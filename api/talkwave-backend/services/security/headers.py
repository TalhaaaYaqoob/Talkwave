"""
Security Headers Middleware.

This module provides security headers to protect against common web vulnerabilities:
- XSS (Cross-Site Scripting)
- Clickjacking
- MIME type sniffing
- Information disclosure

These headers follow OWASP recommendations for secure HTTP headers.
"""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from api.constants import ENVIRONMENT


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds security headers to all responses.
    
    Headers added:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 1; mode=block
    - Referrer-Policy: strict-origin-when-cross-origin
    - Permissions-Policy: Restrict browser features
    - Cache-Control: For sensitive endpoints
    - Strict-Transport-Security: HTTPS enforcement (production only)
    """
    
    def __init__(self, app: ASGIApp, enable_hsts: bool = True):
        super().__init__(app)
        self.enable_hsts = enable_hsts
    
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Prevent clickjacking - API responses shouldn't be framed
        response.headers["X-Frame-Options"] = "DENY"
        
        # XSS Protection (legacy, but still useful for older browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Restrict browser features (camera, microphone handled by embed widget)
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), "
            "autoplay=(), "
            "camera=(), "
            "cross-origin-isolated=(), "
            "display-capture=(), "
            "encrypted-media=(), "
            "fullscreen=(), "
            "geolocation=(), "
            "gyroscope=(), "
            "keyboard-map=(), "
            "magnetometer=(), "
            "microphone=(), "
            "midi=(), "
            "payment=(), "
            "picture-in-picture=(), "
            "publickey-credentials-get=(), "
            "screen-wake-lock=(), "
            "sync-xhr=(), "
            "usb=(), "
            "xr-spatial-tracking=()"
        )
        
        # Cache control for API responses
        # Prevent caching of sensitive data
        if "Authorization" in request.headers:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        
        # HSTS - enforce HTTPS (only in production)
        if self.enable_hsts and ENVIRONMENT not in ("local", "development", "test"):
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        
        # Prevent information disclosure
        # Remove server header if present
        if "server" in response.headers:
            del response.headers["server"]
        
        return response


class ContentSecurityPolicyMiddleware(BaseHTTPMiddleware):
    """
    Content Security Policy middleware for additional XSS protection.
    
    This is separate from SecurityHeadersMiddleware because CSP
    needs to be carefully configured for each application.
    """
    
    def __init__(self, app: ASGIApp, policy: str = None):
        super().__init__(app)
        self.policy = policy or self._default_policy()
    
    def _default_policy(self) -> str:
        """Default CSP for API-only backends."""
        return (
            "default-src 'none'; "
            "frame-ancestors 'none'; "
            "form-action 'none'; "
            "base-uri 'none'"
        )
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Only add CSP to HTML responses (like error pages)
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers["Content-Security-Policy"] = self.policy
        
        return response

