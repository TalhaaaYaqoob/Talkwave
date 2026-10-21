"""Usage limits and feature access.

Self-hosted TalkWave grants every organization all features with no limits.
"""

from api.services.subscription.subscription_service import SubscriptionService

shared_subscription_service = SubscriptionService()
