"""Internal Do-Not-Call / suppression list service.

Phase A: org-managed suppression list backed by PostgreSQL, with a Redis set
per organization for O(1) lookups on the call hot-path.

Phase B extension points (not yet active): ``sync_ftc_dnc()`` and
``sync_tps()`` would bulk-load external registry numbers into the same store.
"""

from typing import List, Optional

import redis.asyncio as aioredis
from loguru import logger

from api.constants import REDIS_URL
from api.db import db_client
from api.services.compliance.phone_utils import (
    get_country_code,
    normalize_and_hash,
)

# Redis key for the per-org suppression set of phone hashes.
_DNC_SET_KEY = "compliance:dnc:{org_id}"
# Sentinel member so an empty-but-warmed set is distinguishable from "cold".
_WARM_SENTINEL = "__warm__"
_DNC_TTL_SECONDS = 24 * 60 * 60  # refresh daily


class DNCService:
    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        if self.redis_client is None:
            self.redis_client = await aioredis.from_url(
                REDIS_URL, decode_responses=True
            )
        return self.redis_client

    def _set_key(self, organization_id: int) -> str:
        return _DNC_SET_KEY.format(org_id=organization_id)

    async def is_suppressed(self, organization_id: int, phone: str) -> bool:
        """Return True if the number is on the org's suppression list.

        Checks the Redis hot-cache first; warms it from the DB on a miss.
        """
        parsed = normalize_and_hash(phone)
        if not parsed:
            # Unparseable numbers can't be matched against the list; treat as
            # not suppressed but let the caller decide (the gate validates E.164).
            return False
        _, phone_hash = parsed
        return await self.is_suppressed_hash(organization_id, phone_hash)

    async def is_suppressed_hash(
        self, organization_id: int, phone_hash: str
    ) -> bool:
        try:
            redis_client = await self._get_redis()
            key = self._set_key(organization_id)
            if not await redis_client.exists(key):
                await self._warm_cache(organization_id)
            is_member = await redis_client.sismember(key, phone_hash)
            return bool(is_member)
        except Exception as e:
            logger.warning(
                f"DNC Redis lookup failed for org {organization_id}, "
                f"falling back to DB: {e}"
            )
            return await db_client.is_phone_suppressed(organization_id, phone_hash)

    async def _warm_cache(self, organization_id: int) -> None:
        """Load all active suppression hashes for an org into Redis."""
        try:
            hashes = await db_client.get_all_active_dnc_hashes(organization_id)
            redis_client = await self._get_redis()
            key = self._set_key(organization_id)
            pipe = redis_client.pipeline()
            pipe.delete(key)
            pipe.sadd(key, _WARM_SENTINEL, *hashes)
            pipe.expire(key, _DNC_TTL_SECONDS)
            await pipe.execute()
            logger.info(
                f"Warmed DNC cache for org {organization_id}: {len(hashes)} entries"
            )
        except Exception as e:
            logger.warning(f"Failed to warm DNC cache for org {organization_id}: {e}")

    async def warm_cache(self, organization_id: int) -> None:
        """Public wrapper for warming the cache (used by background jobs)."""
        await self._warm_cache(organization_id)

    async def add_to_dnc(
        self,
        organization_id: int,
        phone: str,
        source: str = "internal",
        notes: Optional[str] = None,
        added_by: Optional[int] = None,
    ) -> Optional[str]:
        """Add a number to the suppression list. Returns the E.164 number added."""
        parsed = normalize_and_hash(phone)
        if not parsed:
            logger.warning(f"Cannot add unparseable number to DNC: {phone}")
            return None
        e164, phone_hash = parsed
        country = get_country_code(phone)

        await db_client.add_dnc_entry(
            organization_id=organization_id,
            phone_number_hash=phone_hash,
            phone_number_e164=e164,
            source=source,
            country_code=country,
            notes=notes,
            added_by=added_by,
        )

        # Update hot-cache
        try:
            redis_client = await self._get_redis()
            key = self._set_key(organization_id)
            if await redis_client.exists(key):
                await redis_client.sadd(key, phone_hash)
        except Exception as e:
            logger.warning(f"Failed to update DNC cache on add: {e}")

        await db_client.write_audit_log(
            organization_id=organization_id,
            action="dnc_added",
            phone_number_hash=phone_hash,
            regulation="dnc",
            details={"source": source},
        )
        return e164

    async def remove_from_dnc(self, organization_id: int, phone: str) -> bool:
        parsed = normalize_and_hash(phone)
        if not parsed:
            return False
        _, phone_hash = parsed

        removed = await db_client.remove_dnc_entry(organization_id, phone_hash)
        if removed:
            try:
                redis_client = await self._get_redis()
                key = self._set_key(organization_id)
                await redis_client.srem(key, phone_hash)
            except Exception as e:
                logger.warning(f"Failed to update DNC cache on remove: {e}")

            await db_client.write_audit_log(
                organization_id=organization_id,
                action="dnc_removed",
                phone_number_hash=phone_hash,
                regulation="dnc",
            )
        return removed

    async def bulk_import(
        self,
        organization_id: int,
        phones: List[str],
        source: str = "internal",
        added_by: Optional[int] = None,
    ) -> dict:
        """Bulk-add numbers. Returns counts of added vs. skipped."""
        added = 0
        skipped = 0
        for phone in phones:
            result = await self.add_to_dnc(
                organization_id, phone, source=source, added_by=added_by
            )
            if result:
                added += 1
            else:
                skipped += 1
        # Invalidate cache so it re-warms with the full set on next lookup
        try:
            redis_client = await self._get_redis()
            await redis_client.delete(self._set_key(organization_id))
        except Exception:
            pass
        return {"added": added, "skipped": skipped, "total": len(phones)}


# Global instance
dnc_service = DNCService()
