"""Lightweight public endpoint that returns ICE servers for the browser.

Returning TURN credentials to authenticated users is standard practice; TURN
servers themselves still authenticate each RTP session with the returned
username/credential pair, so exposing them per-request is safe.
"""

from fastapi import APIRouter, Request

from api.services.security.rate_limiter import RateLimitTiers, limiter
from api.services.webrtc import get_ice_servers_for_client

router = APIRouter(prefix="/webrtc", tags=["webrtc"])


@router.get("/ice-servers")
@limiter.limit(RateLimitTiers.PUBLIC)
async def ice_servers(request: Request):
    """Return ICE server configuration the browser should pass to ``RTCPeerConnection``.

    Rate-limited because it is unauthenticated and may vend TURN credentials;
    limiting requests curbs credential-harvesting / relay-abuse attempts.
    """
    servers = await get_ice_servers_for_client()
    return {"ice_servers": servers}
