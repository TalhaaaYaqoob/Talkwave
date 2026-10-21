"""Database operations for telecom compliance: internal DNC/suppression list,
consent records, and the immutable audit log.
"""

from datetime import UTC, datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import and_, func
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    ComplianceAuditLogModel,
    ComplianceConsentRecordModel,
    ComplianceDNCEntryModel,
)


class ComplianceClient(BaseDBClient):
    # ------------------------------------------------------------------
    # Internal DNC / suppression list
    # ------------------------------------------------------------------
    async def is_phone_suppressed(
        self, organization_id: int, phone_hash: str
    ) -> bool:
        """Return True if the number is on the org's active suppression list."""
        async with self.async_session() as session:
            result = await session.execute(
                select(ComplianceDNCEntryModel.id).where(
                    and_(
                        ComplianceDNCEntryModel.organization_id == organization_id,
                        ComplianceDNCEntryModel.phone_number_hash == phone_hash,
                        ComplianceDNCEntryModel.is_active.is_(True),
                    )
                ).limit(1)
            )
            return result.scalars().first() is not None

    async def add_dnc_entry(
        self,
        organization_id: int,
        phone_number_hash: str,
        phone_number_e164: str,
        source: str = "internal",
        country_code: Optional[str] = None,
        notes: Optional[str] = None,
        added_by: Optional[int] = None,
    ) -> ComplianceDNCEntryModel:
        """Add (or reactivate) a number on the internal suppression list."""
        async with self.async_session() as session:
            existing = await session.execute(
                select(ComplianceDNCEntryModel).where(
                    and_(
                        ComplianceDNCEntryModel.organization_id == organization_id,
                        ComplianceDNCEntryModel.phone_number_hash
                        == phone_number_hash,
                        ComplianceDNCEntryModel.source == source,
                    )
                )
            )
            entry = existing.scalars().first()
            if entry:
                entry.is_active = True
                entry.phone_number_e164 = phone_number_e164
                if notes is not None:
                    entry.notes = notes
                if country_code is not None:
                    entry.country_code = country_code
                await session.commit()
                await session.refresh(entry)
                return entry

            entry = ComplianceDNCEntryModel(
                organization_id=organization_id,
                phone_number_hash=phone_number_hash,
                phone_number_e164=phone_number_e164,
                source=source,
                country_code=country_code,
                notes=notes,
                added_by=added_by,
                is_active=True,
            )
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            return entry

    async def remove_dnc_entry(
        self, organization_id: int, phone_number_hash: str
    ) -> bool:
        """Soft-remove a number from the suppression list (sets is_active=False)."""
        async with self.async_session() as session:
            result = await session.execute(
                select(ComplianceDNCEntryModel).where(
                    and_(
                        ComplianceDNCEntryModel.organization_id == organization_id,
                        ComplianceDNCEntryModel.phone_number_hash
                        == phone_number_hash,
                        ComplianceDNCEntryModel.is_active.is_(True),
                    )
                )
            )
            entries = list(result.scalars().all())
            if not entries:
                return False
            for entry in entries:
                entry.is_active = False
            await session.commit()
            return True

    async def list_dnc_entries(
        self,
        organization_id: int,
        limit: int = 100,
        offset: int = 0,
        active_only: bool = True,
    ) -> Tuple[List[ComplianceDNCEntryModel], int]:
        """Return ``(entries, total_count)`` for the org's suppression list."""
        async with self.async_session() as session:
            base_filter = [ComplianceDNCEntryModel.organization_id == organization_id]
            if active_only:
                base_filter.append(ComplianceDNCEntryModel.is_active.is_(True))

            count_result = await session.execute(
                select(func.count(ComplianceDNCEntryModel.id)).where(*base_filter)
            )
            total = count_result.scalar() or 0

            result = await session.execute(
                select(ComplianceDNCEntryModel)
                .where(*base_filter)
                .order_by(ComplianceDNCEntryModel.added_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all()), total

    async def get_all_active_dnc_hashes(self, organization_id: int) -> List[str]:
        """Return all active suppression hashes for an org (for Redis cache warm)."""
        async with self.async_session() as session:
            result = await session.execute(
                select(ComplianceDNCEntryModel.phone_number_hash).where(
                    and_(
                        ComplianceDNCEntryModel.organization_id == organization_id,
                        ComplianceDNCEntryModel.is_active.is_(True),
                    )
                )
            )
            return [row for row in result.scalars().all()]

    # ------------------------------------------------------------------
    # Consent records
    # ------------------------------------------------------------------
    async def get_active_consent(
        self, organization_id: int, phone_number_hash: str
    ) -> Optional[ComplianceConsentRecordModel]:
        async with self.async_session() as session:
            result = await session.execute(
                select(ComplianceConsentRecordModel)
                .where(
                    and_(
                        ComplianceConsentRecordModel.organization_id
                        == organization_id,
                        ComplianceConsentRecordModel.phone_number_hash
                        == phone_number_hash,
                        ComplianceConsentRecordModel.is_active.is_(True),
                    )
                )
                .order_by(ComplianceConsentRecordModel.consent_given_at.desc())
                .limit(1)
            )
            return result.scalars().first()

    async def record_consent(
        self,
        organization_id: int,
        phone_number_hash: str,
        phone_number_e164: str,
        consent_type: str = "opt_in",
        regulation: str = "tcpa",
        consent_source: Optional[str] = None,
        evidence_url: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> ComplianceConsentRecordModel:
        async with self.async_session() as session:
            record = ComplianceConsentRecordModel(
                organization_id=organization_id,
                phone_number_hash=phone_number_hash,
                phone_number_e164=phone_number_e164,
                consent_type=consent_type,
                regulation=regulation,
                consent_source=consent_source,
                evidence_url=evidence_url,
                created_by=created_by,
                is_active=True,
                consent_given_at=datetime.now(UTC),
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return record

    async def revoke_consent(
        self, organization_id: int, phone_number_hash: str
    ) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                select(ComplianceConsentRecordModel).where(
                    and_(
                        ComplianceConsentRecordModel.organization_id
                        == organization_id,
                        ComplianceConsentRecordModel.phone_number_hash
                        == phone_number_hash,
                        ComplianceConsentRecordModel.is_active.is_(True),
                    )
                )
            )
            records = list(result.scalars().all())
            if not records:
                return False
            now = datetime.now(UTC)
            for record in records:
                record.is_active = False
                record.consent_revoked_at = now
            await session.commit()
            return True

    async def list_consent_records(
        self,
        organization_id: int,
        limit: int = 100,
        offset: int = 0,
        phone_number_hash: Optional[str] = None,
    ) -> Tuple[List[ComplianceConsentRecordModel], int]:
        async with self.async_session() as session:
            base_filter = [
                ComplianceConsentRecordModel.organization_id == organization_id
            ]
            if phone_number_hash:
                base_filter.append(
                    ComplianceConsentRecordModel.phone_number_hash
                    == phone_number_hash
                )

            count_result = await session.execute(
                select(func.count(ComplianceConsentRecordModel.id)).where(
                    *base_filter
                )
            )
            total = count_result.scalar() or 0

            result = await session.execute(
                select(ComplianceConsentRecordModel)
                .where(*base_filter)
                .order_by(ComplianceConsentRecordModel.consent_given_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all()), total

    async def has_prior_relationship(
        self, organization_id: int, phone_number_hash: str, months: int = 18
    ) -> bool:
        """TCPA established-business-relationship check within a time window."""
        cutoff = datetime.now(UTC) - timedelta(days=months * 30)
        async with self.async_session() as session:
            result = await session.execute(
                select(ComplianceConsentRecordModel.id).where(
                    and_(
                        ComplianceConsentRecordModel.organization_id
                        == organization_id,
                        ComplianceConsentRecordModel.phone_number_hash
                        == phone_number_hash,
                        ComplianceConsentRecordModel.consent_type
                        == "prior_relationship",
                        ComplianceConsentRecordModel.consent_given_at >= cutoff,
                    )
                ).limit(1)
            )
            return result.scalars().first() is not None

    async def erase_phone_data(
        self, organization_id: int, phone_number_hash: str
    ) -> int:
        """UK GDPR right-to-erasure: delete consent + DNC rows for a number.

        Returns the number of rows deleted. Audit log entries are retained
        (they store only the hash, no PII) for regulatory defensibility.
        """
        deleted = 0
        async with self.async_session() as session:
            consent_result = await session.execute(
                select(ComplianceConsentRecordModel).where(
                    and_(
                        ComplianceConsentRecordModel.organization_id
                        == organization_id,
                        ComplianceConsentRecordModel.phone_number_hash
                        == phone_number_hash,
                    )
                )
            )
            for record in consent_result.scalars().all():
                await session.delete(record)
                deleted += 1

            dnc_result = await session.execute(
                select(ComplianceDNCEntryModel).where(
                    and_(
                        ComplianceDNCEntryModel.organization_id == organization_id,
                        ComplianceDNCEntryModel.phone_number_hash
                        == phone_number_hash,
                    )
                )
            )
            for entry in dnc_result.scalars().all():
                await session.delete(entry)
                deleted += 1

            await session.commit()
        return deleted

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------
    async def write_audit_log(
        self,
        organization_id: int,
        action: str,
        phone_number_hash: Optional[str] = None,
        campaign_id: Optional[int] = None,
        workflow_run_id: Optional[int] = None,
        regulation: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> ComplianceAuditLogModel:
        async with self.async_session() as session:
            entry = ComplianceAuditLogModel(
                organization_id=organization_id,
                action=action,
                phone_number_hash=phone_number_hash,
                campaign_id=campaign_id,
                workflow_run_id=workflow_run_id,
                regulation=regulation,
                details=details or {},
            )
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            return entry

    async def list_audit_log(
        self,
        organization_id: int,
        limit: int = 100,
        offset: int = 0,
        action: Optional[str] = None,
        campaign_id: Optional[int] = None,
    ) -> Tuple[List[ComplianceAuditLogModel], int]:
        async with self.async_session() as session:
            base_filter = [ComplianceAuditLogModel.organization_id == organization_id]
            if action:
                base_filter.append(ComplianceAuditLogModel.action == action)
            if campaign_id is not None:
                base_filter.append(ComplianceAuditLogModel.campaign_id == campaign_id)

            count_result = await session.execute(
                select(func.count(ComplianceAuditLogModel.id)).where(*base_filter)
            )
            total = count_result.scalar() or 0

            result = await session.execute(
                select(ComplianceAuditLogModel)
                .where(*base_filter)
                .order_by(ComplianceAuditLogModel.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all()), total

    async def delete_audit_logs_before(self, cutoff: datetime) -> int:
        """Retention cleanup: delete audit rows older than ``cutoff``."""
        async with self.async_session() as session:
            result = await session.execute(
                select(ComplianceAuditLogModel).where(
                    ComplianceAuditLogModel.created_at < cutoff
                )
            )
            rows = list(result.scalars().all())
            for row in rows:
                await session.delete(row)
            await session.commit()
            return len(rows)
