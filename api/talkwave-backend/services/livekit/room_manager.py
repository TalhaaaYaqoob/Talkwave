"""LiveKit room creation and access token generation.

When LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET are set, browser calls
use LiveKit Cloud as the SFU instead of self-hosted aiortc peer connections.
The Pipecat agent joins the LiveKit room as a participant, and the browser
connects via the LiveKit JS SDK.

Room lifecycle:
  1. Backend creates a room via the LiveKit Server API
  2. Backend generates two tokens: one for the browser, one for the agent
  3. Browser joins the room (audio published from mic)
  4. Agent joins the room (Pipecat LiveKitTransport)
  5. Room is auto-deleted when both participants leave
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Optional

from loguru import logger

from api.constants import LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_ENABLED, LIVEKIT_URL

try:
    from livekit.api import AccessToken, VideoGrants
    LIVEKIT_SDK_AVAILABLE = True
except ImportError:
    LIVEKIT_SDK_AVAILABLE = False
    logger.warning(
        "[LiveKit] livekit-api package not installed. "
        "Install with: pip install livekit-api"
    )


def livekit_enabled() -> bool:
    return LIVEKIT_ENABLED and LIVEKIT_SDK_AVAILABLE


def _room_name(workflow_run_id: int) -> str:
    return f"dograh-run-{workflow_run_id}"


def create_participant_token(
    workflow_run_id: int,
    participant_identity: str,
    participant_name: str = "",
    ttl_seconds: int = 3600,
    is_agent: bool = False,
) -> str:
    """Generate a signed JWT for a participant to join a LiveKit room.

    Args:
        workflow_run_id: Used to derive the room name.
        participant_identity: Unique identity string for the participant.
        participant_name: Display name for the participant.
        ttl_seconds: Token time-to-live.
        is_agent: If True, grants room admin + publish permissions.

    Returns:
        Signed JWT string.
    """
    if not LIVEKIT_SDK_AVAILABLE:
        raise RuntimeError("livekit-api package is not installed")

    room_name = _room_name(workflow_run_id)

    grants = VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
        room_create=is_agent,
        room_admin=is_agent,
    )

    token = (
        AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(participant_identity)
        .with_name(participant_name or participant_identity)
        .with_grants(grants)
        .with_ttl(timedelta(seconds=ttl_seconds))
    )

    jwt_str = token.to_jwt()
    logger.info(
        f"[LiveKit] Token created for {participant_identity} in room {room_name} "
        f"(agent={is_agent}, ttl={ttl_seconds}s)"
    )
    return jwt_str


async def create_room(
    workflow_run_id: int,
    empty_timeout: int = 300,
    max_participants: int = 2,
) -> dict:
    """Create a LiveKit room (or return info if it already exists).

    LiveKit rooms are created implicitly when the first participant with
    room_create permission joins. This helper returns the metadata the
    caller needs to build transport/token objects.

    Args:
        workflow_run_id: Workflow run ID (used as room name seed).
        empty_timeout: Seconds to keep room alive after all participants leave.
        max_participants: Maximum participants allowed in the room.

    Returns:
        Dict with room_name, livekit_url, and agent/user tokens.
    """
    room_name = _room_name(workflow_run_id)

    agent_token = create_participant_token(
        workflow_run_id,
        participant_identity=f"agent-{workflow_run_id}",
        participant_name="AI Agent",
        is_agent=True,
    )

    user_token = create_participant_token(
        workflow_run_id,
        participant_identity=f"user-{workflow_run_id}-{int(time.time())}",
        participant_name="User",
        is_agent=False,
    )

    logger.info(
        f"[LiveKit] Room prepared: {room_name} "
        f"(url={LIVEKIT_URL}, max_participants={max_participants})"
    )

    return {
        "room_name": room_name,
        "livekit_url": LIVEKIT_URL,
        "agent_token": agent_token,
        "user_token": user_token,
    }


async def delete_room(workflow_run_id: int) -> bool:
    """Delete a LiveKit room. Best-effort; failures are logged but not raised."""
    try:
        from livekit.api import LiveKitAPI

        api = LiveKitAPI(
            url=LIVEKIT_URL,
            api_key=LIVEKIT_API_KEY,
            api_secret=LIVEKIT_API_SECRET,
        )
        room_name = _room_name(workflow_run_id)
        await api.room.delete_room(room_name)
        logger.info(f"[LiveKit] Room deleted: {room_name}")
        return True
    except Exception as e:
        logger.warning(f"[LiveKit] Failed to delete room for run {workflow_run_id}: {e}")
        return False
