"""Shared HTTP connection pools for meeting agent services.

Instead of creating a new httpx.AsyncClient per LLM/TTS call, we maintain
long-lived pools per provider (OpenAI, Deepgram, Recall). This dramatically
reduces TCP handshake and TLS negotiation overhead under high concurrency.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import httpx
from loguru import logger


_MAX_CONNECTIONS = 50
_MAX_KEEPALIVE = 20
_DEFAULT_TIMEOUT = 30.0


class _PoolManager:
    """Lazy-initialized, per-process singleton pool manager."""

    def __init__(self):
        self._openai: Optional[httpx.AsyncClient] = None
        self._deepgram: Optional[httpx.AsyncClient] = None
        self._recall: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def openai(self) -> httpx.AsyncClient:
        if self._openai is None or self._openai.is_closed:
            async with self._lock:
                if self._openai is None or self._openai.is_closed:
                    self._openai = httpx.AsyncClient(
                        base_url="https://api.openai.com",
                        headers={
                            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}",
                            "Content-Type": "application/json",
                        },
                        limits=httpx.Limits(
                            max_connections=_MAX_CONNECTIONS,
                            max_keepalive_connections=_MAX_KEEPALIVE,
                        ),
                        timeout=httpx.Timeout(_DEFAULT_TIMEOUT),
                        http2=True,
                    )
                    logger.debug("[PoolManager] OpenAI connection pool created")
        return self._openai

    async def deepgram(self) -> httpx.AsyncClient:
        if self._deepgram is None or self._deepgram.is_closed:
            async with self._lock:
                if self._deepgram is None or self._deepgram.is_closed:
                    self._deepgram = httpx.AsyncClient(
                        base_url="https://api.deepgram.com",
                        headers={
                            "Authorization": f"Token {os.getenv('DEEPGRAM_API_KEY', '')}",
                            "Content-Type": "application/json",
                        },
                        limits=httpx.Limits(
                            max_connections=_MAX_CONNECTIONS,
                            max_keepalive_connections=_MAX_KEEPALIVE,
                        ),
                        timeout=httpx.Timeout(15.0),
                    )
                    logger.debug("[PoolManager] Deepgram connection pool created")
        return self._deepgram

    async def recall(self, api_key: str) -> httpx.AsyncClient:
        if self._recall is None or self._recall.is_closed:
            async with self._lock:
                if self._recall is None or self._recall.is_closed:
                    from api.services.recall.client import RECALL_API_BASE
                    self._recall = httpx.AsyncClient(
                        base_url=RECALL_API_BASE,
                        headers={
                            "Authorization": f"Token {api_key}",
                            "Content-Type": "application/json",
                        },
                        limits=httpx.Limits(
                            max_connections=_MAX_CONNECTIONS,
                            max_keepalive_connections=_MAX_KEEPALIVE,
                        ),
                        timeout=httpx.Timeout(_DEFAULT_TIMEOUT),
                    )
                    logger.debug("[PoolManager] Recall connection pool created")
        return self._recall

    async def close_all(self):
        for name, client in [
            ("OpenAI", self._openai),
            ("Deepgram", self._deepgram),
            ("Recall", self._recall),
        ]:
            if client and not client.is_closed:
                await client.aclose()
                logger.debug(f"[PoolManager] {name} connection pool closed")
        self._openai = None
        self._deepgram = None
        self._recall = None


pool_manager = _PoolManager()
