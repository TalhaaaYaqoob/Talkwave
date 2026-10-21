"""
PostHog analytics service for server-side event tracking.

Tracks key business events: subscriptions, calls, workflows, campaigns.
All methods are fire-and-forget — analytics failures never block the main flow.
"""

import os
from typing import Any, Dict, Optional

from loguru import logger

POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY", "")
POSTHOG_HOST = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not POSTHOG_API_KEY:
        return None
    try:
        import posthog
        posthog.project_api_key = POSTHOG_API_KEY
        posthog.host = POSTHOG_HOST
        posthog.debug = False
        posthog.disabled = False
        _client = posthog
        logger.info(f"PostHog initialized (host={POSTHOG_HOST})")
        return _client
    except ImportError:
        logger.warning("posthog package not installed — analytics disabled")
        return None


def identify(
    distinct_id: str,
    properties: Optional[Dict[str, Any]] = None,
) -> None:
    """Identify a user with optional properties."""
    client = _get_client()
    if not client:
        return
    try:
        client.identify(distinct_id, properties or {})
    except Exception as e:
        logger.debug(f"PostHog identify error: {e}")


def capture(
    distinct_id: str,
    event: str,
    properties: Optional[Dict[str, Any]] = None,
) -> None:
    """Capture an event for a user."""
    client = _get_client()
    if not client:
        return
    try:
        client.capture(distinct_id, event, properties or {})
    except Exception as e:
        logger.debug(f"PostHog capture error: {e}")


def group_identify(
    group_type: str,
    group_key: str,
    properties: Optional[Dict[str, Any]] = None,
) -> None:
    """Identify a group (e.g., organization) with properties."""
    client = _get_client()
    if not client:
        return
    try:
        client.group_identify(group_type, group_key, properties or {})
    except Exception as e:
        logger.debug(f"PostHog group_identify error: {e}")


def flush() -> None:
    """Flush pending events (call on shutdown)."""
    client = _get_client()
    if not client:
        return
    try:
        client.flush()
    except Exception:
        pass


# ============================================================================
# Pre-built event helpers
# ============================================================================

def track_subscription_changed(
    user_id: str,
    org_id: int,
    old_plan: str,
    new_plan: str,
    source: str = "checkout",
) -> None:
    capture(user_id, "subscription_changed", {
        "organization_id": org_id,
        "old_plan": old_plan,
        "new_plan": new_plan,
        "source": source,
    })


def track_call_started(
    user_id: str,
    org_id: int,
    workflow_id: int,
    run_id: int,
    call_type: str,
) -> None:
    """call_type: 'browser', 'inbound', 'outbound', 'campaign'"""
    capture(user_id, "call_started", {
        "organization_id": org_id,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "call_type": call_type,
    })


def track_call_ended(
    user_id: str,
    org_id: int,
    workflow_id: int,
    run_id: int,
    duration_seconds: float,
    call_type: str,
) -> None:
    capture(user_id, "call_ended", {
        "organization_id": org_id,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "duration_seconds": round(duration_seconds, 2),
        "duration_minutes": round(duration_seconds / 60, 2),
        "call_type": call_type,
    })


def track_workflow_created(
    user_id: str,
    org_id: int,
    workflow_id: int,
    source: str = "manual",
) -> None:
    """source: 'manual', 'template', 'ai_generate'"""
    capture(user_id, "workflow_created", {
        "organization_id": org_id,
        "workflow_id": workflow_id,
        "source": source,
    })


def track_campaign_started(
    user_id: str,
    org_id: int,
    campaign_id: int,
    contact_count: int,
) -> None:
    capture(user_id, "campaign_started", {
        "organization_id": org_id,
        "campaign_id": campaign_id,
        "contact_count": contact_count,
    })


def track_refund(
    user_id: str,
    org_id: int,
    plan: str,
    amount: float,
) -> None:
    capture(user_id, "subscription_refunded", {
        "organization_id": org_id,
        "plan": plan,
        "amount_refunded": amount,
    })
