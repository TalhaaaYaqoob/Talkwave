"""Auto-join scheduler for meeting agent.

Runs as a background asyncio task that:
  1. Polls connected calendars for upcoming meetings every ~2 minutes
  2. For each meeting with a video link, checks if a bot is already scheduled
  3. If not, creates a Recall.ai bot 1 minute before the meeting starts
  4. Tracks scheduled bots in the persistent database (org config) to survive
     worker restarts and avoid lost state.  Redis is only used for the
     distributed worker lock.

User preferences (stored in org config via db_client):
  - auto_join_enabled: bool
  - auto_join_agent_name: str
  - auto_join_wake_words: list[str]
  - auto_join_llm_model: str
  - auto_join_system_prompt: str
  - auto_join_knowledge_base_id: int | None
  - auto_join_providers: list[str]  (["google", "outlook"])
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from api.constants import (
    RECALL_API_KEY,
    REDIS_URL,
)


SCHEDULER_LOCK = "meeting:autojoin:lock"
POLL_INTERVAL_SECONDS = 30
JOIN_BEFORE_MINUTES = 1
_SCHED_KEY_PREFIX = "autojoin_scheduled_"


def _expand_wake_words(
    user_wake_words: list[str], agent_name: str
) -> list[str]:
    """Build a wake word list from user-defined words or the agent name.

    If the workflow provides explicit wake words, ONLY those are used
    (plus "hey" variants and base-word extraction). The agent name is
    NOT added so it doesn't accidentally trigger the bot.

    Falls back to agent-name-based wake words only when no explicit
    wake words are configured.
    """
    seen: set[str] = set()
    result: list[str] = []

    def _add(w: str):
        w = w.lower().strip()
        if w and w not in seen and len(w) > 1:
            seen.add(w)
            result.append(w)

    has_explicit = bool(user_wake_words)

    if has_explicit:
        for uw in user_wake_words:
            uw_lower = uw.lower().strip()
            _add(uw_lower)
            if uw_lower.startswith("hey "):
                _add(uw_lower[4:])
            else:
                _add(f"hey {uw_lower}")
    else:
        name_lower = agent_name.lower().strip()
        _add(f"hey {name_lower}")
        _add(name_lower)
        for word in name_lower.split():
            if len(word) > 2:
                _add(f"hey {word}")
                _add(word)

    return result


class AutoJoinPreferences:
    """User preferences for auto-join, stored in org configuration."""

    def __init__(
        self,
        enabled: bool = False,
        agent_name: str = "TalkWave",
        wake_words: Optional[list[str]] = None,
        llm_model: str = "gpt-4o",
        system_prompt: str = "",
        knowledge_base_id: Optional[int] = None,
        providers: Optional[list[str]] = None,
        workflow_id: Optional[int] = None,
    ):
        self.enabled = enabled
        self.agent_name = agent_name
        self.wake_words = wake_words or []
        self.llm_model = llm_model
        self.system_prompt = system_prompt
        self.knowledge_base_id = knowledge_base_id
        self.providers = providers or ["google"]
        self.workflow_id = workflow_id


async def get_auto_join_preferences(organization_id: int) -> AutoJoinPreferences:
    """Load auto-join preferences from org configuration."""
    from api.db import db_client

    try:
        keys = [
            "meeting_auto_join_enabled",
            "meeting_auto_join_agent_name",
            "meeting_auto_join_wake_words",
            "meeting_auto_join_llm_model",
            "meeting_auto_join_system_prompt",
            "meeting_auto_join_kb_id",
            "meeting_auto_join_providers",
            "meeting_auto_join_workflow_id",
        ]
        configs = await db_client.get_configurations_by_keys(organization_id, keys)
        if not configs:
            return AutoJoinPreferences()

        def _val(key: str, default: str = "") -> str:
            model = configs.get(key)
            return model.value if model else default

        import json

        return AutoJoinPreferences(
            enabled=_val("meeting_auto_join_enabled") == "true",
            agent_name=_val("meeting_auto_join_agent_name", "TalkWave"),
            wake_words=json.loads(_val("meeting_auto_join_wake_words", "[]")),
            llm_model=_val("meeting_auto_join_llm_model", "gpt-4o"),
            system_prompt=_val("meeting_auto_join_system_prompt"),
            knowledge_base_id=int(_val("meeting_auto_join_kb_id"))
            if _val("meeting_auto_join_kb_id")
            else None,
            providers=json.loads(_val("meeting_auto_join_providers", '["google"]')),
            workflow_id=int(_val("meeting_auto_join_workflow_id"))
            if _val("meeting_auto_join_workflow_id")
            else None,
        )
    except Exception as e:
        logger.debug(f"[AutoJoin] Prefs load failed for org {organization_id}: {e}")
        return AutoJoinPreferences()


async def save_auto_join_preferences(organization_id: int, prefs: AutoJoinPreferences):
    """Save auto-join preferences to org configuration."""
    import json
    from api.db import db_client

    pairs = {
        "meeting_auto_join_enabled": "true" if prefs.enabled else "false",
        "meeting_auto_join_agent_name": prefs.agent_name,
        "meeting_auto_join_wake_words": json.dumps(prefs.wake_words),
        "meeting_auto_join_llm_model": prefs.llm_model,
        "meeting_auto_join_system_prompt": prefs.system_prompt,
        "meeting_auto_join_kb_id": str(prefs.knowledge_base_id) if prefs.knowledge_base_id else "",
        "meeting_auto_join_providers": json.dumps(prefs.providers),
        "meeting_auto_join_workflow_id": str(prefs.workflow_id) if prefs.workflow_id else "",
    }

    for key, value in pairs.items():
        await db_client.upsert_configuration(organization_id, key, value)


_TERMINAL_STATUSES = {"stopped", "call_ended", "fatal", "done", "error", "ended"}
REJOIN_COOLDOWN_SECONDS = 60


async def _is_already_scheduled(organization_id: int, event_id: str) -> bool:
    """Check if a meeting has already been *successfully* scheduled.

    Uses the persistent database instead of volatile Redis to survive
    worker restarts and avoid lost state on memory pressure.

    Returns False for failed attempts so the scheduler retries.
    Also validates that the session is still tracked and the bot is
    still active; if the session ended or was cleaned up, the entry
    is stale and we allow a retry (re-join) after a cooldown.
    """
    import json as _json
    from api.db import db_client

    key = f"{_SCHED_KEY_PREFIX}{event_id}"
    raw = await db_client.get_configuration_value(organization_id, key)
    if raw is None:
        return False

    try:
        data = _json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        data = {"session_id": raw}

    session_id = data.get("session_id") if isinstance(data, dict) else raw
    created_at = data.get("created_at", 0) if isinstance(data, dict) else 0
    if not session_id or session_id == "failed":
        return False

    from api.services.meeting.session_store import session_store

    session = await session_store.get_session(session_id)
    if session is None:
        age = time.time() - created_at if created_at else float("inf")
        if age < REJOIN_COOLDOWN_SECONDS:
            logger.debug(
                f"[AutoJoin] Session {session_id} gone but only {age:.0f}s old "
                f"(cooldown {REJOIN_COOLDOWN_SECONDS}s), blocking re-join"
            )
            return True
        logger.info(
            f"[AutoJoin] Stale schedule for event {event_id} "
            f"(session {session_id} no longer exists), allowing retry"
        )
        await _clear_scheduled(organization_id, event_id)
        return False

    status = (session.get("status") or "").lower()
    if status in _TERMINAL_STATUSES:
        age = time.time() - created_at if created_at else float("inf")
        if age < REJOIN_COOLDOWN_SECONDS:
            logger.debug(
                f"[AutoJoin] Session {session_id} ended but only {age:.0f}s old "
                f"(cooldown {REJOIN_COOLDOWN_SECONDS}s), blocking re-join"
            )
            return True
        logger.info(
            f"[AutoJoin] Previous session {session_id} for event {event_id} "
            f"has terminal status '{status}' and is old enough, allowing re-join"
        )
        await _clear_scheduled(organization_id, event_id)
        return False

    pipeline = session_store.get_pipeline(session_id)

    if pipeline is not None and hasattr(pipeline, "is_running") and not pipeline.is_running:
        age = time.time() - created_at if created_at else float("inf")
        if age < REJOIN_COOLDOWN_SECONDS:
            logger.debug(
                f"[AutoJoin] Pipeline for {session_id} stopped but only {age:.0f}s old, "
                f"blocking re-join"
            )
            return True
        logger.info(
            f"[AutoJoin] Previous pipeline for session {session_id} is no longer "
            f"running, allowing re-join for event {event_id}"
        )
        await _clear_scheduled(organization_id, event_id)
        return False

    if pipeline is not None:
        return True

    bot_id = session.get("bot_id")
    if bot_id:
        recall_api_key = RECALL_API_KEY or os.getenv("RECALL_API_KEY", "")
        if recall_api_key:
            try:
                from api.services.recall.client import RecallClient
                rc = RecallClient(api_key=recall_api_key)
                try:
                    live_status = await rc.get_bot_status(bot_id)
                finally:
                    await rc.close()

                if live_status in ("call_ended", "done", "fatal"):
                    logger.info(
                        f"[AutoJoin] Orphaned session {session_id} — Recall bot "
                        f"{bot_id[:12]} has status '{live_status}', clearing"
                    )
                    await session_store.update_status(session_id, "ended")
                    await _clear_scheduled(organization_id, event_id)
                    return False

                logger.debug(
                    f"[AutoJoin] Orphaned session {session_id} — Recall bot "
                    f"still active (status={live_status}), keeping schedule"
                )
                return True
            except Exception as e:
                logger.warning(
                    f"[AutoJoin] Could not check Recall bot {bot_id[:12]}: {e}"
                )

    age = time.time() - created_at if created_at else float("inf")
    if age > 120:
        logger.info(
            f"[AutoJoin] Orphaned session {session_id} (no pipeline, {age:.0f}s old), "
            f"clearing stale schedule for event {event_id}"
        )
        await session_store.update_status(session_id, "ended")
        await _clear_scheduled(organization_id, event_id)
        return False

    return True


async def _mark_scheduled(organization_id: int, event_id: str, session_id: str):
    """Mark a meeting as scheduled in the persistent database."""
    import json as _json
    from api.db import db_client

    key = f"{_SCHED_KEY_PREFIX}{event_id}"
    value = _json.dumps({"session_id": session_id, "created_at": time.time()})
    await db_client.upsert_configuration(organization_id, key, value)


async def _clear_scheduled(organization_id: int, event_id: str):
    """Remove a stale scheduling entry from the database."""
    from api.db import db_client

    key = f"{_SCHED_KEY_PREFIX}{event_id}"
    try:
        await db_client.delete_configuration(organization_id, key)
    except Exception:
        pass


async def _try_acquire_lock(r: aioredis.Redis, ttl: int = 30) -> bool:
    """Distributed lock so only one worker runs the scheduler at a time."""
    return await r.set(SCHEDULER_LOCK, "1", nx=True, ex=ttl)


async def _has_active_bot_for_url(user_id: int, meeting_url: str) -> bool:
    """Check if there's already an active (non-terminal) bot for this meeting URL."""
    from api.services.meeting.session_store import session_store

    sessions = await session_store.list_user_sessions(user_id)
    for s in sessions:
        if (
            s.get("meeting_url") == meeting_url
            and (s.get("status") or "").lower() not in _TERMINAL_STATUSES
        ):
            return True
    return False


async def _adopt_orphaned_sessions(
    organization_id: int,
    user_id: int,
    recall_api_key: str,
    prefs: AutoJoinPreferences,
):
    """Re-create pipelines for sessions whose Recall bot is still active
    but no worker owns the pipeline (e.g. after a deploy/restart).

    Uses the Redis ownership lock to ensure only ONE worker ever adopts
    a given session.  If another worker already owns it, skip silently.
    """
    from api.services.meeting.session_store import session_store
    from api.services.meeting.pipeline import MeetingAgentPipeline

    sessions = await session_store.list_user_sessions(user_id)
    for session in sessions:
        status = (session.get("status") or "").lower()
        if status in _TERMINAL_STATUSES:
            continue
        session_id = session.get("session_id", "")
        if session_store.get_pipeline(session_id) is not None:
            continue

        if await session_store.has_pipeline_owner(session_id):
            continue

        bot_id = session.get("bot_id")
        if not bot_id:
            continue

        try:
            from api.services.recall.client import RecallClient
            rc = RecallClient(api_key=recall_api_key)
            try:
                live_status = await rc.get_bot_status(bot_id)
            finally:
                await rc.close()

            if live_status in ("call_ended", "done", "fatal"):
                await session_store.update_status(session_id, "ended")
                logger.info(
                    f"[AutoJoin] Orphan {session_id}: bot {bot_id[:12]} ended "
                    f"(status={live_status}), marked ended"
                )
                continue

            claimed = await session_store.try_claim_pipeline_ownership(session_id)
            if not claimed:
                logger.debug(
                    f"[AutoJoin] Skipping {session_id}: another worker "
                    f"claimed ownership between check and adopt"
                )
                continue

            logger.info(
                f"[AutoJoin] Adopting orphaned session {session_id} "
                f"(bot {bot_id[:12]} status={live_status}, pid={os.getpid()})"
            )

            wake_words = session.get("wake_words") or []
            if not wake_words:
                wake_words = _expand_wake_words(
                    prefs.wake_words, prefs.agent_name
                )

            pipeline = MeetingAgentPipeline(
                recall_api_key=recall_api_key,
                meeting_url=session.get("meeting_url", ""),
                agent_name=session.get("agent_name", prefs.agent_name),
                wake_words=wake_words,
                knowledge_base_id=session.get("knowledge_base_id"),
                workflow_id=session.get("workflow_id") or prefs.workflow_id,
                user_id=user_id,
                organization_id=organization_id,
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

            from api.routes.meeting_agent import (
                _make_ws_broadcaster,
                _make_status_handler,
            )
            pipeline.on_transcript(_make_ws_broadcaster(session_id))
            pipeline.on_agent_response(_make_ws_broadcaster(session_id))
            pipeline.on_status_change(_make_status_handler(session_id))

            logger.info(
                f"[AutoJoin] Adopted session {session_id} — pipeline re-created, "
                f"drain loop started for bot {bot_id[:12]}"
            )

        except Exception as e:
            await session_store.release_pipeline_ownership(session_id)
            logger.error(
                f"[AutoJoin] Failed to adopt session {session_id}: {e}",
                exc_info=True,
            )


async def run_auto_join_cycle(organization_id: int, user_id: int):
    """Run one cycle of the auto-join scheduler for a single org.

    Called by the background loop for each org that has auto-join enabled.
    """
    from api.services.meeting.calendar_sync import calendar_sync_service
    from api.services.meeting.session_store import session_store
    from api.services.meeting.pipeline import MeetingAgentPipeline
    from api.services.meeting.concurrency import register_active_session

    recall_api_key = RECALL_API_KEY or os.getenv("RECALL_API_KEY", "")
    if not recall_api_key:
        logger.warning("[AutoJoin] RECALL_API_KEY not configured, skipping cycle")
        return

    prefs = await get_auto_join_preferences(organization_id)
    if not prefs.enabled:
        logger.debug(f"[AutoJoin] Auto-join not enabled for org {organization_id}")
        return

    await _adopt_orphaned_sessions(organization_id, user_id, recall_api_key, prefs)

    logger.info(
        f"[AutoJoin] Running cycle for org={organization_id} user={user_id} "
        f"providers={prefs.providers} agent={prefs.agent_name}"
    )

    now = datetime.now(timezone.utc)

    for provider in prefs.providers:
        events = await calendar_sync_service.fetch_upcoming_meetings(
            organization_id=organization_id,
            lookahead_minutes=15,
            provider=provider,
        )

        logger.info(
            f"[AutoJoin] {provider}: {len(events)} events (ongoing + next 15 min)"
        )

        for event in events:
            if await _is_already_scheduled(organization_id, event.event_id):
                logger.debug(
                    f"[AutoJoin] Skipping '{event.title}' (already scheduled)"
                )
                continue

            if event.meeting_url and await _has_active_bot_for_url(user_id, event.meeting_url):
                logger.debug(
                    f"[AutoJoin] Skipping '{event.title}' "
                    f"(active bot already at {event.meeting_url})"
                )
                continue

            minutes_until = (event.start_time - now).total_seconds() / 60
            if minutes_until > 10:
                logger.debug(
                    f"[AutoJoin] Skipping '{event.title}' "
                    f"(starts in {minutes_until:.1f}min, > 10min threshold)"
                )
                continue

            meeting_ended = (
                event.end_time
                and event.end_time < now
            )
            if meeting_ended:
                logger.debug(
                    f"[AutoJoin] Skipping '{event.title}' (already ended)"
                )
                continue

            logger.info(
                f"[AutoJoin] Scheduling bot for '{event.title}' "
                f"starting in {minutes_until:.1f}min | url={event.meeting_url}"
            )

            session_id = f"ms-auto-{user_id}-{int(time.time())}"

            wf_wake_words: list[str] = []
            if prefs.workflow_id:
                try:
                    from api.db import db_client
                    wf = await db_client.get_workflow(prefs.workflow_id)
                    if wf and wf.workflow_definition_with_fallback:
                        for wf_node in wf.workflow_definition_with_fallback.get("nodes", []):
                            if wf_node.get("type") == "meetingTrigger":
                                wf_wake_words = wf_node.get("data", {}).get("trigger_config", {}).get("wake_words", [])
                                break
                except Exception as wf_err:
                    logger.warning(f"[AutoJoin] Could not extract wake words from workflow: {wf_err}")

            wake_words = _expand_wake_words(
                wf_wake_words or prefs.wake_words, prefs.agent_name
            )
            logger.info(
                f"[AutoJoin] Wake words (from {'workflow' if wf_wake_words else 'prefs'}): {wake_words}"
            )

            pipeline = MeetingAgentPipeline(
                recall_api_key=recall_api_key,
                meeting_url=event.meeting_url,
                agent_name=prefs.agent_name,
                wake_words=wake_words,
                knowledge_base_id=prefs.knowledge_base_id,
                workflow_id=prefs.workflow_id,
                user_id=user_id,
                organization_id=organization_id,
                llm_model=prefs.llm_model,
                llm_api_key=os.getenv("OPENAI_API_KEY", ""),
                system_prompt=prefs.system_prompt or None,
            )

            try:
                bot_id = await pipeline.start()

                await session_store.create_session(
                    session_id=session_id,
                    bot_id=bot_id,
                    user_id=user_id,
                    meeting_url=event.meeting_url,
                    agent_name=prefs.agent_name,
                    wake_words=wake_words,
                    knowledge_base_id=prefs.knowledge_base_id,
                    organization_id=organization_id,
                )
                session_store.set_pipeline(session_id, pipeline)
                await session_store.try_claim_pipeline_ownership(session_id)
                await register_active_session(session_id, user_id)
                await _mark_scheduled(organization_id, event.event_id, session_id)

                from api.routes.meeting_agent import _make_ws_broadcaster, _make_status_handler
                pipeline.on_transcript(_make_ws_broadcaster(session_id))
                pipeline.on_agent_response(_make_ws_broadcaster(session_id))
                pipeline.on_status_change(_make_status_handler(session_id))

                logger.info(
                    f"[AutoJoin] Bot created: {bot_id} for '{event.title}' | "
                    f"session={session_id}"
                )

            except Exception as e:
                logger.error(
                    f"[AutoJoin] Failed to join '{event.title}': {e}",
                    exc_info=True,
                )


class AutoJoinScheduler:
    """Background scheduler that polls calendars and auto-joins meetings."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def start(self):
        """Start the background polling loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[AutoJoin] Scheduler started")

    def stop(self):
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("[AutoJoin] Scheduler stopped")

    async def _loop(self):
        await asyncio.sleep(2)

        while self._running:
            try:
                r = aioredis.from_url(REDIS_URL, decode_responses=True)
                try:
                    if not await _try_acquire_lock(r, ttl=POLL_INTERVAL_SECONDS + 30):
                        logger.debug("[AutoJoin] Another worker holds the lock, skipping")
                        await asyncio.sleep(POLL_INTERVAL_SECONDS)
                        continue
                finally:
                    await r.aclose()

                orgs = await self._get_orgs_with_auto_join()
                for org_id, user_id in orgs:
                    try:
                        await run_auto_join_cycle(org_id, user_id)
                    except Exception as e:
                        logger.error(
                            f"[AutoJoin] Cycle failed for org {org_id}: {e}",
                            exc_info=True,
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[AutoJoin] Scheduler error: {e}", exc_info=True)

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _get_orgs_with_auto_join(self) -> list[tuple[int, int]]:
        """Get list of (org_id, user_id) pairs that have auto-join enabled.

        Queries the configuration table for all orgs with the feature turned on,
        joining through organization_users to find a user for each org.

        The configuration `value` column is JSON, so a Python string "true"
        is stored as the JSON scalar `"true"` (with quotes). We cast to text
        and compare against the quoted form so the query works with both
        json and jsonb column types.
        """
        from api.db import db_client

        try:
            result = await db_client.execute_raw_query(
                """
                SELECT DISTINCT ON (c.organization_id)
                       c.organization_id,
                       ou.user_id
                FROM organization_configurations c
                JOIN organization_users ou ON ou.organization_id = c.organization_id
                WHERE c.key = 'meeting_auto_join_enabled'
                  AND c.value::text IN ('"true"', 'true')
                """
            )
            if result:
                return [(row["organization_id"], row["user_id"]) for row in result]
        except Exception as e:
            logger.debug(f"[AutoJoin] Could not query auto-join orgs: {e}")
        return []


auto_join_scheduler = AutoJoinScheduler()
