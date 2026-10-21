"""ICE server configuration for WebRTC.

Resolves STUN/TURN servers from environment variables. TURN is required for any
caller behind a symmetric NAT / strict corporate firewall — without it, even a
"connected" WebSocket signalling channel can't get media through, which shows up
in logs as `Failed to write audio frame` and `Connection(0) ICE failed`.

Three sources are supported, in order of preference when resolving user-facing
credentials (`get_ice_servers_for_client`):

1. **Twilio Network Traversal Service (NTS)** — ephemeral TURN credentials.
   Enable by setting `TWILIO_ICE_ACCOUNT_SID` + `TWILIO_ICE_AUTH_TOKEN`. This is
   the easiest production-ready option; Twilio runs a global relay fleet.

2. **Static TURN** — if you host your own coturn or use a managed TURN provider
   (Metered, Xirsys, Cloudflare). Supports multiple URLs via comma separation:
       TURN_URLS=turn:relay.example.com:3478?transport=udp,turns:relay.example.com:5349?transport=tcp
       TURN_USERNAME=...
       TURN_PASSWORD=...

3. **STUN-only fallback** — used if neither of the above is configured. This
   will fail for users behind symmetric NAT; fine for dev, **not** for prod.

The server-side (aiortc) helper only accepts URL strings, so we return a
simplified list there. The client gets full objects including credentials.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger


# -----------------------------------------------------------------------------
# Config helpers
# -----------------------------------------------------------------------------


def _split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _stun_urls() -> List[str]:
    urls = _split_csv(os.getenv("STUN_URLS"))
    if urls:
        return urls
    return ["stun:stun.l.google.com:19302"]


# TTL for ephemeral TURN credentials handed to browsers (seconds).
_TURN_CRED_TTL_SECONDS = int(os.getenv("TURN_CRED_TTL_SECONDS", "3600"))


def _ephemeral_turn_credentials(secret: str) -> Dict[str, str]:
    """Generate time-limited coturn REST-API credentials.

    Uses the standard coturn ``use-auth-secret`` scheme: the username is an
    expiry timestamp and the credential is ``base64(HMAC-SHA1(secret, username))``.
    This means the credentials handed to an anonymous browser expire quickly and
    cannot be reused to abuse the relay indefinitely, unlike a shared static
    username/password.
    """
    expiry = int(time.time()) + _TURN_CRED_TTL_SECONDS
    username = str(expiry)
    digest = hmac.new(
        secret.encode("utf-8"), username.encode("utf-8"), hashlib.sha1
    ).digest()
    credential = base64.b64encode(digest).decode("ascii")
    return {"username": username, "credential": credential}


def _static_turn_servers() -> List[Dict[str, Any]]:
    urls = _split_csv(os.getenv("TURN_URLS"))
    if not urls:
        return []

    # Preferred: ephemeral, time-limited credentials via a shared auth secret.
    auth_secret = os.getenv("TURN_STATIC_AUTH_SECRET")
    if auth_secret:
        creds = _ephemeral_turn_credentials(auth_secret)
        return [{"urls": urls, **creds}]

    # Fallback: long-lived static credentials. These are handed to any caller
    # (including anonymous share pages), so they can be harvested and used to
    # abuse the relay. Strongly prefer TURN_STATIC_AUTH_SECRET in production.
    username = os.getenv("TURN_USERNAME")
    password = os.getenv("TURN_PASSWORD") or os.getenv("TURN_CREDENTIAL")
    if not username or not password:
        return []
    logger.warning(
        "[ICE] Serving long-lived static TURN credentials. Set "
        "TURN_STATIC_AUTH_SECRET to issue short-lived credentials instead."
    )
    return [
        {
            "urls": urls,
            "username": username,
            "credential": password,
        }
    ]


# -----------------------------------------------------------------------------
# Twilio Network Traversal Service (ephemeral TURN)
# -----------------------------------------------------------------------------


@dataclass
class _TwilioCache:
    servers: List[Dict[str, Any]]
    expires_at: float


_twilio_cache: Optional[_TwilioCache] = None


async def _twilio_ice_servers() -> List[Dict[str, Any]]:
    """Fetch ephemeral ICE credentials from Twilio NTS and cache them."""
    global _twilio_cache

    account_sid = os.getenv("TWILIO_ICE_ACCOUNT_SID") or os.getenv(
        "TWILIO_ACCOUNT_SID_FOR_ICE"
    )
    auth_token = os.getenv("TWILIO_ICE_AUTH_TOKEN") or os.getenv(
        "TWILIO_AUTH_TOKEN_FOR_ICE"
    )
    if not account_sid or not auth_token:
        return []

    now = time.time()
    if _twilio_cache and _twilio_cache.expires_at - 60 > now:
        return _twilio_cache.servers

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Tokens.json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, auth=(account_sid, auth_token), data={})
            resp.raise_for_status()
            payload = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[ICE] Failed to fetch Twilio NTS token: {e}")
        return []

    raw = payload.get("ice_servers") or []
    servers: List[Dict[str, Any]] = []
    for entry in raw:
        urls = entry.get("urls") or entry.get("url")
        if not urls:
            continue
        item: Dict[str, Any] = {"urls": urls}
        if entry.get("username"):
            item["username"] = entry["username"]
        if entry.get("credential"):
            item["credential"] = entry["credential"]
        servers.append(item)

    try:
        ttl = int(payload.get("ttl", "3600"))
    except (TypeError, ValueError):
        ttl = 3600

    _twilio_cache = _TwilioCache(servers=servers, expires_at=now + ttl)
    logger.info(
        f"[ICE] Loaded {len(servers)} Twilio NTS ICE servers (ttl={ttl}s)"
    )
    return servers


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


async def get_ice_servers_for_client() -> List[Dict[str, Any]]:
    """ICE config returned to the browser (includes TURN creds)."""
    servers: List[Dict[str, Any]] = [{"urls": _stun_urls()}]

    twilio = await _twilio_ice_servers()
    if twilio:
        servers.extend(twilio)

    static_turn = _static_turn_servers()
    if static_turn:
        servers.extend(static_turn)

    return servers


def get_ice_servers_for_aiortc() -> List[str]:
    """ICE URLs used by the server-side aiortc peer connection.

    aiortc's ``SmallWebRTCConnection`` accepts a plain list of ``stun:``/``turn:``
    URLs (no credentials) for server-side candidate gathering. We still need
    TURN URLs here so that if the *server* sits behind NAT (e.g. Railway), it
    can gather relay candidates of its own.
    """
    urls: List[str] = list(_stun_urls())
    urls.extend(_split_csv(os.getenv("TURN_URLS")))
    return urls
