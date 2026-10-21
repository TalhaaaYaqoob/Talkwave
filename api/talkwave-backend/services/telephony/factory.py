"""
Factory for creating telephony providers.
Handles configuration loading from environment (OSS) or database (SaaS).
The providers themselves don't know or care where config comes from.

Includes a short-lived in-memory cache (60s TTL) for telephony config
to avoid redundant DB roundtrips during a single call flow.
"""

import time
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from api.db import db_client
from api.enums import OrganizationConfigurationKey
from api.services.telephony.base import TelephonyProvider
from api.services.telephony.providers.twilio_provider import TwilioProvider

# Simple in-memory cache: org_id -> (config_dict, timestamp)
# 60-second TTL — long enough to cover a single call setup flow,
# short enough to pick up config changes quickly.
_CONFIG_CACHE: Dict[int, Tuple[Dict[str, Any], float]] = {}
_CACHE_TTL = 60.0  # seconds


def _get_cached_config(organization_id: int) -> Optional[Dict[str, Any]]:
    """Return cached config if still valid, else None."""
    entry = _CONFIG_CACHE.get(organization_id)
    if entry:
        config, ts = entry
        if time.monotonic() - ts < _CACHE_TTL:
            return config
        # Expired — remove
        del _CONFIG_CACHE[organization_id]
    return None


def _set_cached_config(organization_id: int, config: Dict[str, Any]) -> None:
    """Store config in cache with current timestamp."""
    _CONFIG_CACHE[organization_id] = (config, time.monotonic())


async def load_telephony_config(organization_id: int) -> Dict[str, Any]:
    """
    Load telephony configuration from cache or database.

    Args:
        organization_id: Organization ID for database config

    Returns:
        Configuration dictionary with provider type and credentials

    Raises:
        ValueError: If no configuration found for the organization
    """
    if not organization_id:
        raise ValueError("Organization ID is required to load telephony configuration")

    # Check cache first
    cached = _get_cached_config(organization_id)
    if cached:
        logger.debug(f"Using cached telephony config for org {organization_id}")
        return cached

    logger.debug(f"Loading telephony config from database for org {organization_id}")

    config = await db_client.get_configuration(
        organization_id,
        OrganizationConfigurationKey.TELEPHONY_CONFIGURATION.value,
    )

    if config and config.value:
        provider = (config.value.get("provider") or "twilio").lower()
        if provider != "twilio":
            logger.warning(
                f"Unsupported telephony provider '{provider}' configured for org {organization_id}. "
                "This deployment is Twilio-only."
            )
            result = {
                "provider": "twilio",
                "account_sid": None,
                "auth_token": None,
                "from_numbers": [],
            }
            _set_cached_config(organization_id, result)
            return result

        result = {
            "provider": "twilio",
            "account_sid": config.value.get("account_sid"),
            "auth_token": config.value.get("auth_token"),
            "from_numbers": config.value.get("from_numbers", []),
        }

        # Cache the result
        _set_cached_config(organization_id, result)
        return result

    raise ValueError(
        f"No telephony configuration found for organization {organization_id}"
    )


async def get_telephony_provider(organization_id: int) -> TelephonyProvider:
    """
    Factory function to create telephony providers.

    Args:
        organization_id: Organization ID (required)

    Returns:
        Configured telephony provider instance

    Raises:
        ValueError: If provider type is unknown or configuration is invalid
    """
    # Load configuration (from cache or DB)
    config = await load_telephony_config(organization_id)

    provider_type = (config.get("provider") or "twilio").lower()
    if provider_type != "twilio":
        logger.warning(
            f"Unsupported provider '{provider_type}' received from config. "
            "Falling back to Twilio provider with current config."
        )

    logger.info("Creating twilio telephony provider")
    return TwilioProvider(config)
