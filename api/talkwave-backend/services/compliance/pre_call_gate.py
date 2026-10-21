"""Pre-call compliance gate.

A single entry point the campaign dispatcher consults before every outbound
call. Runs internal DNC scrub, consent verification, and TCPA calling-hours
checks, writes an audit-log entry for the decision, and returns whether the
call may proceed (plus the AI-disclosure config to inject into the pipeline).
"""

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from api.db import db_client
from api.services.compliance.calling_hours import is_within_permitted_hours
from api.services.compliance.consent_manager import consent_manager
from api.services.compliance.dnc_service import dnc_service
from api.services.compliance.phone_utils import (
    get_compliance_region,
    normalize_and_hash,
)

# Default AI disclosures per region (FCC Feb-2024 ruling / PECR transparency).
DEFAULT_AI_DISCLOSURE_US = (
    "Please be advised, this call uses artificial intelligence technology."
)
DEFAULT_AI_DISCLOSURE_UK = "This call uses an AI voice assistant."


@dataclass
class ComplianceResult:
    allowed: bool
    reason: str
    region: str = "us"
    ai_disclosure_enabled: bool = True
    ai_disclosure_text: Optional[str] = None
    phone_hash: Optional[str] = None
    details: dict = field(default_factory=dict)


class PreCallComplianceGate:
    async def check(
        self,
        organization_id: int,
        phone: str,
        campaign=None,
    ) -> ComplianceResult:
        """Evaluate all compliance rules for an outbound call.

        ``campaign`` is the CampaignModel (optional). When absent (e.g. manual
        test calls) sensible defaults are used: DNC scrub on, consent not
        required, AI disclosure on.
        """
        # Campaign-level toggles with safe defaults
        dnc_scrub_enabled = getattr(campaign, "dnc_scrub_enabled", True)
        consent_required = getattr(campaign, "consent_required", False)
        ai_disclosure_enabled = getattr(campaign, "ai_disclosure_enabled", True)
        campaign_ai_text = getattr(campaign, "ai_disclosure_text", None)
        campaign_id = getattr(campaign, "id", None)

        parsed = normalize_and_hash(phone)
        if not parsed:
            return ComplianceResult(
                allowed=False,
                reason="invalid_phone_number",
                ai_disclosure_enabled=ai_disclosure_enabled,
            )
        e164, phone_hash = parsed
        region = get_compliance_region(phone)

        ai_disclosure_text = campaign_ai_text or (
            DEFAULT_AI_DISCLOSURE_UK if region == "gb" else DEFAULT_AI_DISCLOSURE_US
        )

        # 1. Internal DNC / suppression list
        if dnc_scrub_enabled:
            if await dnc_service.is_suppressed_hash(organization_id, phone_hash):
                await self._audit(
                    organization_id, "call_blocked_dnc", phone_hash, campaign_id, "dnc"
                )
                return ComplianceResult(
                    allowed=False,
                    reason="on_dnc_list",
                    region=region,
                    ai_disclosure_enabled=ai_disclosure_enabled,
                    ai_disclosure_text=ai_disclosure_text,
                    phone_hash=phone_hash,
                )

        # 2. Consent verification
        if consent_required:
            status = await consent_manager.has_valid_consent(
                organization_id, phone, region
            )
            if not status.has_consent:
                regulation = "pecr" if region == "gb" else "tcpa"
                await self._audit(
                    organization_id,
                    "call_blocked_no_consent",
                    phone_hash,
                    campaign_id,
                    regulation,
                )
                return ComplianceResult(
                    allowed=False,
                    reason=f"no_consent:{status.reason}",
                    region=region,
                    ai_disclosure_enabled=ai_disclosure_enabled,
                    ai_disclosure_text=ai_disclosure_text,
                    phone_hash=phone_hash,
                )

        # 3. TCPA / best-practice calling hours (recipient local time)
        allowed_hours, hours_reason = is_within_permitted_hours(phone)
        if not allowed_hours:
            regulation = "pecr" if region == "gb" else "tcpa"
            await self._audit(
                organization_id,
                "call_blocked_hours",
                phone_hash,
                campaign_id,
                regulation,
                details={"hours_reason": hours_reason},
            )
            return ComplianceResult(
                allowed=False,
                reason=hours_reason,
                region=region,
                ai_disclosure_enabled=ai_disclosure_enabled,
                ai_disclosure_text=ai_disclosure_text,
                phone_hash=phone_hash,
            )

        # Allowed
        await self._audit(
            organization_id, "call_allowed", phone_hash, campaign_id, None
        )
        return ComplianceResult(
            allowed=True,
            reason="passed",
            region=region,
            ai_disclosure_enabled=ai_disclosure_enabled,
            ai_disclosure_text=ai_disclosure_text,
            phone_hash=phone_hash,
        )

    async def _audit(
        self,
        organization_id: int,
        action: str,
        phone_hash: str,
        campaign_id: Optional[int],
        regulation: Optional[str],
        details: Optional[dict] = None,
    ) -> None:
        try:
            await db_client.write_audit_log(
                organization_id=organization_id,
                action=action,
                phone_number_hash=phone_hash,
                campaign_id=campaign_id,
                regulation=regulation,
                details=details or {},
            )
        except Exception as e:
            # Auditing must never break call dispatch
            logger.warning(f"Failed to write compliance audit log ({action}): {e}")


# Global instance
pre_call_gate = PreCallComplianceGate()
