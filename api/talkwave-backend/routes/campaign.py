import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.enums import OrganizationConfigurationKey
from api.services.auth.depends import get_user
from api.services.campaign.runner import campaign_runner_service
from api.services.storage import storage_fs
from api.services.subscription.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaign")

# Subscription service for limit checks
_sub_service = SubscriptionService()


class CreateCampaignRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    workflow_id: int
    source_type: str = Field(..., pattern="^(google-sheet|csv)$")
    source_id: str  # Google Sheet URL or CSV file key
    scheduled_start_at: Optional[datetime] = None
    calling_window_start: Optional[str] = Field(
        None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="HH:MM 24h format"
    )
    calling_window_end: Optional[str] = Field(
        None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$", description="HH:MM 24h format"
    )
    calling_window_timezone: Optional[str] = Field(
        None, description="IANA timezone e.g. America/New_York"
    )


class UpdateScheduleRequest(BaseModel):
    scheduled_start_at: Optional[datetime] = None
    calling_window_start: Optional[str] = Field(
        None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    calling_window_end: Optional[str] = Field(
        None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$"
    )
    calling_window_timezone: Optional[str] = None


class CampaignResponse(BaseModel):
    id: int
    name: str
    workflow_id: int
    workflow_name: str
    state: str
    source_type: str
    source_id: str
    total_rows: Optional[int]
    processed_rows: int
    failed_rows: int
    completed_calls: int = 0
    scheduled_start_at: Optional[datetime] = None
    calling_window_start: Optional[str] = None
    calling_window_end: Optional[str] = None
    calling_window_timezone: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class CampaignsResponse(BaseModel):
    campaigns: List[CampaignResponse]


class WorkflowRunResponse(BaseModel):
    id: int
    workflow_id: int
    state: str
    created_at: datetime
    completed_at: Optional[datetime]


class CampaignContactResponse(BaseModel):
    id: int
    phone_number: str
    first_name: str
    last_name: str
    status: str
    disposition: Optional[str] = None
    call_duration: Optional[float] = None
    retry_count: int = 0
    retry_reason: Optional[str] = None
    created_at: Optional[str] = None
    processed_at: Optional[str] = None
    workflow_run_id: Optional[int] = None


class CampaignContactsResponse(BaseModel):
    contacts: List[CampaignContactResponse]
    total: int
    offset: int
    limit: int


class CampaignAnalyticsResponse(BaseModel):
    total_contacts: int = 0
    processed: int = 0
    failed: int = 0
    remaining: int = 0
    connected_calls: int = 0
    total_calls_made: int = 0
    avg_call_duration: float = 0.0
    total_call_duration: float = 0.0
    disposition_breakdown: dict = {}


class CampaignProgressResponse(BaseModel):
    campaign_id: int
    state: str
    total_rows: int
    processed_rows: int
    failed_calls: int
    progress_percentage: float
    source_sync: dict
    rate_limit: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


def _campaign_to_response(
    campaign, workflow_name: str, connected_calls: int | None = None,
) -> CampaignResponse:
    """Convert a CampaignModel to CampaignResponse."""
    completed = connected_calls if connected_calls is not None else 0
    return CampaignResponse(
        id=campaign.id,
        name=campaign.name,
        workflow_id=campaign.workflow_id,
        workflow_name=workflow_name,
        state=campaign.state,
        source_type=campaign.source_type,
        source_id=campaign.source_id,
        total_rows=campaign.total_rows,
        processed_rows=campaign.processed_rows,
        failed_rows=campaign.failed_rows,
        completed_calls=completed,
        scheduled_start_at=campaign.scheduled_start_at,
        calling_window_start=campaign.calling_window_start,
        calling_window_end=campaign.calling_window_end,
        calling_window_timezone=campaign.calling_window_timezone,
        created_at=campaign.created_at,
        started_at=campaign.started_at,
        completed_at=campaign.completed_at,
    )


@router.post("/create")
async def create_campaign(
    request: CreateCampaignRequest,
    user: UserModel = Depends(get_user),
) -> CampaignResponse:
    """Create a new campaign"""
    # Check subscription allows campaigns
    can_campaign = await _sub_service.check_can_create_campaign(
        user.selected_organization_id
    )
    if not can_campaign["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_campaign["reason"],
                "message": can_campaign.get("message", "Subscription limit reached"),
            },
        )

    # Validate CSV source schema before creating campaign
    if request.source_type == "csv":
        from api.services.campaign.sources.csv import CSVSyncService
        csv_service = CSVSyncService()
        try:
            is_valid = await csv_service.validate_source_schema({"source_id": request.source_id})
            if not is_valid:
                raise HTTPException(
                    status_code=400,
                    detail="CSV file is missing required columns: phone_number, first_name, last_name. "
                           "Please upload a CSV with these columns and try again.",
                )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Failed to validate CSV file: {str(e)}")

    # Verify workflow exists and belongs to organization
    workflow_name = await db_client.get_workflow_name(request.workflow_id, user.id)
    if not workflow_name:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check telephony is configured before creating
    twilio_config = await db_client.get_configuration(
        user.selected_organization_id,
        OrganizationConfigurationKey.TELEPHONY_CONFIGURATION.value,
    )
    if not twilio_config or not twilio_config.value:
        raise HTTPException(
            status_code=401,
            detail="You must configure telephony before creating a campaign.",
        )

    # Check call quota
    can_call = await _sub_service.check_can_make_call(
        user.selected_organization_id
    )
    if not can_call["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_call["reason"],
                "message": can_call.get("message", "Subscription limit reached"),
            },
        )

    campaign = await db_client.create_campaign(
        name=request.name,
        workflow_id=request.workflow_id,
        source_type=request.source_type,
        source_id=request.source_id,
        user_id=user.id,
        organization_id=user.selected_organization_id,
        scheduled_start_at=request.scheduled_start_at,
        calling_window_start=request.calling_window_start,
        calling_window_end=request.calling_window_end,
        calling_window_timezone=request.calling_window_timezone,
    )

    # Auto-start the campaign immediately after creation
    try:
        logger.info(
            f"Campaign {campaign.id} created | scheduled_start_at={request.scheduled_start_at} | "
            f"calling_window={request.calling_window_start}-{request.calling_window_end} "
            f"tz={request.calling_window_timezone}"
        )
        await campaign_runner_service.start_campaign(campaign.id)
        campaign = await db_client.get_campaign(campaign.id, user.selected_organization_id)
    except Exception as e:
        logger.warning(f"Campaign {campaign.id} created but auto-start failed: {e}")

    return _campaign_to_response(campaign, workflow_name)


@router.get("/")
async def get_campaigns(
    user: UserModel = Depends(get_user),
) -> CampaignsResponse:
    """Get campaigns for user's organization"""
    campaigns = await db_client.get_campaigns(user.selected_organization_id)

    # Get workflow names for all campaigns
    workflow_ids = list(set(c.workflow_id for c in campaigns))
    workflows = await db_client.get_workflows_by_ids(
        workflow_ids, user.selected_organization_id
    )
    workflow_map = {w.id: w.name for w in workflows}

    campaign_ids = [c.id for c in campaigns]
    try:
        connected_map = await db_client.get_connected_calls_counts(campaign_ids)
    except Exception as e:
        logger.warning(f"Failed to fetch connected call counts: {e}")
        connected_map = {}

    campaign_responses = [
        _campaign_to_response(
            c,
            workflow_map.get(c.workflow_id, "Unknown"),
            connected_calls=connected_map.get(c.id, 0),
        )
        for c in campaigns
    ]

    return CampaignsResponse(campaigns=campaign_responses)


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: int,
    user: UserModel = Depends(get_user),
) -> CampaignResponse:
    """Get campaign details"""
    campaign = await db_client.get_campaign(campaign_id, user.selected_organization_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    workflow_name = await db_client.get_workflow_name(campaign.workflow_id, user.id)
    try:
        connected_map = await db_client.get_connected_calls_counts([campaign.id])
    except Exception as e:
        logger.warning(f"Failed to fetch connected call count for campaign {campaign.id}: {e}")
        connected_map = {}

    return _campaign_to_response(
        campaign, workflow_name or "Unknown",
        connected_calls=connected_map.get(campaign.id, 0),
    )


@router.get("/{campaign_id}/analytics")
async def get_campaign_analytics(
    campaign_id: int,
    user: UserModel = Depends(get_user),
) -> CampaignAnalyticsResponse:
    """Get campaign analytics — disposition breakdown, call durations, etc."""
    try:
        data = await db_client.get_campaign_analytics(
            campaign_id, user.selected_organization_id
        )
        return CampaignAnalyticsResponse(**data)
    except ValueError:
        raise HTTPException(status_code=404, detail="Campaign not found")


@router.post("/{campaign_id}/start")
async def start_campaign(
    campaign_id: int,
    user: UserModel = Depends(get_user),
) -> CampaignResponse:
    """Start campaign execution"""
    # Check subscription allows campaigns and calls
    can_campaign = await _sub_service.check_can_create_campaign(
        user.selected_organization_id
    )
    if not can_campaign["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_campaign["reason"],
                "message": can_campaign.get("message", "Subscription limit reached"),
            },
        )

    can_call = await _sub_service.check_can_make_call(
        user.selected_organization_id
    )
    if not can_call["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_call["reason"],
                "message": can_call.get("message", "Subscription limit reached"),
            },
        )

    # Check if organization has TELEPHONY_CONFIGURATION configured
    twilio_config = await db_client.get_configuration(
        user.selected_organization_id,
        OrganizationConfigurationKey.TELEPHONY_CONFIGURATION.value,
    )

    if not twilio_config or not twilio_config.value:
        raise HTTPException(
            status_code=401,
            detail="You must configure telephony first by going to APP_URL/configure-telephony",
        )

    # Verify campaign exists and belongs to organization
    campaign = await db_client.get_campaign(campaign_id, user.selected_organization_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Start the campaign using the runner service
    try:
        await campaign_runner_service.start_campaign(campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Get updated campaign
    campaign = await db_client.get_campaign(campaign_id, user.selected_organization_id)
    workflow_name = await db_client.get_workflow_name(campaign.workflow_id, user.id)

    return _campaign_to_response(campaign, workflow_name or "Unknown")


@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: int,
    user: UserModel = Depends(get_user),
) -> CampaignResponse:
    """Pause campaign execution"""
    # Verify campaign exists and belongs to organization
    campaign = await db_client.get_campaign(campaign_id, user.selected_organization_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Pause the campaign using the runner service
    try:
        await campaign_runner_service.pause_campaign(campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Get updated campaign
    campaign = await db_client.get_campaign(campaign_id, user.selected_organization_id)
    workflow_name = await db_client.get_workflow_name(campaign.workflow_id, user.id)

    return _campaign_to_response(campaign, workflow_name or "Unknown")


@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: int,
    user: UserModel = Depends(get_user),
):
    """Delete a campaign. Cannot delete running campaigns."""
    try:
        deleted = await db_client.delete_campaign(campaign_id, user.selected_organization_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not deleted:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return {"status": "deleted"}


@router.get("/{campaign_id}/runs")
async def get_campaign_runs(
    campaign_id: int,
    user: UserModel = Depends(get_user),
) -> List[WorkflowRunResponse]:
    """Get campaign workflow runs"""
    runs = await db_client.get_campaign_runs(campaign_id, user.selected_organization_id)

    return [
        WorkflowRunResponse(
            id=run.id,
            workflow_id=run.workflow_id,
            state="completed" if run.is_completed else "running",
            created_at=run.created_at,
            completed_at=run.created_at if run.is_completed else None,
        )
        for run in runs
    ]


@router.post("/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: int,
    user: UserModel = Depends(get_user),
) -> CampaignResponse:
    """Resume a paused campaign"""
    # Check subscription allows campaigns and calls
    can_campaign = await _sub_service.check_can_create_campaign(
        user.selected_organization_id
    )
    if not can_campaign["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_campaign["reason"],
                "message": can_campaign.get("message", "Subscription limit reached"),
            },
        )

    can_call = await _sub_service.check_can_make_call(
        user.selected_organization_id
    )
    if not can_call["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_call["reason"],
                "message": can_call.get("message", "Subscription limit reached"),
            },
        )

    # Check if organization has TELEPHONY_CONFIGURATION configured
    twilio_config = await db_client.get_configuration(
        user.selected_organization_id,
        OrganizationConfigurationKey.TELEPHONY_CONFIGURATION.value,
    )

    if not twilio_config or not twilio_config.value:
        raise HTTPException(
            status_code=401,
            detail="You must configure telephony first by going to APP_URL/configure-telephony",
        )

    # Verify campaign exists and belongs to organization
    campaign = await db_client.get_campaign(campaign_id, user.selected_organization_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Resume the campaign using the runner service
    try:
        await campaign_runner_service.resume_campaign(campaign_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Get updated campaign
    campaign = await db_client.get_campaign(campaign_id, user.selected_organization_id)
    workflow_name = await db_client.get_workflow_name(campaign.workflow_id, user.id)

    return _campaign_to_response(campaign, workflow_name or "Unknown")


@router.get("/{campaign_id}/progress")
async def get_campaign_progress(
    campaign_id: int,
    user: UserModel = Depends(get_user),
) -> CampaignProgressResponse:
    """Get current campaign progress and statistics"""
    # Verify campaign exists and belongs to organization
    campaign = await db_client.get_campaign(campaign_id, user.selected_organization_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get progress from runner service
    try:
        progress = await campaign_runner_service.get_campaign_status(campaign_id)
        return CampaignProgressResponse(**progress)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class CampaignSourceDownloadResponse(BaseModel):
    download_url: str
    expires_in: int


@router.get("/{campaign_id}/source-download-url")
async def get_campaign_source_download_url(
    campaign_id: int,
    user: UserModel = Depends(get_user),
) -> CampaignSourceDownloadResponse:
    """Get presigned download URL for campaign CSV source file

    Only works for CSV source type. For Google Sheets, use the source_id directly.
    Validates that the campaign belongs to the user's organization for security.
    """
    # Verify campaign exists and belongs to organization
    campaign = await db_client.get_campaign(campaign_id, user.selected_organization_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Only generate download URL for CSV files
    if campaign.source_type != "csv":
        raise HTTPException(
            status_code=400,
            detail=f"Download URL only available for CSV sources. This campaign uses {campaign.source_type}",
        )

    # Verify the file key belongs to the user's organization
    # File key format: campaigns/{org_id}/{uuid}_{filename}.csv
    if not campaign.source_id.startswith(f"campaigns/{user.selected_organization_id}/"):
        raise HTTPException(
            status_code=403,
            detail="Access denied: Source file does not belong to your organization",
        )

    # Generate presigned download URL
    try:
        download_url = await storage_fs.aget_signed_url(
            campaign.source_id,
            expiration=3600,  # 1 hour
        )

        if not download_url:
            raise HTTPException(
                status_code=500, detail="Failed to generate download URL"
            )

        return CampaignSourceDownloadResponse(
            download_url=download_url, expires_in=3600
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate download URL: {str(e)}"
        )


@router.patch("/{campaign_id}/schedule")
async def update_campaign_schedule(
    campaign_id: int,
    request: UpdateScheduleRequest,
    user: UserModel = Depends(get_user),
) -> CampaignResponse:
    """Update scheduling settings for a campaign.

    Only allowed when the campaign is in 'created' or 'scheduled' state.
    """
    campaign = await db_client.get_campaign(campaign_id, user.selected_organization_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.state not in ("created", "scheduled"):
        raise HTTPException(
            status_code=400,
            detail="Schedule can only be modified for campaigns in 'created' or 'scheduled' state",
        )

    # Validate calling window: both start and end must be provided together
    window_start = request.calling_window_start
    window_end = request.calling_window_end
    if (window_start is not None) != (window_end is not None):
        raise HTTPException(
            status_code=400,
            detail="Both calling_window_start and calling_window_end must be provided together",
        )

    update_kwargs = {}
    if request.scheduled_start_at is not None:
        update_kwargs["scheduled_start_at"] = request.scheduled_start_at
    if window_start is not None:
        update_kwargs["calling_window_start"] = window_start
        update_kwargs["calling_window_end"] = window_end
    if request.calling_window_timezone is not None:
        update_kwargs["calling_window_timezone"] = request.calling_window_timezone

    if update_kwargs:
        await db_client.update_campaign(campaign_id=campaign_id, **update_kwargs)

    campaign = await db_client.get_campaign(campaign_id, user.selected_organization_id)
    workflow_name = await db_client.get_workflow_name(campaign.workflow_id, user.id)

    return _campaign_to_response(campaign, workflow_name or "Unknown")


@router.get("/{campaign_id}/contacts")
async def get_campaign_contacts(
    campaign_id: int,
    user: UserModel = Depends(get_user),
    status: Optional[str] = Query(None, description="Filter by status: queued, processed, failed"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> CampaignContactsResponse:
    """Get per-contact tracking data for a campaign.

    Returns enriched contact data by joining queued_runs with their linked workflow_runs.
    Supports pagination and optional status filtering.
    """
    try:
        contacts, total = await db_client.get_campaign_contacts(
            campaign_id=campaign_id,
            organization_id=user.selected_organization_id,
            status_filter=status,
            offset=offset,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return CampaignContactsResponse(
        contacts=[CampaignContactResponse(**c) for c in contacts],
        total=total,
        offset=offset,
        limit=limit,
    )
