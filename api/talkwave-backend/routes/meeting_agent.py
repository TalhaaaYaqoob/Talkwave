"""Meeting Agent API routes.

Provides endpoints for:
  Sessions:
    POST /meeting-agent/sessions          — Create a new meeting agent session
    GET  /meeting-agent/sessions          — List meeting agent sessions
    GET  /meeting-agent/sessions/{id}     — Get session details
    POST /meeting-agent/sessions/{id}/stop — Stop a meeting agent
    GET  /meeting-agent/sessions/{id}/summary — Get post-meeting summary
  Knowledge Base:
    GET  /meeting-agent/kb/documents          — List meeting agent KB docs
    POST /meeting-agent/kb/documents/upload   — Upload a file
    DELETE /meeting-agent/kb/documents/{id}   — Delete a doc
  Calendar Auto-Join:
    GET  /meeting-agent/auto-join/preferences — Get auto-join settings
    PUT  /meeting-agent/auto-join/preferences — Update auto-join settings
    POST /meeting-agent/auto-join/sync-now    — Trigger an immediate calendar sync
    GET  /meeting-agent/auto-join/upcoming    — Preview upcoming meetings
    GET  /meeting-agent/calendar/status        — Check calendar connection status
  WebSocket / Webhook:
    WS   /meeting-agent/ws/{session_id}   — Live transcript/event stream
    POST /meeting-agent/webhook/transcript — Recall.ai transcript webhook
"""

import asyncio
import json
import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel

from api.constants import RECALL_API_KEY, RECALL_WEBHOOK_SECRET
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.meeting.concurrency import (
    check_session_limits,
    register_active_session,
    unregister_active_session,
)
from api.services.meeting.session_store import session_store

router = APIRouter(prefix="/meeting-agent", tags=["meeting-agent"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    meeting_url: str
    agent_name: str = "TalkWave"
    wake_words: list[str] = []
    knowledge_base_id: Optional[int] = None
    workflow_id: Optional[int] = None
    system_prompt: Optional[str] = None
    llm_model: str = "gpt-4o"


class SessionResponse(BaseModel):
    session_id: str
    bot_id: Optional[str] = None
    meeting_url: str
    agent_name: str
    status: str
    created_at: float
    wake_words: list[str] = []
    knowledge_base_id: Optional[int] = None


class SessionSummaryResponse(BaseModel):
    session_id: str
    executive_summary: str = ""
    key_points: list[str] = []
    action_items: list[dict] = []
    decisions_made: list[str] = []
    follow_ups: list[str] = []
    duration_minutes: float = 0.0
    participant_count: int = 0
    speaker_stats: dict = {}
    transcript: list[dict] = []


def _session_to_response(data: dict) -> SessionResponse:
    return SessionResponse(
        session_id=data["session_id"],
        bot_id=data.get("bot_id"),
        meeting_url=data["meeting_url"],
        agent_name=data["agent_name"],
        status=data["status"],
        created_at=data["created_at"],
        wake_words=data.get("wake_words", []),
        knowledge_base_id=data.get("knowledge_base_id"),
    )


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    body: CreateSessionRequest,
    user: UserModel = Depends(get_user),
):
    """Create a meeting agent session — sends a bot to join the meeting."""
    recall_api_key = RECALL_API_KEY or os.getenv("RECALL_API_KEY", "")
    if not recall_api_key:
        raise HTTPException(
            status_code=503,
            detail="Meeting Agent is not configured. Set the RECALL_API_KEY environment variable.",
        )

    limit_msg = await check_session_limits(user.id)
    if limit_msg:
        raise HTTPException(status_code=429, detail=limit_msg)

    from api.services.meeting.pipeline import MeetingAgentPipeline

    session_id = f"ms-{user.id}-{int(time.time())}"

    wake_words = body.wake_words
    if not wake_words and body.workflow_id:
        try:
            from api.db import db_client
            wf = await db_client.get_workflow(body.workflow_id)
            if wf and wf.workflow_definition_with_fallback:
                wf_def = wf.workflow_definition_with_fallback
                for node in wf_def.get("nodes", []):
                    if node.get("type") == "meetingTrigger":
                        trigger_config = node.get("data", {}).get("trigger_config", {})
                        wake_words = trigger_config.get("wake_words", [])
                        break
        except Exception as e:
            logger.warning(f"[MeetingAgent] Could not extract wake words from workflow: {e}")

    if not wake_words:
        name_lower = body.agent_name.lower()
        wake_words = [f"hey {name_lower}", name_lower]

    pipeline = MeetingAgentPipeline(
        recall_api_key=recall_api_key,
        meeting_url=body.meeting_url,
        agent_name=body.agent_name,
        wake_words=wake_words,
        knowledge_base_id=body.knowledge_base_id,
        workflow_id=body.workflow_id,
        user_id=user.id,
        organization_id=user.selected_organization_id,
        llm_model=body.llm_model,
        llm_api_key=os.getenv("OPENAI_API_KEY", ""),
        system_prompt=body.system_prompt,
    )

    try:
        bot_id = await pipeline.start()
    except Exception as e:
        logger.error(f"[MeetingAgent] Failed to create session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to join meeting: {str(e)}")

    session_data = await session_store.create_session(
        session_id=session_id,
        bot_id=bot_id,
        user_id=user.id,
        meeting_url=body.meeting_url,
        agent_name=body.agent_name,
        wake_words=wake_words,
        knowledge_base_id=body.knowledge_base_id,
        workflow_id=body.workflow_id,
        organization_id=user.selected_organization_id,
    )

    session_store.set_pipeline(session_id, pipeline)
    await session_store.try_claim_pipeline_ownership(session_id)

    pipeline.on_transcript(_make_ws_broadcaster(session_id))
    pipeline.on_agent_response(_make_ws_broadcaster(session_id))
    pipeline.on_status_change(_make_status_handler(session_id))

    await register_active_session(session_id, user.id)

    logger.info(
        f"[MeetingAgent] Session created: {session_id} | bot={bot_id} | "
        f"user={user.id} | meeting={body.meeting_url} | pid={os.getpid()}"
    )

    return _session_to_response(session_data)


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(user: UserModel = Depends(get_user)):
    """List all meeting agent sessions for the current user.

    For sessions that still appear active, query Recall.ai for the real
    bot status so stale "joining"/"in_call_recording" entries get corrected.
    """
    sessions = await session_store.list_user_sessions(user.id)

    recall_api_key = RECALL_API_KEY or os.getenv("RECALL_API_KEY", "")
    ended_statuses = {"ended", "call_ended", "fatal", "done"}
    if recall_api_key:
        from api.services.recall.client import RecallClient

        rc = RecallClient(api_key=recall_api_key)
        try:
            for s in sessions:
                if s.get("status") in ended_statuses:
                    if not await session_store.get_summary(s["session_id"]):
                        asyncio.get_event_loop().create_task(
                            _finalize_session(s["session_id"])
                        )
                    continue
                bot_id = s.get("bot_id")
                if not bot_id:
                    continue
                try:
                    live_status = await rc.get_bot_status(bot_id)
                    if live_status in ("call_ended", "done", "fatal"):
                        s["status"] = "ended"
                        await session_store.update_status(s["session_id"], "ended")
                        asyncio.get_event_loop().create_task(
                            _finalize_session(s["session_id"])
                        )
                    elif live_status != s.get("status"):
                        s["status"] = live_status
                        await session_store.update_status(s["session_id"], live_status)
                except Exception:
                    pass
        finally:
            await rc.close()

    return [_session_to_response(s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, user: UserModel = Depends(get_user)):
    """Get details of a specific meeting agent session."""
    session = await session_store.get_session(session_id)
    if not session or session.get("user_id") != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    ended_statuses = {"ended", "call_ended", "fatal", "done"}
    if session.get("status") not in ended_statuses and session.get("bot_id"):
        recall_api_key = RECALL_API_KEY or os.getenv("RECALL_API_KEY", "")
        if recall_api_key:
            from api.services.recall.client import RecallClient

            rc = RecallClient(api_key=recall_api_key)
            try:
                live_status = await rc.get_bot_status(session["bot_id"])
                if live_status in ("call_ended", "done", "fatal"):
                    session["status"] = "ended"
                    await session_store.update_status(session_id, "ended")
                    asyncio.get_event_loop().create_task(
                        _finalize_session(session_id)
                    )
                elif live_status != session.get("status"):
                    session["status"] = live_status
                    await session_store.update_status(session_id, live_status)
            except Exception:
                pass
            finally:
                await rc.close()

    return _session_to_response(session)


@router.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str, user: UserModel = Depends(get_user)):
    """Stop a meeting agent — leaves the meeting and generates summary."""
    session = await session_store.get_session(session_id)
    if not session or session.get("user_id") != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    pipeline = session_store.get_pipeline(session_id)
    if pipeline:
        await pipeline.stop()

    await session_store.update_status(session_id, "ended")
    await session_store.release_pipeline_ownership(session_id)
    await unregister_active_session(session_id, user.id)

    asyncio.get_event_loop().create_task(_finalize_session(session_id))

    logger.info(f"[MeetingAgent] Session stopped: {session_id}")
    return {"status": "stopped", "session_id": session_id}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: UserModel = Depends(get_user)):
    """Delete a meeting session and its summary."""
    session = await session_store.get_session(session_id)
    if not session or session.get("user_id") != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    pipeline = session_store.get_pipeline(session_id)
    if pipeline:
        try:
            await pipeline.stop()
        except Exception:
            pass

    await session_store.release_pipeline_ownership(session_id)
    await unregister_active_session(session_id, user.id)
    await session_store.delete_session(session_id)

    logger.info(f"[MeetingAgent] Session deleted: {session_id}")
    return {"status": "deleted", "session_id": session_id}


@router.get("/sessions/{session_id}/summary", response_model=SessionSummaryResponse)
async def get_session_summary(session_id: str, user: UserModel = Depends(get_user)):
    """Get the post-meeting summary for a completed session.

    Reads from the stored summary in Redis (written when the meeting
    ended).  Falls back to the live pipeline if still in-memory.
    """
    session = await session_store.get_session(session_id)
    if not session or session.get("user_id") != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    stored = await session_store.get_summary(session_id)
    if stored:
        return SessionSummaryResponse(
            session_id=session_id,
            executive_summary=stored.get("executive_summary", ""),
            key_points=stored.get("key_points", []),
            action_items=stored.get("action_items", []),
            decisions_made=stored.get("decisions_made", []),
            follow_ups=stored.get("follow_ups", []),
            duration_minutes=stored.get("duration_minutes", 0.0),
            participant_count=stored.get("participant_count", 0),
            speaker_stats=stored.get("speaker_stats", {}),
            transcript=stored.get("transcript", []),
        )

    pipeline = session_store.get_pipeline(session_id)
    if not pipeline:
        raise HTTPException(
            status_code=400,
            detail="Meeting has not ended yet or summary is not ready",
        )

    try:
        summary = await pipeline.generate_post_meeting_summary()
    except Exception as e:
        logger.error(f"[MeetingAgent] Summary generation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate summary")

    transcript = pipeline.context_manager.get_full_transcript()

    return SessionSummaryResponse(
        session_id=session_id,
        executive_summary=summary.executive_summary,
        key_points=summary.key_points,
        action_items=summary.action_items,
        decisions_made=summary.decisions_made,
        follow_ups=summary.follow_ups,
        duration_minutes=summary.duration_minutes,
        participant_count=summary.participant_count,
        speaker_stats=summary.speaker_stats,
        transcript=transcript,
    )


@router.get("/sessions/{session_id}/summary/markdown")
async def get_session_summary_markdown(session_id: str, user: UserModel = Depends(get_user)):
    """Get the post-meeting summary formatted as markdown."""
    session = await session_store.get_session(session_id)
    if not session or session.get("user_id") != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    stored = await session_store.get_summary(session_id)
    if stored and stored.get("executive_summary"):
        lines = [f"# Meeting Summary\n\n{stored['executive_summary']}\n"]
        if stored.get("key_points"):
            lines.append("## Key Points\n")
            for p in stored["key_points"]:
                lines.append(f"- {p}")
            lines.append("")
        if stored.get("action_items"):
            lines.append("## Action Items\n")
            for a in stored["action_items"]:
                desc = a.get("description", "") if isinstance(a, dict) else str(a)
                lines.append(f"- {desc}")
            lines.append("")
        if stored.get("decisions_made"):
            lines.append("## Decisions Made\n")
            for d in stored["decisions_made"]:
                lines.append(f"- {d}")
            lines.append("")
        if stored.get("follow_ups"):
            lines.append("## Follow-ups\n")
            for f in stored["follow_ups"]:
                lines.append(f"- {f}")
        return {"markdown": "\n".join(lines), "session_id": session_id}

    pipeline = session_store.get_pipeline(session_id)
    if not pipeline:
        raise HTTPException(status_code=400, detail="Summary is not ready yet")

    try:
        summary = await pipeline.generate_post_meeting_summary()
        from api.services.meeting.post_meeting import PostMeetingProcessor
        processor = PostMeetingProcessor()
        markdown = processor.format_summary_markdown(summary)
        return {"markdown": markdown, "session_id": session_id}
    except Exception as e:
        logger.error(f"[MeetingAgent] Markdown summary failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate summary")


@router.get("/sessions/{session_id}/transcript")
async def get_session_transcript(session_id: str, user: UserModel = Depends(get_user)):
    """Get the transcript for a completed or active session."""
    session = await session_store.get_session(session_id)
    if not session or session.get("user_id") != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    stored = await session_store.get_summary(session_id)
    if stored:
        return {
            "transcript": stored.get("transcript", []),
            "speakers": stored.get("speaker_stats", {}),
            "duration_minutes": stored.get("duration_minutes", 0),
        }

    pipeline = session_store.get_pipeline(session_id)
    if not pipeline:
        return {"transcript": [], "speakers": {}}

    return {
        "transcript": pipeline.context_manager.get_full_transcript(),
        "speakers": pipeline.context_manager.get_speaker_stats(),
        "duration_minutes": pipeline.context_manager.duration_minutes,
    }


# ---------------------------------------------------------------------------
# WebSocket — live transcript/event stream
# ---------------------------------------------------------------------------

@router.websocket("/ws/{session_id}")
async def meeting_events_websocket(websocket: WebSocket, session_id: str):
    """WebSocket for streaming real-time meeting events to the frontend."""
    # Authenticate the connecting user via the token query param and ensure the
    # requested session belongs to them (or their organization). This prevents
    # session-id guessing from exposing live meeting transcripts.
    from api.services.auth.depends import get_user

    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="Missing authentication token")
        return
    try:
        user = await get_user(f"Bearer {token}")
    except HTTPException:
        await websocket.close(code=1008, reason="Unauthorized")
        return

    session = await session_store.get_session(session_id)
    if not session:
        await websocket.close(code=4004, reason="Session not found")
        return

    session_user_id = session.get("user_id")
    session_org_id = session.get("organization_id")
    owns_session = session_user_id == user.id or (
        session_org_id is not None
        and session_org_id == user.selected_organization_id
    )
    if not owns_session:
        logger.warning(
            f"[MeetingAgent] WS access denied for session {session_id} "
            f"(user={user.id})"
        )
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await websocket.accept()
    session_store.add_websocket(session_id, websocket)

    logger.info(f"[MeetingAgent] WS connected for session {session_id}")

    try:
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "agent_name": session["agent_name"],
            "status": session["status"],
        })

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(f"[MeetingAgent] WS disconnected for session {session_id}")
    except Exception as e:
        logger.error(f"[MeetingAgent] WS error for {session_id}: {e}")
    finally:
        session_store.remove_websocket(session_id, websocket)


# ---------------------------------------------------------------------------
# Webhook — Recall.ai transcript delivery
# ---------------------------------------------------------------------------

def _verify_recall_signature(
    body: bytes,
    svix_id: Optional[str],
    svix_timestamp: Optional[str],
    svix_signature: Optional[str],
) -> bool:
    """Verify a Svix-style Recall.ai webhook signature (fail closed)."""
    import base64
    import hashlib
    import hmac
    import time as _time

    if not RECALL_WEBHOOK_SECRET:
        logger.error(
            "[MeetingAgent] RECALL_WEBHOOK_SECRET not configured; rejecting webhook"
        )
        return False
    if not (svix_id and svix_timestamp and svix_signature):
        return False

    # Reject stale timestamps (replay protection, 5-minute tolerance).
    try:
        ts = int(svix_timestamp)
        if abs(int(_time.time()) - ts) > 300:
            return False
    except (TypeError, ValueError):
        return False

    secret = RECALL_WEBHOOK_SECRET
    if secret.startswith("whsec_"):
        secret = secret[len("whsec_"):]
    try:
        secret_bytes = base64.b64decode(secret)
    except Exception:
        secret_bytes = secret.encode("utf-8")

    signed_content = f"{svix_id}.{svix_timestamp}.".encode("utf-8") + body
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    ).decode("ascii")

    # The header may contain multiple space-separated "v1,<sig>" entries.
    for part in svix_signature.split():
        _, _, sig = part.partition(",")
        if sig and hmac.compare_digest(sig, expected):
            return True
    return False


@router.post("/webhook/transcript")
async def recall_transcript_webhook(request: Request):
    """Receive real-time transcript data from Recall.ai.

    Uses the Redis-backed bot_id→session_id reverse index for O(1) lookup
    instead of scanning all sessions.
    """
    raw_body = await request.body()

    # Verify the webhook signature before trusting any payload. This prevents
    # forged transcripts from being injected into live sessions.
    if not _verify_recall_signature(
        raw_body,
        request.headers.get("svix-id") or request.headers.get("webhook-id"),
        request.headers.get("svix-timestamp") or request.headers.get("webhook-timestamp"),
        request.headers.get("svix-signature") or request.headers.get("webhook-signature"),
    ):
        logger.warning("[MeetingAgent] REJECTED - invalid Recall webhook signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    import json as _json
    logger.debug(
        f"[MeetingAgent] Webhook raw (truncated): "
        f"{_json.dumps(data, default=str)[:500]}"
    )

    inner = data.get("data", {})
    bot_obj = inner.get("bot", {})
    bot_id = ""
    if isinstance(bot_obj, dict):
        bot_id = bot_obj.get("id", "")
    if not bot_id:
        bot_id = inner.get("bot_id") or data.get("bot_id", "")

    if not bot_id:
        logger.warning(
            f"[MeetingAgent] Webhook has no bot_id. "
            f"event={data.get('event')}, "
            f"data keys={list(inner.keys()) if isinstance(inner, dict) else 'N/A'}"
        )
        return {"status": "ignored"}

    session = await session_store.get_session_by_bot_id(bot_id)

    if not session:
        logger.debug(f"[MeetingAgent] Webhook for unknown bot: {bot_id}")
        return {"status": "ignored"}

    session_id = session["session_id"]
    pipeline = session_store.get_pipeline(session_id)

    if not pipeline:
        if await session_store.has_pipeline_owner(session_id):
            await session_store.push_transcript(bot_id, data)
            logger.debug(
                f"[MeetingAgent] Transcript queued for bot {bot_id[:8]}… "
                f"(pipeline owned by another worker)"
            )
            return {"status": "ok"}
        pipeline = await _try_adopt_session_inline(session)

    if pipeline:
        logger.debug(
            f"[MeetingAgent] Processing transcript locally for bot {bot_id[:8]}…"
        )
        await pipeline.handle_transcript_webhook(data)
    else:
        await session_store.push_transcript(bot_id, data)
        logger.debug(
            f"[MeetingAgent] Transcript queued for bot {bot_id[:8]}… "
            f"(pipeline on another worker)"
        )

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Knowledge Base — upload/list/delete docs for the meeting agent
# ---------------------------------------------------------------------------

MEETING_KB_CONFIG_KEY = "meeting_agent_kb_doc_ids"


class MeetingKBDocResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    file_type: str = "txt"
    file_size_bytes: Optional[int] = None
    chunk_count: Optional[int] = 0
    processing_status: str = "pending"
    created_at: str = ""


async def _get_meeting_kb_doc_ids(org_id: int) -> list[int]:
    """Load the list of KB document IDs tagged for the meeting agent."""
    from api.db import db_client

    config = await db_client.get_configuration(org_id, MEETING_KB_CONFIG_KEY)
    if config and config.value:
        val = config.value
        if isinstance(val, list):
            return [int(v) for v in val]
        if isinstance(val, str):
            try:
                return [int(v) for v in json.loads(val)]
            except Exception:
                return []
    return []


async def _save_meeting_kb_doc_ids(org_id: int, doc_ids: list[int]):
    from api.db import db_client

    await db_client.upsert_configuration(org_id, MEETING_KB_CONFIG_KEY, doc_ids)


@router.get("/kb/documents", response_model=list[MeetingKBDocResponse])
async def list_meeting_kb_docs(user: UserModel = Depends(get_user)):
    """List knowledge base documents attached to the meeting agent."""
    from api.db.knowledge_base_client import knowledge_base_client

    org_id = user.selected_organization_id
    doc_ids = await _get_meeting_kb_doc_ids(org_id)
    if not doc_ids:
        return []

    docs = []
    for did in doc_ids:
        doc = await knowledge_base_client.get_document(did)
        if doc and doc.organization_id == org_id and doc.is_active:
            docs.append(MeetingKBDocResponse(
                id=doc.id,
                name=doc.name,
                description=doc.description,
                file_type=doc.file_type,
                file_size_bytes=doc.file_size_bytes,
                chunk_count=doc.chunk_count,
                processing_status=doc.processing_status,
                created_at=doc.created_at.isoformat() if doc.created_at else "",
            ))
    return docs


@router.post("/kb/documents/upload", response_model=MeetingKBDocResponse)
async def upload_meeting_kb_doc(
    file: UploadFile = File(...),
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    user: UserModel = Depends(get_user),
):
    """Upload a file to the meeting agent knowledge base."""
    from api.db.knowledge_base_client import knowledge_base_client
    from api.routes.knowledge_base import (
        chunk_text,
        chunk_text_for_retrieval,
        extract_text_from_docx,
        extract_text_from_xlsx,
    )

    allowed_extensions = [".txt", ".md", ".pdf", ".docx", ".doc", ".xlsx", ".xls"]
    file_ext = ""
    if file.filename:
        file_ext = "." + file.filename.split(".")[-1].lower() if "." in file.filename else ""

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail="File type not supported. Allowed: TXT, MD, PDF, DOCX, XLSX",
        )

    try:
        content = await file.read()
        file_type = "txt"
        text_content = ""

        if file.filename:
            fn = file.filename.lower()
            if fn.endswith(".md"):
                file_type = "md"
                text_content = content.decode("utf-8")
            elif fn.endswith(".pdf"):
                file_type = "pdf"
                text_content = content.decode("utf-8")
            elif fn.endswith(".docx"):
                file_type = "docx"
                text_content = extract_text_from_docx(content)
            elif fn.endswith((".xlsx", ".xls")):
                file_type = "xlsx"
                text_content = extract_text_from_xlsx(content)
            else:
                text_content = content.decode("utf-8")
        else:
            text_content = content.decode("utf-8")

        if not text_content.strip():
            raise HTTPException(status_code=400, detail="File is empty or could not be read")

        org_id = user.selected_organization_id
        doc_name = name or file.filename or "Meeting Agent Document"

        doc = await knowledge_base_client.create_document(
            organization_id=org_id,
            name=doc_name,
            content=text_content,
            file_type=file_type,
            description=description or "Meeting Agent KB",
            file_size_bytes=len(content),
            created_by=user.id,
        )

        if len(text_content) > 15000:
            chunks = chunk_text_for_retrieval(
                text_content, document_name=doc_name, chunk_size=2000, overlap=200
            )
        else:
            chunks = chunk_text(text_content)

        if chunks:
            created_chunks = await knowledge_base_client.create_chunks(doc.id, chunks)
            await knowledge_base_client.update_document(
                doc.id, processing_status="completed", chunk_count=len(chunks)
            )
            try:
                from api.services.workflow.knowledge_base_retrieval import embed_and_store_chunks

                await embed_and_store_chunks(
                    [c.id for c in created_chunks],
                    [c.content for c in created_chunks],
                    organization_id=org_id,
                    document_id=doc.id,
                )
            except Exception as emb_err:
                logger.warning(f"Non-fatal: embedding failed: {emb_err}")
        else:
            await knowledge_base_client.update_document(
                doc.id, processing_status="completed", chunk_count=0
            )

        doc_ids = await _get_meeting_kb_doc_ids(org_id)
        doc_ids.append(doc.id)
        await _save_meeting_kb_doc_ids(org_id, doc_ids)

        doc = await knowledge_base_client.get_document(doc.id)
        logger.info(f"[MeetingAgent] KB doc uploaded: {doc.id} ({doc_name})")

        return MeetingKBDocResponse(
            id=doc.id,
            name=doc.name,
            description=doc.description,
            file_type=doc.file_type,
            file_size_bytes=doc.file_size_bytes,
            chunk_count=doc.chunk_count,
            processing_status=doc.processing_status,
            created_at=doc.created_at.isoformat() if doc.created_at else "",
        )

    except HTTPException:
        raise
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Could not decode file as UTF-8 text")
    except Exception as e:
        logger.error(f"[MeetingAgent] KB upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/kb/documents/{document_id}")
async def delete_meeting_kb_doc(document_id: int, user: UserModel = Depends(get_user)):
    """Remove a document from the meeting agent knowledge base."""
    from api.db.knowledge_base_client import knowledge_base_client

    org_id = user.selected_organization_id
    doc_ids = await _get_meeting_kb_doc_ids(org_id)

    if document_id not in doc_ids:
        raise HTTPException(status_code=404, detail="Document not in meeting agent KB")

    doc = await knowledge_base_client.get_document(document_id)
    if not doc or doc.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        from api.services.vector import qdrant_service

        await qdrant_service.delete_by_document(document_id)
    except Exception as e:
        logger.warning(f"[MeetingAgent] Failed to delete vectors: {e}")

    await knowledge_base_client.delete_document(document_id)

    doc_ids = [d for d in doc_ids if d != document_id]
    await _save_meeting_kb_doc_ids(org_id, doc_ids)

    logger.info(f"[MeetingAgent] KB doc deleted: {document_id}")
    return {"status": "deleted", "document_id": document_id}


# ---------------------------------------------------------------------------
# Calendar Auto-Join
# ---------------------------------------------------------------------------

class AutoJoinPreferencesRequest(BaseModel):
    enabled: bool = False
    agent_name: str = "TalkWave"
    wake_words: list[str] = []
    llm_model: str = "gpt-4o"
    system_prompt: str = ""
    knowledge_base_id: Optional[int] = None
    providers: list[str] = ["google"]
    workflow_id: Optional[int] = None


class AutoJoinPreferencesResponse(BaseModel):
    enabled: bool
    agent_name: str
    wake_words: list[str]
    llm_model: str
    system_prompt: str
    knowledge_base_id: Optional[int]
    providers: list[str]
    workflow_id: Optional[int] = None


class CalendarStatusResponse(BaseModel):
    google_connected: bool = False
    outlook_connected: bool = False


class UpcomingMeetingResponse(BaseModel):
    event_id: str
    title: str
    start_time: str
    end_time: str
    meeting_url: str = ""
    organizer: str = ""
    source: str = "google"
    already_scheduled: bool = False
    has_meeting_link: bool = True


@router.get("/auto-join/preferences", response_model=AutoJoinPreferencesResponse)
async def get_auto_join_prefs(user: UserModel = Depends(get_user)):
    """Get the user's auto-join preferences."""
    from api.services.meeting.auto_join import get_auto_join_preferences

    prefs = await get_auto_join_preferences(user.selected_organization_id)
    return AutoJoinPreferencesResponse(
        enabled=prefs.enabled,
        agent_name=prefs.agent_name,
        wake_words=prefs.wake_words,
        llm_model=prefs.llm_model,
        system_prompt=prefs.system_prompt,
        knowledge_base_id=prefs.knowledge_base_id,
        providers=prefs.providers,
        workflow_id=prefs.workflow_id,
    )


@router.put("/auto-join/preferences", response_model=AutoJoinPreferencesResponse)
async def update_auto_join_prefs(
    body: AutoJoinPreferencesRequest,
    user: UserModel = Depends(get_user),
):
    """Update auto-join preferences. Toggling enabled on/off starts/stops auto-join."""
    from api.services.meeting.auto_join import (
        AutoJoinPreferences,
        save_auto_join_preferences,
        run_auto_join_cycle,
    )

    prefs = AutoJoinPreferences(
        enabled=body.enabled,
        agent_name=body.agent_name,
        wake_words=body.wake_words,
        llm_model=body.llm_model,
        system_prompt=body.system_prompt,
        knowledge_base_id=body.knowledge_base_id,
        providers=body.providers,
        workflow_id=body.workflow_id,
    )
    await save_auto_join_preferences(user.selected_organization_id, prefs)

    logger.info(
        f"[MeetingAgent] Auto-join {'enabled' if prefs.enabled else 'disabled'} "
        f"for org {user.selected_organization_id}"
    )

    if prefs.enabled:
        asyncio.get_event_loop().create_task(
            run_auto_join_cycle(user.selected_organization_id, user.id)
        )

    return AutoJoinPreferencesResponse(
        enabled=prefs.enabled,
        agent_name=prefs.agent_name,
        wake_words=prefs.wake_words,
        llm_model=prefs.llm_model,
        system_prompt=prefs.system_prompt,
        knowledge_base_id=prefs.knowledge_base_id,
        providers=prefs.providers,
        workflow_id=prefs.workflow_id,
    )


@router.post("/auto-join/sync-now")
async def trigger_sync_now(user: UserModel = Depends(get_user)):
    """Manually trigger a calendar sync cycle.

    Also clears stale/failed schedule entries from the database so
    events get retried.
    """
    from api.services.meeting.auto_join import (
        _SCHED_KEY_PREFIX,
        _TERMINAL_STATUSES,
        run_auto_join_cycle,
    )
    from api.db import db_client

    recall_api_key = RECALL_API_KEY or os.getenv("RECALL_API_KEY", "")
    if not recall_api_key:
        raise HTTPException(status_code=503, detail="RECALL_API_KEY not configured")

    cleared = 0
    try:
        configs = await db_client.get_all_configurations(user.selected_organization_id)
        for cfg in configs:
            if not cfg.key.startswith(_SCHED_KEY_PREFIX):
                continue
            import json as _json
            try:
                data = _json.loads(cfg.value) if isinstance(cfg.value, str) else cfg.value
                session_id = data.get("session_id") if isinstance(data, dict) else cfg.value
            except Exception:
                session_id = None

            should_clear = False
            if not session_id or session_id == "failed":
                should_clear = True
            else:
                session = await session_store.get_session(session_id)
                if session is None:
                    should_clear = True
                elif (session.get("status") or "").lower() in _TERMINAL_STATUSES:
                    should_clear = True

            if should_clear:
                await db_client.delete_configuration(user.selected_organization_id, cfg.key)
                cleared += 1
    except Exception as e:
        logger.warning(f"[MeetingAgent] Failed to clear stale schedules: {e}")

    if cleared:
        logger.info(f"[MeetingAgent] Cleared {cleared} stale schedule entries")

    try:
        await run_auto_join_cycle(user.selected_organization_id, user.id)
        return {"status": "sync_completed", "stale_cleared": cleared}
    except Exception as e:
        logger.error(f"[MeetingAgent] Manual sync failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


@router.get("/auto-join/upcoming", response_model=list[UpcomingMeetingResponse])
async def get_upcoming_meetings(user: UserModel = Depends(get_user)):
    """Preview upcoming meetings that would be auto-joined."""
    from api.services.meeting.calendar_sync import calendar_sync_service
    from api.services.meeting.auto_join import (
        _SCHED_KEY_PREFIX,
        get_auto_join_preferences,
    )
    from api.db import db_client

    prefs = await get_auto_join_preferences(user.selected_organization_id)
    org_id = user.selected_organization_id

    all_events = []
    for provider in prefs.providers:
        try:
            events = await calendar_sync_service.fetch_upcoming_meetings(
                organization_id=org_id,
                lookahead_minutes=1440,
                provider=provider,
                require_meeting_url=False,
            )
            all_events.extend(events)
        except Exception as e:
            logger.warning(f"[MeetingAgent] Failed to fetch {provider} events: {e}")

    result = []
    for event in all_events:
        sched_val = await db_client.get_configuration_value(
            org_id, f"{_SCHED_KEY_PREFIX}{event.event_id}"
        )
        scheduled = sched_val is not None
        has_link = bool(event.meeting_url)
        result.append(UpcomingMeetingResponse(
            event_id=event.event_id,
            title=event.title,
            start_time=event.start_time.isoformat(),
            end_time=event.end_time.isoformat(),
            meeting_url=event.meeting_url or "",
            organizer=event.organizer or "",
            source=event.source,
            already_scheduled=scheduled,
            has_meeting_link=has_link,
        ))
    return result


@router.get("/calendar/status", response_model=CalendarStatusResponse)
async def get_calendar_status(user: UserModel = Depends(get_user)):
    """Check which calendar providers are connected via Composio.

    Checks both the local DB and the Composio SDK directly so that connections
    made through the OAuth flow but not yet synced to our DB are still detected.
    """
    from api.services.integrations.composio_service import composio_service

    org_id = user.selected_organization_id
    google_ok = False
    outlook_ok = False

    try:
        connections = await composio_service._get_stored_connections(org_id)
        for conn in connections:
            if conn.get("app_id") == "googlecalendar" and conn.get("is_active"):
                google_ok = True
            if conn.get("app_id") == "outlookcalendar" and conn.get("is_active"):
                outlook_ok = True
    except Exception as e:
        logger.warning(f"[MeetingAgent] Calendar status (DB) check failed: {e}")

    if not google_ok or not outlook_ok:
        try:
            sdk_status = await asyncio.to_thread(
                composio_service._get_sdk_connections, org_id
            )
            if not google_ok:
                conn = sdk_status.get("googlecalendar") or sdk_status.get("GOOGLECALENDAR") or {}
                if str(conn.get("status", "")).upper() == "ACTIVE":
                    google_ok = True
            if not outlook_ok:
                conn = sdk_status.get("outlook") or sdk_status.get("OUTLOOK") or {}
                if str(conn.get("status", "")).upper() == "ACTIVE":
                    outlook_ok = True
        except Exception as e:
            logger.warning(f"[MeetingAgent] Calendar status (SDK) check failed: {e}")

    return CalendarStatusResponse(
        google_connected=google_ok,
        outlook_connected=outlook_ok,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _try_adopt_session_inline(session: dict):
    """If no worker owns this session's pipeline, adopt it on this worker.

    Called from the webhook handler so the very first transcript after a
    deploy/restart triggers immediate pipeline re-creation instead of
    waiting for the next auto-join cycle.

    Uses a Redis SETNX lock to ensure only one worker can adopt a given
    session, preventing duplicate agents from speaking simultaneously.
    """
    session_id = session.get("session_id", "")
    bot_id = session.get("bot_id", "")
    status = (session.get("status") or "").lower()
    if status in ("ended", "stopped", "call_ended", "fatal", "done", "error"):
        return None

    recall_api_key = RECALL_API_KEY or os.getenv("RECALL_API_KEY", "")
    if not recall_api_key or not bot_id:
        return None

    claimed = await session_store.try_claim_pipeline_ownership(session_id)
    if not claimed:
        logger.debug(
            f"[MeetingAgent] Cannot adopt {session_id}: "
            f"another worker already owns it"
        )
        return None

    try:
        from api.services.meeting.auto_join import (
            _expand_wake_words,
            get_auto_join_preferences,
        )
        from api.services.meeting.pipeline import MeetingAgentPipeline

        org_id = session.get("organization_id") or session.get("org_id")
        user_id = session.get("user_id")
        if not org_id or not user_id:
            await session_store.release_pipeline_ownership(session_id)
            return None

        prefs = await get_auto_join_preferences(org_id)

        wake_words = session.get("wake_words") or []
        if not wake_words:
            wake_words = _expand_wake_words(prefs.wake_words, prefs.agent_name)

        pipeline = MeetingAgentPipeline(
            recall_api_key=recall_api_key,
            meeting_url=session.get("meeting_url", ""),
            agent_name=session.get("agent_name", prefs.agent_name),
            wake_words=wake_words,
            knowledge_base_id=session.get("knowledge_base_id"),
            workflow_id=session.get("workflow_id") or prefs.workflow_id,
            user_id=user_id,
            organization_id=org_id,
            llm_model=prefs.llm_model,
            llm_api_key=os.getenv("OPENAI_API_KEY", ""),
            system_prompt=prefs.system_prompt or None,
        )
        pipeline._bot_id = bot_id
        pipeline._running = True

        await pipeline.pre_warm_pools()

        pipeline._poll_task = asyncio.create_task(pipeline._poll_bot_status())
        pipeline._transcript_drain_task = asyncio.create_task(
            pipeline._drain_transcript_queue()
        )

        session_store.set_pipeline(session_id, pipeline)

        pipeline.on_transcript(_make_ws_broadcaster(session_id))
        pipeline.on_agent_response(_make_ws_broadcaster(session_id))
        pipeline.on_status_change(_make_status_handler(session_id))

        logger.info(
            f"[MeetingAgent] Adopted orphaned session {session_id} inline "
            f"(bot {bot_id[:12]}, pid={os.getpid()})"
        )
        return pipeline
    except Exception as e:
        await session_store.release_pipeline_ownership(session_id)
        logger.warning(f"[MeetingAgent] Inline adoption failed for {session_id}: {e}")
        return None


def _make_ws_broadcaster(session_id: str):
    """Create an async callback that broadcasts events via the session store."""
    async def broadcast(event: dict):
        await session_store.broadcast_to_session(session_id, event)
    return broadcast


def _make_status_handler(session_id: str):
    """Create an async callback that updates session status in Redis
    and generates + saves the summary when the meeting ends."""
    async def handle_status(event: dict):
        new_status = event.get("status", "")
        is_ended = new_status in ("call_ended", "fatal", "done")
        if is_ended:
            new_status = "ended"
        await session_store.update_status(session_id, new_status)

        if is_ended:
            asyncio.get_event_loop().create_task(
                _finalize_session(session_id)
            )

    return handle_status


async def _finalize_session(session_id: str):
    """Fetch transcript from Recall.ai, generate summary, and store both."""
    try:
        session = await session_store.get_session(session_id)
        if not session:
            return
        bot_id = session.get("bot_id")
        if not bot_id:
            return

        recall_api_key = RECALL_API_KEY or os.getenv("RECALL_API_KEY", "")
        if not recall_api_key:
            return

        from api.services.recall.client import RecallClient

        rc = RecallClient(api_key=recall_api_key)
        try:
            transcript_data = await rc.get_transcript(bot_id)
        except Exception as e:
            logger.error(f"[MeetingAgent] Failed to fetch transcript for {bot_id}: {e}")
            transcript_data = []
        finally:
            await rc.close()

        transcript = []
        for entry in transcript_data:
            speaker = entry.get("speaker", "Unknown")
            words = entry.get("words", [])
            if isinstance(words, list):
                text = " ".join(w.get("text", "") for w in words if isinstance(w, dict))
            elif isinstance(words, str):
                text = words
            else:
                text = str(words)
            if text.strip():
                transcript.append({"speaker": speaker, "text": text.strip()})

        summary_data: dict = {
            "session_id": session_id,
            "transcript": transcript,
            "executive_summary": "",
            "key_points": [],
            "action_items": [],
            "decisions_made": [],
            "follow_ups": [],
            "duration_minutes": 0.0,
            "participant_count": 0,
            "speaker_stats": {},
        }

        pipeline = session_store.get_pipeline(session_id)
        if pipeline and hasattr(pipeline, "generate_post_meeting_summary"):
            try:
                summary = await pipeline.generate_post_meeting_summary()
                summary_data.update({
                    "executive_summary": summary.executive_summary,
                    "key_points": summary.key_points,
                    "action_items": summary.action_items,
                    "decisions_made": summary.decisions_made,
                    "follow_ups": summary.follow_ups,
                    "duration_minutes": summary.duration_minutes,
                    "participant_count": summary.participant_count,
                    "speaker_stats": summary.speaker_stats,
                })
            except Exception as e:
                logger.error(f"[MeetingAgent] Summary generation failed: {e}")

        await session_store.save_summary(session_id, summary_data)
        logger.info(
            f"[MeetingAgent] Finalized session {session_id}: "
            f"{len(transcript)} transcript entries saved"
        )
    except Exception as e:
        logger.error(f"[MeetingAgent] Finalize error for {session_id}: {e}", exc_info=True)
