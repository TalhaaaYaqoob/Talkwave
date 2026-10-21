"""
API Rate Limiting Configuration.

This module provides rate limiting for API endpoints using slowapi.
The limits are designed to be generous for normal usage while preventing abuse.

Rate Limit Tiers:
- CRITICAL: Very high limits for real-time calling/streaming (1000/min)
- HIGH: High limits for frequently accessed endpoints (300/min)
- STANDARD: Standard limits for regular CRUD operations (100/min)
- LOW: Lower limits for expensive operations like AI generation (20/min)
- PUBLIC: Limits for unauthenticated public endpoints (30/min)
"""

import os
from typing import Callable, Optional

from fastapi import Request
from loguru import logger
from slowapi import Limiter
from slowapi.util import get_remote_address

from api.constants import REDIS_URL


def get_rate_limit_key(request: Request) -> str:
    """
    Get the rate limit key based on user identity or IP.
    
    For authenticated requests, uses the user ID for rate limiting.
    For unauthenticated requests, falls back to IP address.
    This ensures authenticated users get their own rate limit bucket.
    """
    # Try to get user from request state (set by auth middleware)
    if hasattr(request.state, "user") and request.state.user:
        user = request.state.user
        if hasattr(user, "id"):
            return f"user:{user.id}"
        if hasattr(user, "selected_organization_id"):
            return f"org:{user.selected_organization_id}"
    
    # Check for authorization header to create consistent key
    auth_header = request.headers.get("authorization", "")
    if auth_header:
        # Hash the token to create a consistent key without exposing the token
        import hashlib
        token_hash = hashlib.sha256(auth_header.encode()).hexdigest()[:16]
        return f"token:{token_hash}"
    
    # Fallback to IP address for unauthenticated requests
    return get_remote_address(request)


def get_redis_storage_uri() -> Optional[str]:
    """Get Redis URI for distributed rate limiting."""
    if REDIS_URL:
        return REDIS_URL
    return None


# Initialize the rate limiter
# Uses Redis for distributed rate limiting if available, otherwise in-memory
_storage_uri = get_redis_storage_uri()

if _storage_uri:
    logger.info("Initializing rate limiter with Redis backend")
    limiter = Limiter(
        key_func=get_rate_limit_key,
        storage_uri=_storage_uri,
        strategy="moving-window",  # Best strategy for Redis - smooth rate limiting
    )
else:
    logger.warning("Initializing rate limiter with in-memory backend (not suitable for production)")
    limiter = Limiter(
        key_func=get_rate_limit_key,
        strategy="fixed-window",  # Simple strategy for in-memory
    )


class RateLimitTiers:
    """
    Rate limit tiers for different endpoint types.
    
    These limits are designed to allow heavy normal usage while preventing abuse.
    For a voice AI platform, we need generous limits for real-time operations.
    """
    
    # Critical tier: Real-time voice/calling operations
    # Very high limits to not interrupt ongoing calls or streaming
    CRITICAL = "1000/minute"
    CRITICAL_PER_SECOND = "50/second"
    
    # High tier: Frequently accessed read operations
    # Listing workflows, fetching data, health checks
    HIGH = "300/minute"
    HIGH_BURST = "30/second"
    
    # Standard tier: Regular CRUD operations
    # Creating/updating workflows, runs, configurations
    STANDARD = "100/minute"
    STANDARD_BURST = "10/second"
    
    # Low tier: Expensive or sensitive operations
    # AI-powered template generation, file uploads
    LOW = "20/minute"
    LOW_BURST = "3/second"
    
    # Public tier: Unauthenticated endpoints
    # Embed initialization, public config fetching
    PUBLIC = "30/minute"
    PUBLIC_BURST = "5/second"
    
    # Auth tier: Authentication-related endpoints
    # Login attempts, token refresh
    AUTH = "10/minute"
    AUTH_BURST = "2/second"
    
    # WebSocket tier: For connection establishment
    # After connection, rate limiting is per-message
    WEBSOCKET = "60/minute"


class RateLimitManager:
    """
    Manager class for applying rate limits to routes.
    
    Usage:
        from api.services.security import RateLimitManager
        
        @router.get("/workflows")
        @RateLimitManager.high()
        async def get_workflows():
            ...
    """
    
    @staticmethod
    def critical():
        """Apply critical tier rate limiting (1000/min)."""
        return limiter.limit(RateLimitTiers.CRITICAL)
    
    @staticmethod
    def high():
        """Apply high tier rate limiting (300/min)."""
        return limiter.limit(RateLimitTiers.HIGH)
    
    @staticmethod
    def standard():
        """Apply standard tier rate limiting (100/min)."""
        return limiter.limit(RateLimitTiers.STANDARD)
    
    @staticmethod
    def low():
        """Apply low tier rate limiting (20/min)."""
        return limiter.limit(RateLimitTiers.LOW)
    
    @staticmethod
    def public():
        """Apply public tier rate limiting (30/min)."""
        return limiter.limit(RateLimitTiers.PUBLIC)
    
    @staticmethod
    def auth():
        """Apply auth tier rate limiting (10/min)."""
        return limiter.limit(RateLimitTiers.AUTH)
    
    @staticmethod
    def websocket():
        """Apply WebSocket connection rate limiting (60/min)."""
        return limiter.limit(RateLimitTiers.WEBSOCKET)
    
    @staticmethod
    def custom(limit: str):
        """Apply a custom rate limit string (e.g., '500/minute')."""
        return limiter.limit(limit)


# Exempt paths from rate limiting (health checks, metrics)
RATE_LIMIT_EXEMPT_PATHS = [
    "/api/v1/health",
    "/api/v1/metrics",
    "/openapi.json",
    "/docs",
    "/redoc",
]


def is_rate_limit_exempt(request: Request) -> bool:
    """Check if a request path is exempt from rate limiting."""
    path = request.url.path
    return any(path.startswith(exempt) or path == exempt for exempt in RATE_LIMIT_EXEMPT_PATHS)

