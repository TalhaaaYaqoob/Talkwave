"""LiveKit Cloud integration routes.

Provides endpoints for:
  - POST /livekit/connect  — Create/join a LiveKit room for a workflow run
  - GET  /livekit/config   — Check if LiveKit is enabled (used by frontend to
                             pick between SmallWebRTC and LiveKit hooks)
  - WS   /ws/livekit/events/{workflow_id}/{workflow_run_id} — UI event stream
    (transcripts, activity, node transitions) while media flows through LiveKit

IMPORTANT: The pipeline is started from the events WebSocket handler, NOT from
the POST handler. This guarantees the pipeline and WebSocket always run in the
same uvicorn worker process, so the in-memory WebSocketBroadcaster can deliver
transcript/activity messages to the connected client.
"""

import asyncio
import json

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel

from api.constants import LIVEKIT_ENABLED, REDIS_URL
from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user, get_user_ws
from api.services.livekit.room_manager import create_room, livekit_enabled
from api.services.pipecat.run_pipeline import run_pipeline_livekit
from api.services.pipecat.websocket_broadcaster import websocket_broadcaster
from pipecat.utils.context import set_current_run_id

router = APIRouter(prefix="/livekit", tags=["livekit"])

_PIPELINE_PARAMS_TTL = 120  # seconds — params expire if WS never connects

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def _params_key(workflow_run_id: int) -> str:
    return f"lk_pipeline_params:{workflow_run_id}"


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


class LiveKitConfigResponse(BaseModel):
    enabled: bool
    url: str = ""


@router.get("/config", response_model=LiveKitConfigResponse)
async def get_livekit_config():
    """Return whether LiveKit is enabled so the frontend can pick the right hook."""
    from api.constants import LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
    from api.services.livekit.room_manager import LIVEKIT_SDK_AVAILABLE

    has_url = bool(LIVEKIT_URL)
    has_key = bool(LIVEKIT_API_KEY)
    has_secret = bool(LIVEKIT_API_SECRET)

    if not (has_url and has_key and has_secret):
        logger.warning(
            f"[LiveKit] Config check: env vars incomplete — "
            f"URL={'set' if has_url else 'MISSING'}, "
            f"API_KEY={'set' if has_key else 'MISSING'}, "
            f"API_SECRET={'set' if has_secret else 'MISSING'}"
        )
        return LiveKitConfigResponse(enabled=False)

    if not LIVEKIT_SDK_AVAILABLE:
        logger.warning(
            "[LiveKit] Config check: env vars are set but livekit-api package "
            "is not installed. Run: pip install livekit-api"
        )
        return LiveKitConfigResponse(enabled=False)

    return LiveKitConfigResponse(enabled=True, url=LIVEKIT_URL)


class LiveKitConnectRequest(BaseModel):
    workflow_id: int
    workflow_run_id: int
    call_context_vars: dict = {}


class LiveKitConnectResponse(BaseModel):
    room_name: str
    livekit_url: str
    user_token: str


@router.post("/connect", response_model=LiveKitConnectResponse)
async def connect_livekit(
    body: LiveKitConnectRequest,
    user: UserModel = Depends(get_user),
):
    """Create a LiveKit room and return the user's connection token.

    The pipeline is NOT started here — it is started by the events WebSocket
    handler to guarantee they share the same worker process.
    """
    if not livekit_enabled():
        raise HTTPException(
            status_code=503,
            detail="LiveKit is not configured. Set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET.",
        )

    import os
    worker_pid = os.getpid()

    logger.info(
        f"[LiveKit][POST /connect] run_id={body.workflow_run_id} | "
        f"worker_pid={worker_pid} | user_id={user.id}"
    )

    workflow_run = await db_client.get_workflow_run(body.workflow_run_id, user.id)
    if not workflow_run:
        # Fail closed on IDOR: the run must exist and belong to the caller.
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if workflow_run.workflow_id != body.workflow_id:
        raise HTTPException(status_code=403, detail="Run does not match workflow")
    if workflow_run.is_completed:
        logger.warning(
            f"[LiveKit][POST /connect] run_id={body.workflow_run_id} REJECTED — "
            f"run already completed"
        )
        raise HTTPException(
            status_code=400,
            detail="This call has already ended. Please start a new call.",
        )

    room_info = await create_room(body.workflow_run_id)
    logger.info(
        f"[LiveKit][POST /connect] run_id={body.workflow_run_id} | "
        f"room={room_info['room_name']} created"
    )

    r = await _get_redis()
    params = {
        "livekit_url": room_info["livekit_url"],
        "livekit_token": room_info["agent_token"],
        "room_name": room_info["room_name"],
        "workflow_id": body.workflow_id,
        "workflow_run_id": body.workflow_run_id,
        "user_id": user.id,
        "call_context_vars": body.call_context_vars,
    }
    redis_key = _params_key(body.workflow_run_id)
    await r.set(redis_key, json.dumps(params), ex=_PIPELINE_PARAMS_TTL)

    logger.info(
        f"[LiveKit][POST /connect] run_id={body.workflow_run_id} | "
        f"pipeline params saved to Redis key={redis_key} | "
        f"worker_pid={worker_pid} (pipeline will start from WS handler)"
    )

    return LiveKitConnectResponse(
        room_name=room_info["room_name"],
        livekit_url=room_info["livekit_url"],
        user_token=room_info["user_token"],
    )


# ---------------------------------------------------------------------------
# WebSocket — UI event stream (transcripts, activity) while media is on LiveKit
# ---------------------------------------------------------------------------


@router.websocket("/ws/events/{workflow_id}/{workflow_run_id}")
async def livekit_events_websocket(
    websocket: WebSocket,
    workflow_id: int,
    workflow_run_id: int,
    user: UserModel = Depends(get_user_ws),
):
    """WebSocket that streams transcripts/activity to the browser while
    media flows through LiveKit.

    The pipeline is started here (not in POST /connect) so that the pipeline
    and this WebSocket always share the same uvicorn worker, ensuring the
    in-memory WebSocketBroadcaster can deliver messages.
    """
    import os
    worker_pid = os.getpid()

    # Verify the authenticated user actually owns this run before accepting the
    # socket or consuming the (single-use) pipeline params. Prevents a valid
    # token from being used to hijack another user's LiveKit run.
    owned_run = await db_client.get_workflow_run(workflow_run_id, user.id)
    if not owned_run or owned_run.workflow_id != workflow_id:
        logger.warning(
            f"[LiveKit][WS events] run_id={workflow_run_id} REJECTED — "
            f"not owned by user_id={user.id}"
        )
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await websocket.accept()

    set_current_run_id(workflow_run_id)
    await websocket_broadcaster.register(workflow_run_id, websocket)

    logger.info(
        f"[LiveKit][WS events] run_id={workflow_run_id} | CONNECTED | "
        f"worker_pid={worker_pid} | user_id={user.id} | "
        f"broadcaster has WS: {websocket_broadcaster.get_connection(workflow_run_id) is not None}"
    )

    pipeline_task: asyncio.Task | None = None
    try:
        r = await _get_redis()
        redis_key = _params_key(workflow_run_id)
        raw = await r.getdel(redis_key)
        if raw:
            params = json.loads(raw)
            logger.info(
                f"[LiveKit][WS events] run_id={workflow_run_id} | "
                f"Retrieved pipeline params from Redis key={redis_key} | "
                f"Starting pipeline in worker_pid={worker_pid}"
            )
            pipeline_task = asyncio.create_task(
                run_pipeline_livekit(
                    livekit_url=params["livekit_url"],
                    livekit_token=params["livekit_token"],
                    room_name=params["room_name"],
                    workflow_id=params["workflow_id"],
                    workflow_run_id=params["workflow_run_id"],
                    user_id=params["user_id"],
                    call_context_vars=params.get("call_context_vars", {}),
                )
            )
            logger.info(
                f"[LiveKit][WS events] run_id={workflow_run_id} | "
                f"Pipeline task created in worker_pid={worker_pid} — "
                f"pipeline + WS in SAME worker ✓"
            )
        else:
            logger.warning(
                f"[LiveKit][WS events] run_id={workflow_run_id} | "
                f"NO pipeline params in Redis key={redis_key} — "
                f"params may have expired or already been consumed"
            )
    except Exception as e:
        logger.error(
            f"[LiveKit][WS events] run_id={workflow_run_id} | "
            f"Failed to start pipeline: {e}",
            exc_info=True,
        )

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(
            f"[LiveKit][WS events] run_id={workflow_run_id} | DISCONNECTED | "
            f"worker_pid={worker_pid}"
        )
    except Exception as e:
        logger.error(
            f"[LiveKit][WS events] run_id={workflow_run_id} | ERROR: {e} | "
            f"worker_pid={worker_pid}"
        )
    finally:
        await websocket_broadcaster.unregister(workflow_run_id)
        logger.info(
            f"[LiveKit][WS events] run_id={workflow_run_id} | "
            f"Broadcaster unregistered | worker_pid={worker_pid}"
        )
        if pipeline_task and not pipeline_task.done():
            pipeline_task.cancel()
            logger.info(
                f"[LiveKit][WS events] run_id={workflow_run_id} | "
                f"Pipeline task cancelled | worker_pid={worker_pid}"
            )
