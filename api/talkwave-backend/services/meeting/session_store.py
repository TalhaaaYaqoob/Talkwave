"""Redis-backed session store for meeting agent sessions.

Replaces the in-memory _active_sessions dict with a Redis-backed store
that survives worker restarts and works across multiple Uvicorn workers.

Session metadata (JSON-serializable) lives in Redis. The per-worker
in-memory component holds only non-serializable objects (pipelines,
WebSocket connections) keyed by session_id.

Architecture:
  Redis:  session metadata, bot_id→session_id reverse index, user indexes
  Memory: pipeline instances, WebSocket connections (per-worker only)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from api.constants import REDIS_URL

SESSION_TTL = 86400  # 24h — auto-expire stale sessions
SESSION_PREFIX = "meeting:session:"
BOT_INDEX_PREFIX = "meeting:bot:"
USER_INDEX_PREFIX = "meeting:user:"
TRANSCRIPT_QUEUE_PREFIX = "meeting:tq:"
TRANSCRIPT_QUEUE_TTL = 3600
PIPELINE_OWNER_PREFIX = "meeting:owner:"

_redis: Optional[aioredis.Redis] = None


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            max_connections=20,
        )
    try:
        await _redis.ping()
    except Exception:
        _redis = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            max_connections=20,
        )
    return _redis


class MeetingSessionStore:
    """Distributed session store with per-worker local state for non-serializable objects."""

    def __init__(self):
        self._local_pipelines: dict[str, object] = {}
        self._local_websockets: dict[str, list] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    async def create_session(
        self,
        session_id: str,
        bot_id: str,
        user_id: int,
        meeting_url: str,
        agent_name: str,
        wake_words: list[str],
        knowledge_base_id: Optional[int] = None,
        workflow_id: Optional[int] = None,
        organization_id: Optional[int] = None,
    ) -> dict:
        """Store a new session in Redis with all metadata."""
        r = await _get_redis()

        session_data = {
            "session_id": session_id,
            "bot_id": bot_id,
            "user_id": user_id,
            "organization_id": organization_id,
            "meeting_url": meeting_url,
            "agent_name": agent_name,
            "status": "joining",
            "created_at": time.time(),
            "wake_words": wake_words,
            "knowledge_base_id": knowledge_base_id,
            "workflow_id": workflow_id,
            "worker_pid": os.getpid(),
        }

        pipe = r.pipeline()
        pipe.set(f"{SESSION_PREFIX}{session_id}", json.dumps(session_data), ex=SESSION_TTL)
        pipe.set(f"{BOT_INDEX_PREFIX}{bot_id}", session_id, ex=SESSION_TTL)
        pipe.sadd(f"{USER_INDEX_PREFIX}{user_id}", session_id)
        pipe.expire(f"{USER_INDEX_PREFIX}{user_id}", SESSION_TTL)
        await pipe.execute()

        self._local_websockets[session_id] = []

        logger.info(
            f"[SessionStore] Created session {session_id} | bot={bot_id} | "
            f"user={user_id} | pid={os.getpid()}"
        )
        return session_data

    async def get_session(self, session_id: str) -> Optional[dict]:
        """Retrieve session metadata from Redis."""
        r = await _get_redis()
        raw = await r.get(f"{SESSION_PREFIX}{session_id}")
        if raw:
            return json.loads(raw)
        return None

    async def get_session_by_bot_id(self, bot_id: str) -> Optional[dict]:
        """Reverse-lookup: find session by Recall bot_id (O(1) instead of O(n))."""
        r = await _get_redis()
        session_id = await r.get(f"{BOT_INDEX_PREFIX}{bot_id}")
        if session_id:
            return await self.get_session(session_id)
        return None

    async def list_user_sessions(self, user_id: int) -> list[dict]:
        """List all sessions for a user."""
        r = await _get_redis()
        session_ids = await r.smembers(f"{USER_INDEX_PREFIX}{user_id}")
        sessions = []
        for sid in session_ids:
            data = await self.get_session(sid)
            if data:
                sessions.append(data)
            else:
                await r.srem(f"{USER_INDEX_PREFIX}{user_id}", sid)
        return sorted(sessions, key=lambda s: s.get("created_at", 0), reverse=True)

    async def update_status(self, session_id: str, status: str):
        """Update session status in Redis."""
        r = await _get_redis()
        raw = await r.get(f"{SESSION_PREFIX}{session_id}")
        if raw:
            data = json.loads(raw)
            data["status"] = status
            await r.set(f"{SESSION_PREFIX}{session_id}", json.dumps(data), ex=SESSION_TTL)

    async def delete_session(self, session_id: str):
        """Remove session from Redis and local state."""
        r = await _get_redis()
        raw = await r.get(f"{SESSION_PREFIX}{session_id}")
        if raw:
            data = json.loads(raw)
            bot_id = data.get("bot_id")
            user_id = data.get("user_id")

            pipe = r.pipeline()
            pipe.delete(f"{SESSION_PREFIX}{session_id}")
            pipe.delete(f"{SESSION_PREFIX}{session_id}:summary")
            if bot_id:
                pipe.delete(f"{BOT_INDEX_PREFIX}{bot_id}")
            if user_id:
                pipe.srem(f"{USER_INDEX_PREFIX}{user_id}", session_id)
            await pipe.execute()

        self._local_pipelines.pop(session_id, None)
        self._local_websockets.pop(session_id, None)

    def set_pipeline(self, session_id: str, pipeline):
        """Store a pipeline instance in per-worker memory."""
        self._local_pipelines[session_id] = pipeline

    def get_pipeline(self, session_id: str):
        """Retrieve the pipeline from this worker's memory."""
        return self._local_pipelines.get(session_id)

    def get_websockets(self, session_id: str) -> list:
        """Get WebSocket connections for a session in this worker."""
        return self._local_websockets.get(session_id, [])

    def add_websocket(self, session_id: str, ws):
        if session_id not in self._local_websockets:
            self._local_websockets[session_id] = []
        self._local_websockets[session_id].append(ws)

    def remove_websocket(self, session_id: str, ws):
        wss = self._local_websockets.get(session_id, [])
        if ws in wss:
            wss.remove(ws)

    async def broadcast_to_session(self, session_id: str, event: dict):
        """Send an event to all WebSocket connections for a session in this worker."""
        dead = []
        for ws in self.get_websockets(session_id):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove_websocket(session_id, ws)

    async def try_claim_pipeline_ownership(
        self, session_id: str, ttl: int = SESSION_TTL
    ) -> bool:
        """Atomically claim pipeline ownership for this worker process.

        Uses Redis SETNX so only one worker can own a session's pipeline at
        a time, preventing duplicate agents from speaking simultaneously.
        """
        r = await _get_redis()
        pid = str(os.getpid())
        claimed = await r.set(
            f"{PIPELINE_OWNER_PREFIX}{session_id}", pid, nx=True, ex=ttl
        )
        if claimed:
            logger.debug(
                f"[SessionStore] Pipeline ownership claimed for {session_id} "
                f"by pid={pid}"
            )
        return bool(claimed)

    async def is_pipeline_owner(self, session_id: str) -> bool:
        """Check if this worker process owns the pipeline for the session."""
        r = await _get_redis()
        owner_pid = await r.get(f"{PIPELINE_OWNER_PREFIX}{session_id}")
        return owner_pid == str(os.getpid())

    async def has_pipeline_owner(self, session_id: str) -> bool:
        """Check if any worker currently owns the pipeline for this session."""
        r = await _get_redis()
        return await r.exists(f"{PIPELINE_OWNER_PREFIX}{session_id}") > 0

    async def release_pipeline_ownership(self, session_id: str):
        """Release ownership, but only if this worker is the current owner."""
        r = await _get_redis()
        owner_pid = await r.get(f"{PIPELINE_OWNER_PREFIX}{session_id}")
        if owner_pid == str(os.getpid()):
            await r.delete(f"{PIPELINE_OWNER_PREFIX}{session_id}")
            logger.debug(
                f"[SessionStore] Pipeline ownership released for {session_id}"
            )

    async def push_transcript(self, bot_id: str, data: dict):
        """Push a transcript webhook payload to a Redis queue for cross-worker delivery."""
        r = await _get_redis()
        key = f"{TRANSCRIPT_QUEUE_PREFIX}{bot_id}"
        await r.rpush(key, json.dumps(data))
        await r.expire(key, TRANSCRIPT_QUEUE_TTL)

    async def drain_transcript_queue(self, bot_id: str) -> list[dict]:
        """Pop all queued transcript payloads for a bot (called by the owning worker)."""
        r = await _get_redis()
        key = f"{TRANSCRIPT_QUEUE_PREFIX}{bot_id}"
        items: list[dict] = []
        while True:
            raw = await r.lpop(key)
            if raw is None:
                break
            try:
                items.append(json.loads(raw))
            except Exception:
                pass
        return items

    async def save_summary(self, session_id: str, summary: dict):
        """Persist the post-meeting summary + transcript in Redis."""
        r = await _get_redis()
        await r.set(
            f"{SESSION_PREFIX}{session_id}:summary",
            json.dumps(summary),
            ex=SESSION_TTL * 7,
        )

    async def get_summary(self, session_id: str) -> Optional[dict]:
        """Retrieve the stored summary for a session."""
        r = await _get_redis()
        raw = await r.get(f"{SESSION_PREFIX}{session_id}:summary")
        if raw:
            return json.loads(raw)
        return None

    async def cleanup_ended_sessions(self, max_age_hours: float = 24):
        """Remove ended sessions older than max_age_hours from local state."""
        cutoff = time.time() - (max_age_hours * 3600)
        to_remove = []
        for sid, pipeline in self._local_pipelines.items():
            if hasattr(pipeline, "is_running") and not pipeline.is_running:
                if hasattr(pipeline, "context_manager"):
                    start = getattr(pipeline.context_manager, "_meeting_start_time", 0)
                    if start < cutoff:
                        to_remove.append(sid)

        for sid in to_remove:
            self._local_pipelines.pop(sid, None)
            self._local_websockets.pop(sid, None)
            logger.info(f"[SessionStore] Cleaned up stale session: {sid}")

        return len(to_remove)


session_store = MeetingSessionStore()
