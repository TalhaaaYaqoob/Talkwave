"""Consent management for outbound calling compliance.

Tracks express/opt-in consent (TCPA in the US, PECR / UK GDPR in the UK),
supports revocation (which also suppresses the number), prior-business-
relationship checks, and GDPR right-to-erasure.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from loguru import logger

from api.db import db_client
from api.services.compliance.phone_utils import (
    get_compliance_region,
    normalize_and_hash,
)


@dataclass
class ConsentStatus:
    has_consent: bool
    reason: str
    consent_type: Optional[str] = None
    regulation: Optional[str] = None


class ConsentManager:
    async def has_valid_consent(
        self, organization_id: int, phone: str, region: Optional[str] = None
    ) -> ConsentStatus:
        """Check whether there's an active consent record for a number.

        Falls back to a prior-business-relationship check (TCPA EBR) when no
        explicit consent exists.
        """
        parsed = normalize_and_hash(phone)
        if not parsed:
            return ConsentStatus(False, "invalid_phone_number")
        _, phone_hash = parsed

        consent = await db_client.get_active_consent(organization_id, phone_hash)
        if consent:
            return ConsentStatus(
                True,
                "active_consent",
                consent_type=consent.consent_type,
                regulation=consent.regulation,
            )

        # TCPA established business relationship fallback (US only)
        effective_region = region or get_compliance_region(phone)
        if effective_region == "us":
            if await db_client.has_prior_relationship(organization_id, phone_hash):
                return ConsentStatus(
                    True, "prior_business_relationship", consent_type="prior_relationship"
                )

        return ConsentStatus(False, "no_consent_on_record")

    async def record_consent(
        self,
        organization_id: int,
        phone: str,
        consent_type: str = "opt_in",
        regulation: Optional[str] = None,
        consent_source: Optional[str] = None,
        evidence_url: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> Optional[int]:
        parsed = normalize_and_hash(phone)
        if not parsed:
            logger.warning(f"Cannot record consent for unparseable number: {phone}")
            return None
        e164, phone_hash = parsed

        if regulation is None:
            region = get_compliance_region(phone)
            regulation = "pecr" if region == "gb" else "tcpa"

        record = await db_client.record_consent(
            organization_id=organization_id,
            phone_number_hash=phone_hash,
            phone_number_e164=e164,
            consent_type=consent_type,
            regulation=regulation,
            consent_source=consent_source,
            evidence_url=evidence_url,
            created_by=created_by,
        )

        await db_client.write_audit_log(
            organization_id=organization_id,
            action="consent_recorded",
            phone_number_hash=phone_hash,
            regulation=regulation,
            details={"consent_type": consent_type, "source": consent_source},
        )
        return record.id

    async def revoke_consent(
        self, organization_id: int, phone: str, suppress: bool = True
    ) -> bool:
        """Revoke consent and (by default) add the number to the suppression list."""
        parsed = normalize_and_hash(phone)
        if not parsed:
            return False
        _, phone_hash = parsed

        revoked = await db_client.revoke_consent(organization_id, phone_hash)

        await db_client.write_audit_log(
            organization_id=organization_id,
            action="consent_revoked",
            phone_number_hash=phone_hash,
            details={"suppressed": suppress},
        )

        if suppress:
            # Import here to avoid a circular import at module load time.
            from api.services.compliance.dnc_service import dnc_service

            await dnc_service.add_to_dnc(
                organization_id, phone, source="opt_out_request"
            )

        return revoked

    async def list_consent(
        self,
        organization_id: int,
        limit: int = 100,
        offset: int = 0,
        phone: Optional[str] = None,
    ) -> Tuple[List, int]:
        phone_hash = None
        if phone:
            parsed = normalize_and_hash(phone)
            if parsed:
                _, phone_hash = parsed
        return await db_client.list_consent_records(
            organization_id, limit=limit, offset=offset, phone_number_hash=phone_hash
        )

    async def erase_data(self, organization_id: int, phone: str) -> int:
        """UK GDPR right to erasure: remove all consent + DNC data for a number."""
        parsed = normalize_and_hash(phone)
        if not parsed:
            return 0
        _, phone_hash = parsed

        deleted = await db_client.erase_phone_data(organization_id, phone_hash)

        # Drop from Redis cache too
        try:
            from api.services.compliance.dnc_service import dnc_service

            redis_client = await dnc_service._get_redis()
            await redis_client.srem(dnc_service._set_key(organization_id), phone_hash)
        except Exception:
            pass

        await db_client.write_audit_log(
            organization_id=organization_id,
            action="data_erased",
            phone_number_hash=phone_hash,
            regulation="uk_gdpr",
            details={"rows_deleted": deleted},
        )
        return deleted


# Global instance
consent_manager = ConsentManager()
