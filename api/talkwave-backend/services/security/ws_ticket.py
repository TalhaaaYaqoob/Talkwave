"""Short-lived, HMAC-signed tickets that authorize real-time media connections.

Media WebSockets (telephony audio streams, WebRTC/LiveKit signalling started by
providers) cannot carry a normal user JWT because the connecting party is a
third-party provider (e.g. Twilio) rather than the browser. To prevent an
attacker who guesses/enumerates ``workflow_run_id`` values from hijacking a live
call, every media WebSocket URL embeds a signed ``ticket`` that is:

* bound to the specific (workflow_id, user_id, workflow_run_id) tuple,
* time-limited (short TTL), and
* verified with a constant-time HMAC comparison before the socket is accepted.

The ticket is only ever generated server-side and handed to the provider inside
a signature-verified webhook response, so it cannot be obtained by an
unauthenticated caller.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from loguru import logger

from api.constants import DATABASE_URL, WS_TICKET_SECRET

# Default lifetime for a media-connection ticket. Providers connect almost
# immediately after receiving the webhook response, so this can be short.
DEFAULT_TICKET_TTL_SECONDS = 300


def _signing_key() -> bytes:
    """Return the HMAC signing key.

    Prefers the explicit ``WS_TICKET_SECRET``. Falls back to a key derived from
    ``DATABASE_URL`` (a secret already shared across worker processes) so the
    feature is not silently disabled when the dedicated secret is unset.
    """
    if WS_TICKET_SECRET:
        return WS_TICKET_SECRET.encode("utf-8")

    if DATABASE_URL:
        logger.warning(
            "WS_TICKET_SECRET is not set; deriving media-ticket key from "
            "DATABASE_URL. Set WS_TICKET_SECRET explicitly in production."
        )
        return hashlib.sha256(("ws-ticket:" + DATABASE_URL).encode("utf-8")).digest()

    # No secret material available at all. Fail closed at verification time.
    logger.error(
        "No WS_TICKET_SECRET or DATABASE_URL available to sign media tickets."
    )
    return b""


def _payload(workflow_id: int, user_id: int, workflow_run_id: int, expiry: int) -> str:
    return f"{workflow_id}:{user_id}:{workflow_run_id}:{expiry}"


def _sign(payload: str, key: bytes) -> str:
    digest = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def generate_ws_ticket(
    workflow_id: int,
    user_id: int,
    workflow_run_id: int,
    ttl_seconds: int = DEFAULT_TICKET_TTL_SECONDS,
) -> str:
    """Generate a signed ticket authorizing a single media connection."""
    key = _signing_key()
    expiry = int(time.time()) + ttl_seconds
    payload = _payload(workflow_id, user_id, workflow_run_id, expiry)
    signature = _sign(payload, key)
    return f"{expiry}.{signature}"


def verify_ws_ticket(
    ticket: str | None,
    workflow_id: int,
    user_id: int,
    workflow_run_id: int,
) -> bool:
    """Verify a media-connection ticket in constant time.

    Returns ``True`` only if the ticket is well-formed, not expired, and its
    signature matches the exact (workflow_id, user_id, workflow_run_id) tuple.
    """
    if not ticket:
        return False

    key = _signing_key()
    if not key:
        return False

    try:
        expiry_str, provided_sig = ticket.split(".", 1)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return False

    if expiry < int(time.time()):
        return False

    expected_sig = _sign(
        _payload(workflow_id, user_id, workflow_run_id, expiry), key
    )
    return hmac.compare_digest(expected_sig, provided_sig)
