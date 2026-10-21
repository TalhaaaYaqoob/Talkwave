"""Utility for getting the cloudflared tunnel URL at runtime."""

import asyncio
import os
import re
from typing import Optional

import aiohttp
from loguru import logger


class TunnelURLProvider:
    """Provider for getting the tunnel URL from cloudflared or environment."""
    _cached_url: Optional[str] = None
    _cached_at: float = 0.0
    _cache_ttl_seconds: float = 600.0
    _lock = asyncio.Lock()

    @classmethod
    def _normalize_endpoint(cls, endpoint: str) -> str:
        endpoint = (endpoint or "").strip()
        endpoint = (
            endpoint.replace("https://", "")
            .replace("http://", "")
            .replace("wss://", "")
            .replace("ws://", "")
            .rstrip("/")
        )
        if "/" in endpoint:
            endpoint = endpoint.split("/", 1)[0]
        return endpoint

    @classmethod
    def _get_endpoint_from_env(cls) -> Optional[str]:
        # Primary explicit setting
        endpoint = os.getenv("BACKEND_API_ENDPOINT")
        if endpoint:
            return cls._normalize_endpoint(endpoint)

        # Common hosting-provided public domains (Railway/Render/etc.)
        for key in (
            "RAILWAY_PUBLIC_DOMAIN",
            "RAILWAY_STATIC_URL",
            "RENDER_EXTERNAL_URL",
            "RENDER_EXTERNAL_HOSTNAME",
        ):
            val = os.getenv(key)
            if val:
                return cls._normalize_endpoint(val)
        return None

    @classmethod
    async def get_tunnel_url(cls) -> str:
        """
        Get the tunnel URL for external access.

        Priority:
        1. BACKEND_API_ENDPOINT environment variable (if set)
        2. Query cloudflared metrics endpoint
        3. Raise error if neither available

        Returns:
            str: The tunnel domain (without protocol)

        Raises:
            ValueError: If no tunnel URL can be determined
        """
        now = asyncio.get_running_loop().time()
        if cls._cached_url and (now - cls._cached_at) < cls._cache_ttl_seconds:
            return cls._cached_url

        async with cls._lock:
            # Re-check cache inside lock to avoid duplicate lookups.
            now = asyncio.get_running_loop().time()
            if cls._cached_url and (now - cls._cached_at) < cls._cache_ttl_seconds:
                return cls._cached_url

            # First priority: environment / platform-provided public domain
            env_endpoint = cls._get_endpoint_from_env()
            if env_endpoint:
                logger.debug(f"Using backend endpoint from environment: {env_endpoint}")
                cls._cached_url = env_endpoint
                cls._cached_at = now
                return env_endpoint

            # Second priority: query cloudflared (best-effort, fast timeout)
            try:
                url = await cls._get_cloudflared_url()
                if url:
                    logger.info(f"Retrieved tunnel URL from cloudflared: {url}")
                    cls._cached_url = url
                    cls._cached_at = now
                    return url
            except Exception as e:
                logger.warning(f"Failed to get tunnel URL from cloudflared: {e}")

        raise ValueError(
            "No tunnel URL available. Please set BACKEND_API_ENDPOINT environment "
            "variable or ensure cloudflared service is running."
        )

    @classmethod
    async def _get_cloudflared_url(cls) -> Optional[str]:
        """
        Query cloudflared metrics endpoint to get the tunnel URL.

        Returns:
            Optional[str]: The tunnel domain (without protocol), or None if not found
        """
        try:
            # Try to connect to cloudflared metrics endpoint
            # The service name in docker-compose is 'cloudflared'
            metrics_url = "http://cloudflared:2000/metrics"

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    metrics_url, timeout=aiohttp.ClientTimeout(total=0.75)
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            f"Cloudflared metrics returned status {response.status}"
                        )
                        return None

                    text = await response.text()

                    # Look for the tunnel URL in metrics
                    # Cloudflared exposes this in the userHostname metric
                    match = re.search(r'userHostname="([^"]+)"', text)
                    if match:
                        hostname = match.group(1)
                        # Remove https:// or wss:// if present
                        hostname = hostname.replace("https://", "").replace(
                            "wss://", ""
                        )
                        return hostname

                    # Alternative: Look for trycloudflare.com domain
                    match = re.search(r"([a-z0-9-]+\.trycloudflare\.com)", text)
                    if match:
                        return match.group(1)

                    logger.warning("Could not find tunnel URL in cloudflared metrics")
                    return None

        except asyncio.TimeoutError:
            logger.warning("Timeout connecting to cloudflared metrics endpoint")
            return None
        except aiohttp.ClientError as e:
            logger.warning(f"Error connecting to cloudflared: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting cloudflared URL: {e}")
            return None
