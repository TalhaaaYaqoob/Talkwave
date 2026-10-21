"""Compliance API: internal DNC/suppression list, consent records, audit log,
and org compliance settings.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.enums import OrganizationConfigurationKey
from api.services.auth.depends import get_user
from api.services.compliance.consent_manager import consent_manager
from api.services.compliance.dnc_service import dnc_service
from api.services.compliance.phone_utils import normalize_e164

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/compliance")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class DNCEntryResponse(BaseModel):
    id: int
    phone_number: str
    source: str
    country_code: Optional[str] = None
    notes: Optional[str] = None
    added_at: Optional[datetime] = None


class DNCListResponse(BaseModel):
    entries: List[DNCEntryResponse]
    total: int


class AddDNCRequest(BaseModel):
    phone_numbers: List[str] = Field(..., min_length=1)
    notes: Optional[str] = None


class CheckDNCRequest(BaseModel):
    phone_numbers: List[str] = Field(..., min_length=1)


class CheckDNCResult(BaseModel):
    phone_number: str
    suppressed: bool
    normalized: Optional[str] = None


class ConsentResponse(BaseModel):
    id: int
    phone_number: str
    consent_type: str
    regulation: str
    consent_source: Optional[str] = None
    evidence_url: Optional[str] = None
    is_active: bool
    consent_given_at: Optional[datetime] = None
    consent_revoked_at: Optional[datetime] = None


class ConsentListResponse(BaseModel):
    records: List[ConsentResponse]
    total: int


class RecordConsentRequest(BaseModel):
    phone_number: str
    consent_type: str = Field(
        "opt_in",
        pattern="^(express_written|express_oral|prior_relationship|opt_in)$",
    )
    regulation: Optional[str] = Field(None, pattern="^(tcpa|pecr|uk_gdpr)$")
    consent_source: Optional[str] = None
    evidence_url: Optional[str] = None


class AuditLogResponse(BaseModel):
    id: int
    action: str
    regulation: Optional[str] = None
    campaign_id: Optional[int] = None
    workflow_run_id: Optional[int] = None
    phone_number_hash: Optional[str] = None
    details: dict = {}
    created_at: Optional[datetime] = None


class AuditLogListResponse(BaseModel):
    entries: List[AuditLogResponse]
    total: int


class ComplianceSettings(BaseModel):
    default_region: str = "us"
    consent_retention_days: int = 1825  # ~5 years
    ai_disclosure_default_text: Optional[str] = None


# ---------------------------------------------------------------------------
# Internal DNC / suppression list
# ---------------------------------------------------------------------------
@router.get("/dnc", response_model=DNCListResponse)
async def list_dnc(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: UserModel = Depends(get_user),
) -> DNCListResponse:
    entries, total = await db_client.list_dnc_entries(
        user.selected_organization_id, limit=limit, offset=offset
    )
    return DNCListResponse(
        entries=[
            DNCEntryResponse(
                id=e.id,
                phone_number=e.phone_number_e164,
                source=e.source,
                country_code=e.country_code,
                notes=e.notes,
                added_at=e.added_at,
            )
            for e in entries
        ],
        total=total,
    )


@router.post("/dnc")
async def add_dnc(
    request: AddDNCRequest,
    user: UserModel = Depends(get_user),
) -> dict:
    result = await dnc_service.bulk_import(
        user.selected_organization_id,
        request.phone_numbers,
        source="internal",
        added_by=user.id,
    )
    return result


@router.delete("/dnc/{phone_number}")
async def remove_dnc(
    phone_number: str,
    user: UserModel = Depends(get_user),
) -> dict:
    removed = await dnc_service.remove_from_dnc(
        user.selected_organization_id, phone_number
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Number not found on DNC list")
    return {"removed": True, "phone_number": normalize_e164(phone_number)}


@router.post("/dnc/check", response_model=List[CheckDNCResult])
async def check_dnc(
    request: CheckDNCRequest,
    user: UserModel = Depends(get_user),
) -> List[CheckDNCResult]:
    results = []
    for phone in request.phone_numbers:
        normalized = normalize_e164(phone)
        suppressed = await dnc_service.is_suppressed(
            user.selected_organization_id, phone
        )
        results.append(
            CheckDNCResult(
                phone_number=phone, suppressed=suppressed, normalized=normalized
            )
        )
    return results


# ---------------------------------------------------------------------------
# Consent records
# ---------------------------------------------------------------------------
@router.get("/consent", response_model=ConsentListResponse)
async def list_consent(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    phone_number: Optional[str] = Query(None),
    user: UserModel = Depends(get_user),
) -> ConsentListResponse:
    records, total = await consent_manager.list_consent(
        user.selected_organization_id,
        limit=limit,
        offset=offset,
        phone=phone_number,
    )
    return ConsentListResponse(
        records=[
            ConsentResponse(
                id=r.id,
                phone_number=r.phone_number_e164,
                consent_type=r.consent_type,
                regulation=r.regulation,
                consent_source=r.consent_source,
                evidence_url=r.evidence_url,
                is_active=r.is_active,
                consent_given_at=r.consent_given_at,
                consent_revoked_at=r.consent_revoked_at,
            )
            for r in records
        ],
        total=total,
    )


@router.post("/consent")
async def record_consent(
    request: RecordConsentRequest,
    user: UserModel = Depends(get_user),
) -> dict:
    record_id = await consent_manager.record_consent(
        organization_id=user.selected_organization_id,
        phone=request.phone_number,
        consent_type=request.consent_type,
        regulation=request.regulation,
        consent_source=request.consent_source,
        evidence_url=request.evidence_url,
        created_by=user.id,
    )
    if record_id is None:
        raise HTTPException(status_code=400, detail="Invalid phone number")
    return {"id": record_id, "recorded": True}


@router.delete("/consent/{phone_number}")
async def revoke_consent(
    phone_number: str,
    user: UserModel = Depends(get_user),
) -> dict:
    revoked = await consent_manager.revoke_consent(
        user.selected_organization_id, phone_number, suppress=True
    )
    return {"revoked": revoked, "suppressed": True}


@router.delete("/data/{phone_number}")
async def erase_data(
    phone_number: str,
    user: UserModel = Depends(get_user),
) -> dict:
    """UK GDPR right to erasure: delete all consent + DNC data for a number."""
    deleted = await consent_manager.erase_data(
        user.selected_organization_id, phone_number
    )
    return {"rows_deleted": deleted}


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
@router.get("/audit-log", response_model=AuditLogListResponse)
async def list_audit_log(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None),
    campaign_id: Optional[int] = Query(None),
    user: UserModel = Depends(get_user),
) -> AuditLogListResponse:
    entries, total = await db_client.list_audit_log(
        user.selected_organization_id,
        limit=limit,
        offset=offset,
        action=action,
        campaign_id=campaign_id,
    )
    return AuditLogListResponse(
        entries=[
            AuditLogResponse(
                id=e.id,
                action=e.action,
                regulation=e.regulation,
                campaign_id=e.campaign_id,
                workflow_run_id=e.workflow_run_id,
                phone_number_hash=e.phone_number_hash,
                details=e.details or {},
                created_at=e.created_at,
            )
            for e in entries
        ],
        total=total,
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@router.get("/settings", response_model=ComplianceSettings)
async def get_settings(
    user: UserModel = Depends(get_user),
) -> ComplianceSettings:
    config = await db_client.get_configuration(
        user.selected_organization_id,
        OrganizationConfigurationKey.COMPLIANCE_SETTINGS.value,
    )
    if config and config.value:
        return ComplianceSettings(**config.value)
    return ComplianceSettings()


@router.put("/settings", response_model=ComplianceSettings)
async def update_settings(
    settings: ComplianceSettings,
    user: UserModel = Depends(get_user),
) -> ComplianceSettings:
    await db_client.upsert_configuration(
        user.selected_organization_id,
        OrganizationConfigurationKey.COMPLIANCE_SETTINGS.value,
        settings.model_dump(),
    )
    return settings
