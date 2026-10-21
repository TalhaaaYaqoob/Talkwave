"""Feature limits for self-hosted TalkWave.

There are no paid plans: every organization gets every feature with no
usage limits.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class PlanFeatures:
    """Features included in a plan."""

    minutes_included: int
    max_workflows: int
    max_campaigns: int
    max_campaign_contacts: int
    gemini_s2s_enabled: bool
    overage_rate_per_minute: Optional[float]
    campaigns_enabled: bool
    knowledge_base_enabled: bool
    custom_tools_enabled: bool
    website_embed_enabled: bool
    priority_support: bool
    display_name: str
    price_monthly: float
    description: str
    features_list: List[str] = field(default_factory=list)


SELF_HOSTED_PLAN_NAME = "self_hosted"

SELF_HOSTED_PLAN = PlanFeatures(
    minutes_included=10**9,
    max_workflows=10**6,
    max_campaigns=10**6,
    max_campaign_contacts=10**9,
    gemini_s2s_enabled=True,
    overage_rate_per_minute=None,
    campaigns_enabled=True,
    knowledge_base_enabled=True,
    custom_tools_enabled=True,
    website_embed_enabled=True,
    priority_support=False,
    display_name="Self-hosted",
    price_monthly=0,
    description="All features unlocked with no usage limits",
    features_list=["All features", "No usage limits"],
)


def get_plan(plan_name: str = SELF_HOSTED_PLAN_NAME) -> PlanFeatures:
    """Return the features for a plan. Self-hosted installs have a single plan."""
    return SELF_HOSTED_PLAN
