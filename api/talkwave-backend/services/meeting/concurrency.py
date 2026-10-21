"""Concurrency controls for meeting agent sessions.

Prevents unbounded parallel LLM/TTS work when many wake words fire
simultaneously, and enforces per-user and global session limits.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from api.constants import (
    MEETING_MAX_CONCURRENT_RESPONSES,
    MEETING_MAX_SESSIONS_GLOBAL,
    MEETING_MAX_SESSIONS_PER_USER,
    REDIS_URL,
)

_response_semaphore = asyncio.Semaphore(MEETING_MAX_CONCURRENT_RESPONSES)

GLOBAL_SESSION_KEY = "meeting:global_session_count"
USER_SESSION_KEY = "meeting:user_sessions:{user_id}"


async def acquire_response_slot() -> bool:
    """Acquire a slot before running LLM+TTS for a wake-word response.

    Returns True if a slot is available, False if all slots are occupied.
    Non-blocking so the caller can decide to queue or drop.
    """
    acquired = _response_semaphore._value > 0
    if acquired:
        await _response_semaphore.acquire()
    return acquired


def release_response_slot():
    _response_semaphore.release()


async def check_session_limits(user_id: int) -> Optional[str]:
    """Check whether creating a new session would exceed limits.

    Returns None if OK, otherwise an error message string.
    """
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            global_count = await r.scard("meeting:all_active_sessions")
            if global_count >= MEETING_MAX_SESSIONS_GLOBAL:
                return (
                    f"Global session limit reached ({MEETING_MAX_SESSIONS_GLOBAL}). "
                    "Try again later."
                )

            user_count = await r.scard(f"meeting:user:{user_id}:active")
            if user_count >= MEETING_MAX_SESSIONS_PER_USER:
                return (
                    f"You already have {MEETING_MAX_SESSIONS_PER_USER} active sessions. "
                    "Stop one before creating another."
                )
        finally:
            await r.aclose()
    except Exception as e:
        logger.warning(f"[Concurrency] Redis check failed, allowing session: {e}")
    return None


async def register_active_session(session_id: str, user_id: int):
    """Track an active session in Redis sets for limit enforcement."""
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            pipe = r.pipeline()
            pipe.sadd("meeting:all_active_sessions", session_id)
            pipe.sadd(f"meeting:user:{user_id}:active", session_id)
            await pipe.execute()
        finally:
            await r.aclose()
    except Exception as e:
        logger.warning(f"[Concurrency] Failed to register session: {e}")


async def unregister_active_session(session_id: str, user_id: int):
    """Remove a session from active tracking."""
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            pipe = r.pipeline()
            pipe.srem("meeting:all_active_sessions", session_id)
            pipe.srem(f"meeting:user:{user_id}:active", session_id)
            await pipe.execute()
        finally:
            await r.aclose()
    except Exception as e:
        logger.warning(f"[Concurrency] Failed to unregister session: {e}")
