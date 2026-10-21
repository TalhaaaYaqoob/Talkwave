import time
from typing import Annotated, Optional

import httpx
from fastapi import Header, HTTPException, Query, WebSocket
from loguru import logger
from pydantic import ValidationError

from api.constants import (
    AUTH_PROVIDER,
    DOGRAH_MPS_SECRET_KEY,
    MPS_API_URL,
    SUPERUSER_EMAILS,
    SUPERUSER_PROVIDER_IDS,
)
from api.db import db_client
from api.db.models import UserModel
from api.schemas.user_configuration import UserConfiguration
from api.services.auth.clerk_auth import clerkauth
from api.services.auth.stack_auth import stackauth
from api.services.configuration.registry import (
    DograhLLMModel,
    DograhSTTModel,
    DograhTTSModel,
    DograhVoice,
    ServiceProviders,
)

# ---------------------------------------------------------------------------
# In-memory auth cache — avoids 3-4 sequential DB queries (~1.2s each) on
# every request for the same user session.  TTL = 60s, keyed by JWT sub claim.
# ---------------------------------------------------------------------------
_AUTH_CACHE: dict[str, tuple[UserModel, float]] = {}
_AUTH_CACHE_TTL = 60  # seconds


def _auth_cache_get(key: str) -> Optional[UserModel]:
    entry = _AUTH_CACHE.get(key)
    if entry is None:
        return None
    user, ts = entry
    if time.monotonic() - ts > _AUTH_CACHE_TTL:
        _AUTH_CACHE.pop(key, None)
        return None
    return user


def _auth_cache_set(key: str, user: UserModel) -> None:
    _AUTH_CACHE[key] = (user, time.monotonic())
    # Evict stale entries when cache grows (simple housekeeping)
    if len(_AUTH_CACHE) > 200:
        now = time.monotonic()
        stale = [k for k, (_, ts) in _AUTH_CACHE.items() if now - ts > _AUTH_CACHE_TTL]
        for k in stale:
            _AUTH_CACHE.pop(k, None)


async def _maybe_promote_superuser(
    user_model: UserModel,
    provider_id: str | None,
    email: str | None,
) -> None:
    """Auto-grant superuser based on SUPERUSER_EMAILS / SUPERUSER_PROVIDER_IDS.

    Lets an operator bootstrap admin access via environment variables without
    direct DB access. Only ever promotes (never demotes) so manual grants in the
    DB are preserved.
    """
    if user_model.is_superuser:
        return

    provider_match = bool(provider_id) and provider_id.lower() in SUPERUSER_PROVIDER_IDS
    email_match = bool(email) and email.lower() in SUPERUSER_EMAILS

    if not (provider_match or email_match):
        return

    try:
        await db_client.set_user_superuser(user_model.id, True)
        user_model.is_superuser = True
        logger.info(
            f"Promoted user id={user_model.id} to superuser via env allowlist "
            f"(provider_match={provider_match}, email_match={email_match})"
        )
    except Exception as exc:
        logger.error(f"Failed to auto-promote superuser for user {user_model.id}: {exc}")


async def get_user(
    authorization: Annotated[str | None, Header()] = None,
) -> UserModel:
    # ------------------------------------------------------------------
    # Route to the appropriate auth provider. Every path below performs
    # cryptographic/server-side verification of the caller's identity.
    # There is no unauthenticated / "OSS" bypass.
    # ------------------------------------------------------------------
    if AUTH_PROVIDER == "clerk":
        return await _handle_clerk_auth(authorization)

    if AUTH_PROVIDER != "stack":
        # Fail closed: refuse to authenticate under an unknown/misconfigured
        # provider rather than silently trusting the request.
        logger.error(
            f"Unsupported AUTH_PROVIDER '{AUTH_PROVIDER}'. "
            "Set AUTH_PROVIDER to 'clerk' or 'stack'."
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    # ------------------------------------------------------------------
    # Stack Auth
    # 1. Validate and fetch the authenticated Stack user
    # ------------------------------------------------------------------

    stack_user = await stackauth.get_user(authorization)
    if stack_user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Fast path: return cached user (avoids 3+ DB queries)
    stack_uid = stack_user.get("id", "")
    cached = _auth_cache_get(f"stack:{stack_uid}")
    if cached is not None:
        return cached

    # ------------------------------------------------------------------
    # 2. Ensure the user has a team (Stack "selected_team_id")
    # ------------------------------------------------------------------

    selected_team_id: str | None = stack_user.get("selected_team_id")
    if not selected_team_id and stack_user.get("selected_team"):
        selected_team_id = stack_user["selected_team"].get("id")

    if not selected_team_id:
        raise HTTPException(status_code=400, detail="No team selected")

    # ------------------------------------------------------------------
    # 3. Persist/Fetch the local User model
    # ------------------------------------------------------------------

    try:
        user_model = await db_client.get_or_create_user_by_provider_id(stack_user["id"])
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error while creating user from database {e}"
        )

    # ------------------------------------------------------------------
    # 4. Persist Organization (team) and mapping in local database
    # ------------------------------------------------------------------

    try:
        (
            organization,
            org_was_created,
        ) = await db_client.get_or_create_organization_by_provider_id(
            org_provider_id=selected_team_id, user_id=user_model.id
        )

        # Check if user's selected organization differs from the current organization
        if user_model.selected_organization_id != organization.id:
            await db_client.add_user_to_organization(user_model.id, organization.id)

            # Update user's selected organization
            await db_client.update_user_selected_organization(
                user_model.id, organization.id
            )

            # Update the user_model object to reflect the change
            user_model.selected_organization_id = organization.id

            # Only create default configuration if organization was just created
            # This prevents race conditions where multiple concurrent requests
            # might try to create configurations
            if org_was_created:
                existing_cfg = await db_client.get_user_configurations(user_model.id)
                if not (existing_cfg.llm or existing_cfg.tts or existing_cfg.stt):
                    mps_config = await create_user_configuration_with_mps_key(
                        user_model.id, organization.id, stack_user["id"]
                    )
                    if mps_config:
                        await db_client.update_user_configuration(
                            user_model.id, mps_config
                        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to map user to organization: {exc}",
        )

    stack_email = (
        stack_user.get("primary_email")
        or stack_user.get("primary_email_address")
        or stack_user.get("email")
    )
    await _maybe_promote_superuser(user_model, stack_user.get("id"), stack_email)

    _auth_cache_set(f"stack:{stack_uid}", user_model)
    return user_model


async def get_user_optional(
    authorization: Annotated[str | None, Header()] = None,
) -> UserModel | None:
    """
    Same as get_user but returns None instead of raising 401 if unauthorized.
    Useful for endpoints that need to work both with and without auth.
    """
    try:
        return await get_user(authorization)
    except HTTPException as e:
        if e.status_code == 401:
            return None
        raise


def _extract_clerk_email(clerk_user: dict) -> str | None:
    """Best-effort extraction of the user's primary email from Clerk user data."""
    emails = clerk_user.get("email_addresses") or []
    primary_id = clerk_user.get("primary_email_address_id")
    if primary_id:
        for entry in emails:
            if entry.get("id") == primary_id:
                addr = entry.get("email_address")
                if addr:
                    return addr
    for entry in emails:
        addr = entry.get("email_address")
        if addr:
            return addr
    claims = clerk_user.get("_token_claims", {}) or {}
    return claims.get("email")


async def _handle_clerk_auth(authorization: str | None) -> UserModel:
    """
    Handle authentication using Clerk.
    Validates the JWT token and creates/fetches user in local database.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    # Validate token and get user from Clerk
    clerk_user = await clerkauth.get_user(authorization)
    if clerk_user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    clerk_user_id = clerk_user.get("id")
    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Invalid user data from Clerk")

    # Fast path: return cached user (avoids 3+ DB queries)
    cached = _auth_cache_get(f"clerk:{clerk_user_id}")
    if cached is not None:
        return cached

    # ------------------------------------------------------------------
    # Get organization from Clerk
    # Clerk uses organization memberships, we'll get the active org from token claims
    # ------------------------------------------------------------------
    token_claims = clerk_user.get("_token_claims", {})
    org_id = token_claims.get("org_id")  # Clerk includes org_id in JWT when org is active

    # If no org in token, try to get the first organization membership
    if not org_id:
        org_memberships = await clerkauth.get_user_organizations(clerk_user_id)
        if org_memberships:
            # Use the first organization membership
            first_membership = org_memberships[0]
            org_data = first_membership.get("organization", {})
            org_id = org_data.get("id")

    # If still no org, create a personal organization for the user
    if not org_id:
        org_id = f"personal_{clerk_user_id}"

    # ------------------------------------------------------------------
    # Persist/Fetch the local User model
    # ------------------------------------------------------------------
    try:
        user_model = await db_client.get_or_create_user_by_provider_id(clerk_user_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error while creating user from database {e}"
        )

    # ------------------------------------------------------------------
    # Persist Organization and mapping in local database
    # ------------------------------------------------------------------
    try:
        (
            organization,
            org_was_created,
        ) = await db_client.get_or_create_organization_by_provider_id(
            org_provider_id=org_id, user_id=user_model.id
        )

        # Check if user's selected organization differs from the current organization
        if user_model.selected_organization_id != organization.id:
            await db_client.add_user_to_organization(user_model.id, organization.id)

            # Update user's selected organization
            await db_client.update_user_selected_organization(
                user_model.id, organization.id
            )

            # Update the user_model object to reflect the change
            user_model.selected_organization_id = organization.id

            # Only create default configuration if organization was just created
            if org_was_created:
                existing_cfg = await db_client.get_user_configurations(user_model.id)
                if not (existing_cfg.llm or existing_cfg.tts or existing_cfg.stt):
                    mps_config = await create_user_configuration_with_mps_key(
                        user_model.id, organization.id, clerk_user_id
                    )
                    if mps_config:
                        await db_client.update_user_configuration(
                            user_model.id, mps_config
                        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to map user to organization: {exc}",
        )

    await _maybe_promote_superuser(
        user_model, clerk_user_id, _extract_clerk_email(clerk_user)
    )

    _auth_cache_set(f"clerk:{clerk_user_id}", user_model)
    return user_model


async def create_user_configuration_with_mps_key(
    user_id: int, organization_id: int, user_provider_id: str
) -> Optional[UserConfiguration]:
    """Create user configuration using MPS service key.

    Args:
        user_id: The user's ID
        organization_id: The organization's ID
        user_provider_id: The user's provider ID (for created_by field)

    Returns:
        UserConfiguration with MPS-provided API keys or None if failed
    """

    async with httpx.AsyncClient() as client:
        # Provisioning a service key always requires the shared MPS secret so
        # that keys are only ever minted for authenticated organizations.
        if not DOGRAH_MPS_SECRET_KEY:
            logger.warning("DOGRAH_MPS_SECRET_KEY not set; cannot provision MPS key")
            raise ValidationError("Missing DOGRAH_MPS_SECRET_KEY")

        response = await client.post(
            f"{MPS_API_URL}/api/v1/service-keys/",
            json={
                "name": f"Default Dograh Model Service Key",
                "description": f"Auto-generated key for organization {organization_id}",
                "organization_id": organization_id,
                "expires_in_days": 90,
                "created_by": user_provider_id,
            },
            headers={"X-Secret-Key": DOGRAH_MPS_SECRET_KEY},
            timeout=10.0,
        )

        if response.status_code == 200:
            data = response.json()
            service_key = data.get("service_key")

            if service_key:
                # Create configuration JSON for storage in database
                # The service_factory will use this to instantiate actual services
                configuration = {
                    "llm": {
                        "provider": ServiceProviders.DOGRAH.value,
                        "api_key": service_key,
                        "model": DograhLLMModel.DEFAULT.value,  # Default model
                    },
                    "tts": {
                        "provider": ServiceProviders.DOGRAH.value,
                        "api_key": service_key,
                        "model": DograhTTSModel.DEFAULT.value,  # Default model
                        "voice": DograhVoice.DEFAULT.value,  # Default voice
                    },
                    "stt": {
                        "provider": ServiceProviders.DOGRAH.value,
                        "api_key": service_key,
                        "model": DograhSTTModel.DEFAULT.value,  # Default model
                    },
                }
                user_config = UserConfiguration(**configuration)
                return user_config
        else:
            logger.warning(
                f"Failed to get MPS service key: {response.status_code} - {response.text}"
            )


async def get_superuser(
    authorization: Annotated[str | None, Header()] = None,
) -> UserModel:
    """
    Dependency to check if the authenticated user is a superuser.
    Raises HTTPException if user is not authenticated or not a superuser.
    """
    user = await get_user(authorization)

    if not user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Access denied. Superuser privileges required."
        )

    return user


async def get_user_ws(
    websocket: WebSocket,
    token: str = Query(None),
) -> UserModel:
    """
    WebSocket authentication dependency.
    Uses token from query parameters for authentication.
    """
    if not token:
        await websocket.close(code=1008, reason="Missing authentication token")
        raise HTTPException(status_code=401, detail="Missing authentication token")

    # Use the same logic as get_user but with token from query
    authorization = f"Bearer {token}"

    try:
        user = await get_user(authorization)
        return user
    except HTTPException as e:
        await websocket.close(code=1008, reason=e.detail)
        raise
