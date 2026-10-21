"""
Clerk Authentication Service

This module provides authentication utilities for validating Clerk JWT tokens
and fetching user information from Clerk's API.
"""

import os
from typing import Any, Optional

import aiohttp
from jose import JWTError, jwk, jwt
from loguru import logger


class ClerkAuth:
    """
    Clerk authentication service that validates JWTs and fetches user data.
    """

    def __init__(self):
        self.secret_key = os.environ.get("CLERK_SECRET_KEY")
        self.publishable_key = os.environ.get("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY")
        self.api_url = os.environ.get("CLERK_API_URL", "https://api.clerk.com")
        self._jwks_cache: Optional[dict] = None
        self._jwks_cache_time: float = 0

    def _strip_bearer(self, access_token: str | None) -> str | None:
        """Remove the leading 'Bearer ' prefix from the token if present."""
        if not access_token:
            return None
        if access_token.startswith("Bearer "):
            return access_token.split(" ", 1)[1]
        return access_token

    async def _get_jwks(self) -> dict:
        """
        Fetch Clerk's JWKS (JSON Web Key Set) for token verification.
        Caches the JWKS for performance.
        """
        import time

        # Cache JWKS for 1 hour
        current_time = time.time()
        if self._jwks_cache and (current_time - self._jwks_cache_time) < 3600:
            return self._jwks_cache

        # Extract the Clerk frontend API URL from publishable key
        # Publishable key format: pk_test_xxxx or pk_live_xxxx
        # The domain can be extracted from the JWT issuer
        jwks_url = f"{self.api_url}/v1/jwks"

        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/json",
            }
            async with session.get(jwks_url, headers=headers) as response:
                if response.status == 200:
                    self._jwks_cache = await response.json()
                    self._jwks_cache_time = current_time
                    return self._jwks_cache
                else:
                    logger.error(f"Failed to fetch JWKS: {response.status}")
                    raise ValueError("Failed to fetch JWKS from Clerk")

    async def verify_token(self, access_token: str) -> Optional[dict]:
        """
        Verify a Clerk JWT token and return the decoded claims.

        Args:
            access_token: The JWT token (with or without 'Bearer ' prefix)

        Returns:
            Decoded token claims if valid, None otherwise
        """
        token = self._strip_bearer(access_token)
        if not token:
            return None

        try:
            # Decode token header to get the key ID
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            # Get JWKS and find the matching key
            jwks_data = await self._get_jwks()
            keys = jwks_data.get("keys", [])

            matching_key = None
            for key in keys:
                if key.get("kid") == kid:
                    matching_key = key
                    break

            if not matching_key:
                logger.error(f"No matching key found for kid: {kid}")
                return None

            # Convert JWK to PEM format for verification
            public_key = jwk.construct(matching_key)

            # Verify and decode the token
            claims = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                options={"verify_aud": False},  # Clerk doesn't always set audience
            )

            return claims

        except JWTError as e:
            logger.error(f"JWT verification error: {e}")
            return None
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            return None

    async def get_user(self, access_token: str) -> Optional[dict[str, Any]]:
        """
        Validate the access token and fetch user information from Clerk.

        Args:
            access_token: The JWT token (with or without 'Bearer ' prefix)

        Returns:
            User data dict if authenticated, None otherwise
        """
        if not access_token:
            return None

        token = self._strip_bearer(access_token)
        if not token:
            return None

        # First verify the token
        claims = await self.verify_token(token)
        if not claims:
            return None

        # Extract user ID from claims (Clerk uses 'sub' for user ID)
        user_id = claims.get("sub")
        if not user_id:
            logger.error("No user ID (sub) in token claims")
            return None

        # Fetch full user details from Clerk API
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.secret_key}",
                    "Content-Type": "application/json",
                }
                url = f"{self.api_url}/v1/users/{user_id}"

                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        user_data = await response.json()
                        # Add token claims to user data for convenience
                        user_data["_token_claims"] = claims
                        return user_data
                    else:
                        logger.error(
                            f"Failed to fetch user from Clerk: {response.status}"
                        )
                        # Return minimal user data from token claims
                        return {
                            "id": user_id,
                            "email_addresses": [],
                            "first_name": claims.get("first_name"),
                            "last_name": claims.get("last_name"),
                            "_token_claims": claims,
                        }

        except Exception as e:
            logger.error(f"Error fetching user from Clerk: {e}")
            # Return minimal user data from token claims
            return {
                "id": user_id,
                "_token_claims": claims,
            }

    async def get_user_organizations(self, user_id: str) -> list[dict]:
        """
        Fetch organizations for a user from Clerk.

        Args:
            user_id: The Clerk user ID

        Returns:
            List of organization memberships
        """
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.secret_key}",
                    "Content-Type": "application/json",
                }
                url = f"{self.api_url}/v1/users/{user_id}/organization_memberships"

                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("data", [])
                    body = await response.text()
                    # 403 usually means Organizations are disabled in Clerk, or
                    # CLERK_SECRET_KEY / CLERK_API_URL is wrong for the Backend API.
                    # This is non-fatal: auth falls back to a personal_* org.
                    logger.error(
                        f"Failed to fetch user organizations: {response.status} "
                        f"url={url} body={body[:300]}"
                    )
                    return []

        except Exception as e:
            logger.error(f"Error fetching user organizations: {e}")
            return []

    async def get_organization(self, org_id: str) -> Optional[dict]:
        """
        Fetch organization details from Clerk.

        Args:
            org_id: The Clerk organization ID

        Returns:
            Organization data dict if found, None otherwise
        """
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.secret_key}",
                    "Content-Type": "application/json",
                }
                url = f"{self.api_url}/v1/organizations/{org_id}"

                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(
                            f"Failed to fetch organization: {response.status}"
                        )
                        return None

        except Exception as e:
            logger.error(f"Error fetching organization: {e}")
            return None


# Singleton instance
clerkauth = ClerkAuth()

