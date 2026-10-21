"""Usage limits for self-hosted TalkWave.

Every check allows the action. Call sites go through this service so that a
deployment can plug in its own quota or billing logic in one place.
"""

from dataclasses import dataclass

from api.services.subscription.plans import SELF_HOSTED_PLAN, SELF_HOSTED_PLAN_NAME

_ALLOWED = {"allowed": True, "reason": "ok", "plan": SELF_HOSTED_PLAN_NAME}


@dataclass(frozen=True)
class Subscription:
    organization_id: int
    plan: str = SELF_HOSTED_PLAN_NAME
    status: str = "active"
    gemini_s2s_enabled: bool = SELF_HOSTED_PLAN.gemini_s2s_enabled
    max_workflows: int = SELF_HOSTED_PLAN.max_workflows
    max_campaign_contacts: int = SELF_HOSTED_PLAN.max_campaign_contacts
    minutes_included: int = SELF_HOSTED_PLAN.minutes_included
    minutes_used: float = 0
    trial_expired: bool = False


class SubscriptionService:
    """Grants every organization all features with no usage limits."""

    async def get_or_create_subscription(self, organization_id: int) -> Subscription:
        return Subscription(organization_id=organization_id)

    async def get_subscription(self, organization_id: int) -> Subscription:
        return Subscription(organization_id=organization_id)

    async def check_can_make_call(self, organization_id: int) -> dict:
        return dict(_ALLOWED)

    async def check_can_create_campaign(self, organization_id: int) -> dict:
        return {
            **_ALLOWED,
            "max_campaigns": SELF_HOSTED_PLAN.max_campaigns,
            "max_contacts": SELF_HOSTED_PLAN.max_campaign_contacts,
        }

    async def check_can_create_workflow(self, organization_id: int) -> dict:
        return {**_ALLOWED, "max_workflows": SELF_HOSTED_PLAN.max_workflows}

    async def record_usage(self, organization_id: int, duration_seconds: float) -> None:
        return None

    async def get_subscription_info(self, organization_id: int) -> dict:
        plan = SELF_HOSTED_PLAN
        return {
            "plan": SELF_HOSTED_PLAN_NAME,
            "plan_display_name": plan.display_name,
            "status": "active",
            "billing_enabled": False,
            "minutes_included": plan.minutes_included,
            "minutes_used": 0,
            "minutes_remaining": plan.minutes_included,
            "max_workflows": plan.max_workflows,
            "max_campaigns": plan.max_campaigns,
            "max_campaign_contacts": plan.max_campaign_contacts,
            "gemini_s2s_enabled": plan.gemini_s2s_enabled,
            "campaigns_enabled": plan.campaigns_enabled,
            "custom_tools_enabled": plan.custom_tools_enabled,
            "overage_rate_per_minute": None,
            "trial_expired": False,
            "price_monthly": 0,
            "current_period_start": None,
            "current_period_end": None,
            "has_payment_method": False,
        }
