import asyncio
import json
import re
import uuid
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from httpx import HTTPStatusError
from loguru import logger
from pydantic import BaseModel, ValidationError

from api.db import db_client
from api.db.models import UserModel
from api.schemas.workflow import WorkflowRunResponseSchema
from api.services.auth.depends import get_user
from api.services.mps_service_key_client import mps_service_key_client
from api.services.security.rate_limiter import limiter, RateLimitTiers
from api.services.workflow.dto import ReactFlowDTO, EdgeConditionError
from api.services.workflow.errors import ItemKind, WorkflowError
from api.services.subscription.subscription_service import SubscriptionService
from api.services.workflow.ai_suggest import suggest_edge_condition, suggest_node_prompt, improve_node_prompt, improve_extraction_prompt, suggest_extraction_variables, suggest_field, suggest_database_query, suggest_action_content, ai_edit_workflow, improve_agent_response
from api.services.workflow.workflow import WorkflowGraph
from api.services.workflow.workflow_generator import generate_workflow_local

router = APIRouter(prefix="/workflow")

# Subscription service for limit checks
_sub_service = SubscriptionService()


class ValidateWorkflowResponse(BaseModel):
    is_valid: bool
    errors: list[WorkflowError]


class ValidateWorkflowRequest(BaseModel):
    # Optional live (unsaved) flow from the editor. When provided, validation
    # runs against this instead of the persisted copy so the editor's error
    # indicator reflects in-progress edits without requiring a save.
    workflow_definition: Optional[dict] = None


class WorkflowResponse(BaseModel):
    id: int
    # Opaque, unguessable token used in user-facing URLs instead of the
    # enumerable integer primary key.
    public_id: str | None = None
    name: str
    status: str
    created_at: datetime
    workflow_definition: dict
    current_definition_id: int | None
    template_context_variables: dict | None = None
    call_disposition_codes: dict | None = None
    total_runs: int | None = None
    workflow_configurations: dict | None = None


class WorkflowTemplateResponse(BaseModel):
    id: int
    template_name: str
    template_description: str
    template_json: dict
    created_at: datetime


class CreateWorkflowRequest(BaseModel):
    name: str
    workflow_definition: dict
    workflow_configurations: dict | None = None


class DuplicateTemplateRequest(BaseModel):
    template_id: int
    workflow_name: str


class UpdateWorkflowRequest(BaseModel):
    name: str
    workflow_definition: dict | None = None
    template_context_variables: dict | None = None
    workflow_configurations: dict | None = None


class UpdateWorkflowStatusRequest(BaseModel):
    status: str  # "active" or "archived"


class CreateWorkflowRunRequest(BaseModel):
    mode: str
    name: str


class CreateWorkflowRunResponse(BaseModel):
    id: int
    workflow_id: int
    name: str
    mode: str
    created_at: datetime
    definition_id: int
    initial_context: dict | None = None


class CreateWorkflowTemplateRequest(BaseModel):
    call_type: Literal["INBOUND", "OUTBOUND", "WEBSITE", "MEETING"]
    use_case: str
    activity_description: str
    website_url: Optional[str] = None  # Optional: URL to scrape for business context
    knowledge_base_content: Optional[str] = None  # Optional: Custom KB content (editable extracted text)
    knowledge_base_files: Optional[List[int]] = None  # Optional: Up to 3 KB file IDs to attach


class ExtractWebsiteRequest(BaseModel):
    website_url: str
    deep_crawl: bool = True  # If True, crawl multiple pages


class ExtractWebsiteResponse(BaseModel):
    success: bool
    content: Optional[str] = None
    error: Optional[str] = None
    source: str = "website"
    pages_crawled: int = 0
    message: Optional[str] = None


@router.post("/extract-website")
@limiter.limit(RateLimitTiers.LOW)  # Rate limit for external requests
async def extract_website_content(
    request: Request,
    extract_request: ExtractWebsiteRequest,
    user: UserModel = Depends(get_user),
) -> ExtractWebsiteResponse:
    """
    Extract content from a website URL for knowledge base preview.
    
    This endpoint performs deep crawling of the website to extract content
    from multiple pages (homepage, about, services, menu, etc.) to build
    a comprehensive knowledge base for the voice agent.
    
    Args:
        website_url: The URL to crawl
        deep_crawl: If True (default), crawl up to 10 important pages
    """
    from api.services.workflow.workflow_generator import fetch_website_content
    
    try:
        logger.info(f"Starting website extraction for: {extract_request.website_url} (deep_crawl={extract_request.deep_crawl})")
        
        content = await fetch_website_content(
            extract_request.website_url, 
            deep_crawl=extract_request.deep_crawl
        )
        
        if content:
            # Count pages from content header
            pages_count = content.count("--- PAGE:")
            if pages_count == 0:
                pages_count = 1
            
            return ExtractWebsiteResponse(
                success=True,
                content=content,
                source="deep_crawl" if extract_request.deep_crawl else "single_page",
                pages_crawled=pages_count,
                message=f"Successfully extracted content from {pages_count} page(s)"
            )
        else:
            return ExtractWebsiteResponse(
                success=False,
                error="Could not extract content from the website. Please check the URL and try again.",
                source="website",
                pages_crawled=0
            )
    except Exception as e:
        logger.error(f"Error extracting website content: {e}")
        return ExtractWebsiteResponse(
            success=False,
            error=f"Failed to extract content: {str(e)}",
            source="website",
            pages_crawled=0
        )


@router.post("/{workflow_id}/validate")
@limiter.limit(RateLimitTiers.STANDARD)
async def validate_workflow(
    request: Request,
    workflow_id: int,
    body: Optional[ValidateWorkflowRequest] = Body(default=None),
    user: UserModel = Depends(get_user),
) -> ValidateWorkflowResponse:
    """
    Validate all nodes in a workflow to ensure they have required fields.

    Args:
        workflow_id: The ID of the workflow to validate
        body: Optional live (unsaved) workflow definition to validate instead
            of the persisted copy
        user: The authenticated user

    Returns:
        Object indicating if workflow is valid and any invalid nodes/edges
    """
    workflow = await db_client.get_workflow(
        workflow_id, organization_id=user.selected_organization_id
    )

    if workflow is None:
        raise HTTPException(
            status_code=404, detail=f"Workflow with id {workflow_id} not found"
        )

    errors: list[WorkflowError] = []

    # Prefer the live (unsaved) definition supplied by the editor so the error
    # indicator updates as the user fixes issues, without needing a save. Fall
    # back to the persisted definition when no body is sent.
    if body is not None and body.workflow_definition is not None:
        workflow_definition = body.workflow_definition
    else:
        workflow_definition = workflow.workflow_definition_with_fallback

    # ----------- DTO Validation ------------
    dto: Optional[ReactFlowDTO] = None

    try:
        dto = ReactFlowDTO.model_validate(workflow_definition)
        logger.info(f"DTO Validation PASSED for workflow {workflow_id}")
    except ValidationError as exc:
        logger.error(f"DTO Validation FAILED for workflow {workflow_id}: {exc.errors()}")
        errors.extend(_transform_schema_errors(exc, workflow_definition))

    # ----------- Edge Condition Validation ------------
    if dto:
        edge_condition_errors = dto.validate_edge_conditions()
        for edge_err in edge_condition_errors:
            errors.append(
                WorkflowError(
                    kind=ItemKind.edge,
                    id=edge_err.edge_id,
                    field="condition",
                    message=edge_err.message,
                )
            )
        if edge_condition_errors:
            logger.warning(f"Edge Condition Validation: {len(edge_condition_errors)} edges missing conditions")

    # ----------- Graph Validation if DTO is valid ------------
    try:
        if dto:
            WorkflowGraph(dto)
            logger.info(f"Graph Validation PASSED for workflow {workflow_id}")
    except ValueError as e:
        logger.error(f"Graph Validation FAILED for workflow {workflow_id}: {e.args[0]}")
        errors.extend(e.args[0])
    
    logger.info(f"Workflow {workflow_id} validation complete. Errors: {len(errors)}")

    if errors:
        raise HTTPException(
            status_code=422,
            detail=ValidateWorkflowResponse(is_valid=False, errors=errors).model_dump(),
        )

    return ValidateWorkflowResponse(is_valid=True, errors=[])


def _transform_schema_errors(
    exc: ValidationError, workflow_definition: dict
) -> list[WorkflowError]:
    out: list[WorkflowError] = []

    for err in exc.errors():
        loc = err["loc"]
        idx = workflow_definition[loc[0]][loc[1]]["id"]

        kind: ItemKind = ItemKind.node if loc[0] == "nodes" else ItemKind.edge

        raw_field = ".".join(str(p) for p in err["loc"][2:]) or None
        if raw_field and raw_field.startswith("data."):
            raw_field = raw_field[5:]

        out.append(
            WorkflowError(
                kind=kind,
                id=idx,
                field=raw_field,
                message=err["msg"].capitalize(),
            )
        )
    return out


@router.post("/create/definition")
@limiter.limit(RateLimitTiers.STANDARD)
async def create_workflow(
    request: Request,
    create_request: CreateWorkflowRequest,
    user: UserModel = Depends(get_user),
) -> WorkflowResponse:
    """
    Create a new workflow from the client

    Args:
        request: The create workflow request
        user: The user to create the workflow for
    """
    # Check subscription allows creating workflows
    can_create = await _sub_service.check_can_create_workflow(user.selected_organization_id)
    if not can_create["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_create["reason"],
                "message": can_create.get("message", "Subscription limit reached"),
            },
        )

    workflow = await db_client.create_workflow(
        create_request.name,
        create_request.workflow_definition,
        user.id,
        user.selected_organization_id,
        workflow_configurations=create_request.workflow_configurations,
    )
    return {
        "id": workflow.id,
        "public_id": workflow.public_id,
        "name": workflow.name,
        "status": workflow.status,
        "created_at": workflow.created_at,
        "workflow_definition": workflow.workflow_definition_with_fallback,
        "current_definition_id": workflow.current_definition_id,
        "template_context_variables": workflow.template_context_variables,
        "call_disposition_codes": workflow.call_disposition_codes,
        "workflow_configurations": workflow.workflow_configurations,
    }


async def _run_background_generation(
    workflow_id: int,
    call_type: str,
    use_case: str,
    activity_description: str,
    user_id: int,
    org_id: int,
    placeholder_name: str,
    website_url: Optional[str] = None,
    knowledge_base_content: Optional[str] = None,
    knowledge_base_files: Optional[List[int]] = None,
    style_recordings: Optional[list[tuple[str, bytes, str]]] = None,
):
    """Background task to generate a workflow using AI."""
    try:
        logger.info(f"🚀 Background generation started for workflow {workflow_id}")

        # Optional: distill a style profile from uploaded call recordings and
        # fold it into the activity description so the generator mimics the
        # human agent's tone, pacing, and signature phrases.
        enriched_activity_description = activity_description
        if style_recordings:
            try:
                from api.services.workflow.style_extractor import extract_style_from_recordings
                style_profile = await extract_style_from_recordings(
                    style_recordings, user_id=user_id,
                )
                if style_profile:
                    enriched_activity_description = (
                        f"{activity_description}\n\n{style_profile}"
                    )
                    logger.info(
                        f"[Generation] Appended style profile to activity description "
                        f"for workflow {workflow_id}"
                    )
            except Exception as style_err:
                # Style extraction is best-effort — never fail workflow creation
                logger.warning(
                    f"[Generation] Style extraction failed (continuing without): {style_err}"
                )

        workflow_data = await generate_workflow_local(
            call_type=call_type,
            use_case=use_case,
            activity_description=enriched_activity_description,
            user_id=user_id,
            organization_id=org_id,
            website_url=website_url,
            knowledge_base_content=knowledge_base_content,
            knowledge_base_files=knowledge_base_files,
            workflow_id=workflow_id,
        )
        
        generated_def = workflow_data.get("workflow_definition", {})
        
        await db_client.update_workflow(
            workflow_id=workflow_id,
            name=placeholder_name,
            workflow_definition=generated_def,
            template_context_variables=None,
            workflow_configurations={
                "call_type": call_type,
                "tts_provider": "cartesia",
                "tts_voice_id": "f786b574-daa5-4673-aa0c-cbe3e8534c02",
                "tts_voice_name": "Katie - Female, Stable, Agent-Ready",
                "tts_cartesia_model": "sonic-3.5",
                "voice_mode": "standard",
                "workflow_language": "English",
                "max_call_duration": 600,
                "max_user_idle_timeout": 18.0,
                "max_cumulative_silence": 30.0,
                "guardrails_enabled": True,
                "redact_pii": True,
                "_generating": False,
            },
            organization_id=org_id,
        )
        
        logger.info(f"✅ Background generation complete for workflow {workflow_id}: {placeholder_name}")
        
    except Exception as e:
        logger.error(f"❌ Background generation failed for workflow {workflow_id}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        try:
            await db_client.update_workflow(
                workflow_id=workflow_id,
                name=f"⚠ {placeholder_name} (Failed)",
                workflow_definition=None,
                template_context_variables=None,
                workflow_configurations={"call_type": call_type, "_generating": False, "_error": str(e)},
                organization_id=org_id,
            )
        except Exception:
            pass


@router.post("/create/template")
@limiter.limit(RateLimitTiers.LOW)
async def create_workflow_from_template(
    request: Request,
    # JSON payload must be sent as a string field named `data` inside multipart
    # form-data so we can also accept optional audio recordings on the same call.
    # Callers that have no recordings can still POST `multipart/form-data` with
    # just the `data` field (FormData is the browser default when sending files).
    data: str = Form(...),
    style_recordings: list[UploadFile] = File(default_factory=list),
    user: UserModel = Depends(get_user),
) -> WorkflowResponse:
    """
    Create a new workflow from a natural language template request.
    Returns immediately with a placeholder, generates in background.

    Optionally accepts `style_recordings` — audio files of a human agent
    handling real calls. When present, we transcribe them and inject the
    extracted style profile (tone, pacing, signature phrases) into the
    generation prompt so the resulting agent mimics that person's style.
    """
    # Parse the JSON payload out of the form field.
    try:
        payload_dict = json.loads(data) if data else {}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in `data`: {e}")
    try:
        template_request = CreateWorkflowTemplateRequest(**payload_dict)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    # Check subscription allows creating workflows
    can_create = await _sub_service.check_can_create_workflow(user.selected_organization_id)
    if not can_create["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_create["reason"],
                "message": can_create.get("message", "Subscription limit reached"),
            },
        )

    # Validate + read uploaded recordings (if any) before kicking off the bg task.
    recordings_payload: list[tuple[str, bytes, str]] = []
    total_size = 0
    for f in style_recordings or []:
        content_type = f.content_type or "audio/mpeg"
        if content_type not in ALLOWED_AUDIO_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported recording type: {content_type} for {f.filename}",
            )
        blob = await f.read()
        if len(blob) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Recording {f.filename} exceeds 25 MB limit",
            )
        total_size += len(blob)
        if total_size > MAX_TOTAL_SIZE:
            raise HTTPException(
                status_code=400,
                detail="Total recording upload size exceeds 100 MB limit",
            )
        recordings_payload.append((f.filename or "audio", blob, content_type))
    if len(recordings_payload) > MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_FILES} recordings allowed",
        )

    # Build placeholder name
    placeholder_name = template_request.use_case or "New Agent"
    if template_request.website_url:
        from urllib.parse import urlparse
        parsed = urlparse(template_request.website_url)
        domain = parsed.netloc.replace('www.', '')
        placeholder_name = f"Agent for {domain}"

    if template_request.call_type == "MEETING":
        placeholder_def = {
            "nodes": [
                {"id": "trigger-1", "type": "meetingTrigger", "position": {"x": 400, "y": 100},
                 "data": {"name": "Wake Word Trigger", "trigger_config": {"mode": "wake_word", "wake_words": ["hey agent"], "cooldown_seconds": 2},
                          "response_prompt": "Respond helpfully and concisely to the question based on the meeting context."},
                 "measured": {"width": 300, "height": 100}},
                {"id": "agent-1", "type": "agentNode", "position": {"x": 400, "y": 350},
                 "data": {"name": "Meeting Assistant",
                          "prompt": "You are a helpful meeting assistant. Answer questions based on the meeting context and knowledge base. Be concise and direct — do not introduce yourself or use call-style greetings.",
                          "is_static": False, "allow_interrupt": True, "add_global_prompt": True},
                 "measured": {"width": 300, "height": 100}},
                {"id": "summary-1", "type": "meetingSummary", "position": {"x": 400, "y": 600},
                 "data": {"name": "Meeting Summary", "summary_config": {"mode": "end_of_meeting", "include_action_items": True, "include_decisions": True, "include_key_points": True},
                          "output_format": "markdown"},
                 "measured": {"width": 300, "height": 100}},
            ],
            "edges": [
                {"animated": True, "type": "custom", "source": "trigger-1", "target": "agent-1", "id": "edge-trigger-agent", "data": {"condition": "", "label": ""}},
                {"animated": True, "type": "custom", "source": "agent-1", "target": "summary-1", "id": "edge-agent-summary", "data": {"condition": "", "label": ""}},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1}
        }
    else:
        placeholder_def = {
            "nodes": [
                {"id": "start-1", "type": "startCall", "position": {"x": 400, "y": 100},
                 "data": {"prompt": "Agent is being built...", "name": "Start Call", "is_start": True, "is_static": False, "allow_interrupt": False},
                 "measured": {"width": 300, "height": 100}},
                {"id": "end-1", "type": "endCall", "position": {"x": 400, "y": 400},
                 "data": {"prompt": "Goodbye!", "name": "End Call", "is_end": True, "is_static": False, "allow_interrupt": False},
                 "measured": {"width": 300, "height": 100}}
            ],
            "edges": [{"animated": True, "type": "custom", "source": "start-1", "target": "end-1", "id": "edge-start-end", "data": {"condition": "", "label": ""}}],
            "viewport": {"x": 0, "y": 0, "zoom": 1}
        }

    try:
        workflow = await db_client.create_workflow(
            name=placeholder_name,
            workflow_definition=placeholder_def,
            user_id=user.id,
            organization_id=user.selected_organization_id,
            workflow_configurations={"call_type": template_request.call_type, "_generating": True},
        )
    except Exception as e:
        logger.error(f"Failed to create placeholder workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Copy all values BEFORE the request ends (avoid garbage collection)
    wf_id = workflow.id
    uid = user.id
    oid = user.selected_organization_id
    ct = template_request.call_type
    uc = template_request.use_case
    ad = template_request.activity_description
    wu = template_request.website_url
    kbc = template_request.knowledge_base_content
    kbf = template_request.knowledge_base_files
    pn = placeholder_name

    asyncio.ensure_future(_run_background_generation(
        workflow_id=wf_id, call_type=ct, use_case=uc,
        activity_description=ad, user_id=uid, org_id=oid,
        placeholder_name=pn, website_url=wu,
        knowledge_base_content=kbc, knowledge_base_files=kbf,
        style_recordings=recordings_payload or None,
    ))

    logger.info(
        f"📋 Created placeholder workflow {wf_id}, background generation launched "
        f"(style_recordings={len(recordings_payload)})"
    )
    
    return {
        "id": workflow.id,
        "name": placeholder_name,
        "status": "active",
        "created_at": workflow.created_at,
        "workflow_definition": placeholder_def,
        "current_definition_id": workflow.current_definition_id,
        "template_context_variables": workflow.template_context_variables,
        "call_disposition_codes": workflow.call_disposition_codes,
        "public_id": workflow.public_id,
        "workflow_configurations": {"call_type": ct, "_generating": True},
    }


class CreateIndustryTemplateRequest(BaseModel):
    industry: str
    business_name: str
    call_type: Literal["INBOUND", "OUTBOUND", "WEBSITE", "MEETING"]
    business_description: str
    reference_links: Optional[list[str]] = None
    business_info: Optional[dict[str, str]] = None


async def _run_industry_crew_background(
    workflow_id: int,
    industry: str,
    business_name: str,
    business_description: str,
    call_type: str,
    user_id: int,
    org_id: int,
    reference_links: Optional[list[str]] = None,
    style_recordings: Optional[list[tuple[str, bytes, str]]] = None,
    business_info: Optional[dict[str, str]] = None,
):
    """Background task to scrape reference links, then run the CrewAI industry crew."""
    try:
        from api.services.workflow.industry_crew import run_industry_crew
        from api.services.workflow.link_scraper import scrape_links

        logger.info(f"[IndustryTemplate] Background crew started for workflow {workflow_id}")

        scraped_context = ""
        if reference_links:
            logger.info(
                f"[IndustryTemplate] Scraping {len(reference_links)} reference link(s) "
                f"for workflow {workflow_id}: {reference_links}"
            )
            scraped_context = await scrape_links(reference_links)
            if scraped_context:
                logger.info(
                    f"[IndustryTemplate] Scraped {len(scraped_context)} chars of "
                    f"context for workflow {workflow_id}"
                )
            else:
                logger.warning(
                    f"[IndustryTemplate] Reference links provided but scraping "
                    f"returned no usable content for workflow {workflow_id}. "
                    f"The crew will run with description-only context."
                )
        else:
            logger.info(
                f"[IndustryTemplate] No reference links provided for workflow {workflow_id} — "
                f"crew will run with description-only context."
            )

        enriched_description = business_description
        if style_recordings:
            try:
                from api.services.workflow.style_extractor import extract_style_from_recordings
                style_profile = await extract_style_from_recordings(
                    style_recordings, user_id=user_id,
                )
                if style_profile:
                    enriched_description = (
                        f"{business_description}\n\n{style_profile}"
                    )
                    logger.info(
                        f"[IndustryTemplate] Appended style profile to description "
                        f"for workflow {workflow_id}"
                    )
            except Exception as style_err:
                logger.warning(
                    f"[IndustryTemplate] Style extraction failed "
                    f"(continuing without): {style_err}"
                )

        result = await run_industry_crew(
            industry_key=industry,
            business_name=business_name,
            business_description=enriched_description,
            call_type=call_type,
            user_id=user_id,
            scraped_link_context=scraped_context or None,
            business_info=business_info,
        )

        generated_def = result.get("workflow_definition", {})

        wf_config: dict = {
            "call_type": call_type,
            "tts_provider": "cartesia",
            "tts_voice_id": "f786b574-daa5-4673-aa0c-cbe3e8534c02",
            "tts_voice_name": "Katie - Female, Stable, Agent-Ready",
            "tts_cartesia_model": "sonic-3.5",
            "voice_mode": "standard",
            "workflow_language": "English",
            "max_call_duration": 600,
            "max_user_idle_timeout": 18.0,
            "max_cumulative_silence": 30.0,
            "guardrails_enabled": True,
            "redact_pii": True,
            "_generating": False,
        }
        if business_info:
            wf_config["business_info"] = business_info

        await db_client.update_workflow(
            workflow_id=workflow_id,
            name=business_name,
            workflow_definition=generated_def,
            template_context_variables=None,
            workflow_configurations=wf_config,
            organization_id=org_id,
        )

        # Persist scraped reference content as a workflow-scoped KB document so
        # the runtime voice agent can actually retrieve it via search_knowledge_base.
        # Without this step the architect's `kb_enabled=true` flag on nodes is
        # useless because there's no content indexed for retrieval.
        if scraped_context:
            try:
                from api.services.workflow.workflow_generator import (
                    _save_kb_content_for_organization,
                )
                website_url = reference_links[0] if reference_links else None
                logger.info(
                    f"[IndustryTemplate] Saving {len(scraped_context)} chars of "
                    f"scraped content as KB document for workflow {workflow_id}"
                )
                await _save_kb_content_for_organization(
                    organization_id=org_id,
                    user_id=user_id,
                    use_case=business_name,
                    website_url=website_url,
                    knowledge_base_content=scraped_context,
                    workflow_id=workflow_id,
                )
                logger.info(
                    f"[IndustryTemplate] KB document persisted for workflow {workflow_id}"
                )
            except Exception as kb_err:
                logger.error(
                    f"[IndustryTemplate] Failed to persist KB doc for "
                    f"workflow {workflow_id} (non-fatal): {kb_err}"
                )

        logger.info(f"[IndustryTemplate] Complete for workflow {workflow_id}: {business_name}")

        # Auto-Rehearsal: enqueue a background stress-test so the workflow is
        # validated against diverse caller personas before the user's first
        # real call. Idempotent per workflow so the user can manually re-queue
        # without piling up jobs. Non-blocking — failures never affect the
        # generation result.
        try:
            from api.tasks.arq import enqueue_job as _enqueue_job
            from api.tasks.function_names import FunctionNames as _FN
            await _enqueue_job(
                _FN.RUN_WORKFLOW_REHEARSAL,
                workflow_id,
                _job_id=f"rehearsal:{workflow_id}",
            )
            logger.info(f"[IndustryTemplate] Queued auto-rehearsal for workflow {workflow_id}")
        except Exception as _re_err:
            logger.warning(f"[IndustryTemplate] Could not queue rehearsal (non-fatal): {_re_err}")

    except Exception as e:
        logger.error(f"[IndustryTemplate] Failed for workflow {workflow_id}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        try:
            # Fall back to basic template
            from api.services.workflow.workflow_generator import _create_basic_template

            fallback = _create_basic_template(call_type, business_name, business_description)
            await db_client.update_workflow(
                workflow_id=workflow_id,
                name=fallback["name"],
                workflow_definition=fallback["workflow_definition"],
                template_context_variables=None,
                workflow_configurations={
                    "call_type": call_type,
                    "_generating": False,
                    "_error": str(e),
                },
                organization_id=org_id,
            )
        except Exception:
            pass


@router.post("/create/industry-template")
@limiter.limit(RateLimitTiers.LOW)
async def create_industry_template_workflow(
    request: Request,
    data: str = Form(...),
    style_recordings: list[UploadFile] = File(default_factory=list),
    user: UserModel = Depends(get_user),
) -> WorkflowResponse:
    """
    Create a specialized workflow for a specific industry.
    Returns immediately with a placeholder; CrewAI generates the full workflow in background.

    Accepts multipart form-data with:
      - data: JSON-encoded CreateIndustryTemplateRequest
      - style_recordings: optional audio files for style-pattern extraction
    """
    from api.services.workflow.industry_templates import INDUSTRY_REGISTRY

    try:
        payload_dict = json.loads(data) if data else {}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in `data`: {e}")
    try:
        body = CreateIndustryTemplateRequest(**payload_dict)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    if body.industry not in INDUSTRY_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown industry: {body.industry}. Valid: {list(INDUSTRY_REGISTRY.keys())}")

    can_create = await _sub_service.check_can_create_workflow(user.selected_organization_id)
    if not can_create["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_create["reason"],
                "message": can_create.get("message", "Subscription limit reached"),
            },
        )

    # Validate + buffer recordings (if any) before starting the background task.
    recordings_payload: list[tuple[str, bytes, str]] = []
    total_size = 0
    for f in style_recordings or []:
        content_type = f.content_type or "audio/mpeg"
        if content_type not in ALLOWED_AUDIO_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported recording type: {content_type} for {f.filename}",
            )
        blob = await f.read()
        if len(blob) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Recording {f.filename} exceeds 25 MB limit",
            )
        total_size += len(blob)
        if total_size > MAX_TOTAL_SIZE:
            raise HTTPException(
                status_code=400,
                detail="Total recording upload size exceeds 100 MB limit",
            )
        recordings_payload.append((f.filename or "audio", blob, content_type))
    if len(recordings_payload) > MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_FILES} recordings allowed",
        )

    industry_info = INDUSTRY_REGISTRY[body.industry]
    placeholder_name = body.business_name

    if body.call_type == "MEETING":
        placeholder_def = {
            "nodes": [
                {"id": "trigger-1", "type": "meetingTrigger", "position": {"x": 400, "y": 100},
                 "data": {"name": "Wake Word Trigger", "trigger_config": {"mode": "wake_word", "wake_words": ["hey agent"], "cooldown_seconds": 2},
                          "response_prompt": "Respond helpfully and concisely to the question based on the meeting context."},
                 "measured": {"width": 300, "height": 100}},
                {"id": "agent-1", "type": "agentNode", "position": {"x": 400, "y": 350},
                 "data": {"name": "Meeting Assistant",
                          "prompt": "You are a helpful meeting assistant. Answer questions based on the meeting context and knowledge base. Be concise and direct — do not introduce yourself or use call-style greetings.",
                          "is_static": False, "allow_interrupt": True, "add_global_prompt": True},
                 "measured": {"width": 300, "height": 100}},
                {"id": "summary-1", "type": "meetingSummary", "position": {"x": 400, "y": 600},
                 "data": {"name": "Meeting Summary", "summary_config": {"mode": "end_of_meeting", "include_action_items": True, "include_decisions": True, "include_key_points": True},
                          "output_format": "markdown"},
                 "measured": {"width": 300, "height": 100}},
            ],
            "edges": [
                {"animated": True, "type": "custom", "source": "trigger-1", "target": "agent-1", "id": "edge-trigger-agent", "data": {"condition": "", "label": ""}},
                {"animated": True, "type": "custom", "source": "agent-1", "target": "summary-1", "id": "edge-agent-summary", "data": {"condition": "", "label": ""}},
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1}
        }
    else:
        placeholder_def = {
            "nodes": [
                {"id": "start-1", "type": "startCall", "position": {"x": 400, "y": 100},
                 "data": {"prompt": "Your specialized agent is being built...", "name": "Start Call", "is_start": True, "is_static": False, "allow_interrupt": False},
                 "measured": {"width": 300, "height": 100}},
                {"id": "end-1", "type": "endCall", "position": {"x": 400, "y": 400},
                 "data": {"prompt": "Goodbye!", "name": "End Call", "is_end": True, "is_static": False, "allow_interrupt": False},
                 "measured": {"width": 300, "height": 100}}
            ],
            "edges": [{"animated": True, "type": "custom", "source": "start-1", "target": "end-1", "id": "edge-start-end", "data": {"condition": "", "label": ""}}],
            "viewport": {"x": 0, "y": 0, "zoom": 1}
        }

    try:
        workflow = await db_client.create_workflow(
            name=placeholder_name,
            workflow_definition=placeholder_def,
            user_id=user.id,
            organization_id=user.selected_organization_id,
            workflow_configurations={"call_type": body.call_type, "_generating": True},
        )
    except Exception as e:
        logger.error(f"Failed to create industry template workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    wf_id = workflow.id
    uid = user.id
    oid = user.selected_organization_id

    asyncio.ensure_future(_run_industry_crew_background(
        workflow_id=wf_id,
        industry=body.industry,
        business_name=body.business_name,
        business_description=body.business_description,
        call_type=body.call_type,
        user_id=uid,
        org_id=oid,
        reference_links=body.reference_links,
        style_recordings=recordings_payload or None,
        business_info=body.business_info,
    ))

    logger.info(
        f"[IndustryTemplate] Created placeholder {wf_id}, crew launched in background "
        f"(style_recordings={len(recordings_payload)})"
    )

    return {
        "id": workflow.id,
        "name": placeholder_name,
        "status": "active",
        "created_at": workflow.created_at,
        "workflow_definition": placeholder_def,
        "current_definition_id": workflow.current_definition_id,
        "template_context_variables": workflow.template_context_variables,
        "call_disposition_codes": workflow.call_disposition_codes,
        "public_id": workflow.public_id,
        "workflow_configurations": {"call_type": body.call_type, "_generating": True},
    }


async def _run_clone_crew_background(
    workflow_id: int,
    audio_files: list[tuple[str, bytes, str]],
    business_name: str,
    call_type: str,
    org_id: int,
):
    """Background task: transcribe audio files, run cloning crew, update workflow."""
    try:
        from api.services.workflow.audio_transcriber import transcribe_multiple
        from api.services.workflow.voice_clone_crew import run_voice_clone_crew

        logger.info(f"[VoiceClone] Background task started for workflow {workflow_id} ({len(audio_files)} files)")

        transcripts = await transcribe_multiple(audio_files)
        valid_transcripts = [t for t in transcripts if t]

        if not valid_transcripts:
            logger.error(f"[VoiceClone] All transcriptions failed for workflow {workflow_id}")
            from api.services.workflow.workflow_generator import _create_basic_template
            fallback = _create_basic_template(call_type, business_name, "Voice agent")
            await db_client.update_workflow(
                workflow_id=workflow_id,
                name=f"{business_name} (transcription failed)",
                workflow_definition=fallback["workflow_definition"],
                template_context_variables=None,
                workflow_configurations={"call_type": call_type, "_generating": False},
                organization_id=org_id,
            )
            return

        result = await run_voice_clone_crew(
            transcripts=valid_transcripts,
            business_name=business_name,
            call_type=call_type,
        )

        await db_client.update_workflow(
            workflow_id=workflow_id,
            name=business_name,
            workflow_definition=result.get("workflow_definition", {}),
            template_context_variables=None,
            workflow_configurations={
                "call_type": call_type,
                "tts_provider": "cartesia",
                "tts_voice_id": "f786b574-daa5-4673-aa0c-cbe3e8534c02",
                "tts_voice_name": "Katie - Female, Stable, Agent-Ready",
                "tts_cartesia_model": "sonic-3.5",
                "voice_mode": "standard",
                "workflow_language": "English",
                "max_call_duration": 600,
                "max_user_idle_timeout": 18.0,
                "max_cumulative_silence": 30.0,
                "_generating": False,
            },
            organization_id=org_id,
        )

        logger.info(f"[VoiceClone] Complete for workflow {workflow_id}")

    except Exception as e:
        logger.error(f"[VoiceClone] Failed for workflow {workflow_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            from api.services.workflow.workflow_generator import _create_basic_template
            fallback = _create_basic_template(call_type, business_name, "Voice agent")
            await db_client.update_workflow(
                workflow_id=workflow_id,
                name=business_name,
                workflow_definition=fallback["workflow_definition"],
                template_context_variables=None,
                workflow_configurations={"call_type": call_type, "_generating": False},
                organization_id=org_id,
            )
        except Exception:
            pass


ALLOWED_AUDIO_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/wave",
    "audio/mp4", "audio/m4a", "audio/x-m4a", "audio/webm", "audio/ogg",
    "audio/flac", "video/webm",
}
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB
MAX_TOTAL_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_FILES = 10


@router.post("/create/clone-from-calls")
@limiter.limit(RateLimitTiers.LOW)
async def create_clone_from_calls(
    request: Request,
    files: list[UploadFile] = File(...),
    business_name: str = Form("My Business"),
    call_type: str = Form("INBOUND"),
    user: UserModel = Depends(get_user),
) -> WorkflowResponse:
    """
    Clone a voice agent from uploaded call recordings.
    Accepts 1-10 audio files; transcribes and analyzes them in background.
    """
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_FILES} files allowed")
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="At least one audio file is required")

    can_create = await _sub_service.check_can_create_workflow(user.selected_organization_id)
    if not can_create["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_create["reason"],
                "message": can_create.get("message", "Subscription limit reached"),
            },
        )

    audio_data: list[tuple[str, bytes, str]] = []
    total_size = 0
    for f in files:
        content_type = f.content_type or "audio/mpeg"
        if content_type not in ALLOWED_AUDIO_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type} for {f.filename}")
        data = await f.read()
        if len(data) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"File {f.filename} exceeds 25 MB limit")
        total_size += len(data)
        if total_size > MAX_TOTAL_SIZE:
            raise HTTPException(status_code=400, detail="Total upload size exceeds 100 MB limit")
        audio_data.append((f.filename or "audio", data, content_type))

    placeholder_name = business_name
    placeholder_def = {
        "nodes": [
            {"id": "start-1", "type": "startCall", "position": {"x": 400, "y": 100},
             "data": {"prompt": "Your cloned agent is being built from recordings...", "name": "Start Call",
                      "is_start": True, "is_static": False, "allow_interrupt": False},
             "measured": {"width": 300, "height": 100}},
            {"id": "end-1", "type": "endCall", "position": {"x": 400, "y": 400},
             "data": {"prompt": "Goodbye!", "name": "End Call", "is_end": True,
                      "is_static": False, "allow_interrupt": False},
             "measured": {"width": 300, "height": 100}},
        ],
        "edges": [{"animated": True, "type": "custom", "source": "start-1", "target": "end-1",
                    "id": "edge-start-end", "data": {"condition": "", "label": ""}}],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }

    try:
        workflow = await db_client.create_workflow(
            name=placeholder_name,
            workflow_definition=placeholder_def,
            user_id=user.id,
            template_context_variables={},
            workflow_configurations={"call_type": call_type, "_generating": True},
            organization_id=user.selected_organization_id,
        )
    except Exception as e:
        logger.error(f"Failed to create clone workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    asyncio.ensure_future(_run_clone_crew_background(
        workflow_id=workflow.id,
        audio_files=audio_data,
        business_name=business_name,
        call_type=call_type,
        org_id=user.selected_organization_id,
    ))

    logger.info(f"[VoiceClone] Created placeholder {workflow.id}, cloning launched in background")

    return {
        "id": workflow.id,
        "name": placeholder_name,
        "status": "active",
        "created_at": workflow.created_at,
        "workflow_definition": placeholder_def,
        "current_definition_id": workflow.current_definition_id,
        "template_context_variables": workflow.template_context_variables,
        "call_disposition_codes": workflow.call_disposition_codes,
        "public_id": workflow.public_id,
        "workflow_configurations": {"call_type": call_type, "_generating": True},
    }


class WorkflowSummaryResponse(BaseModel):
    id: int
    name: str
    call_type: Optional[str] = None


@router.get("/fetch")
@limiter.limit(RateLimitTiers.HIGH)
async def get_workflows(
    request: Request,
    user: UserModel = Depends(get_user),
    status: Optional[str] = Query(
        None,
        description="Filter by status - can be single value (active/archived) or comma-separated (active,archived)",
    ),
) -> List[WorkflowResponse]:
    """Get all workflows for the authenticated user's organization"""
    # Handle comma-separated status values
    if status and "," in status:
        # Split comma-separated values and fetch workflows for each status
        status_list = [s.strip() for s in status.split(",")]
        all_workflows = []
        for status_value in status_list:
            workflows = await db_client.get_all_workflows(
                organization_id=user.selected_organization_id, status=status_value
            )
            all_workflows.extend(workflows)
        workflows = all_workflows
    else:
        # Single status or no status filter
        workflows = await db_client.get_all_workflows(
            organization_id=user.selected_organization_id, status=status
        )

    # Get run counts for all workflows in a single batch query (N+1 optimization)
    workflow_ids = [workflow.id for workflow in workflows]
    run_counts = await db_client.get_workflow_run_counts_batch(workflow_ids)

    # Auto-heal stale _generating flags: if a workflow claims to be generating
    # but already has a real definition or was created > 3 min ago, clear the flag.
    from datetime import datetime, timezone, timedelta
    _stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=3)
    _stale_ids = []
    for wf in workflows:
        cfg = wf.workflow_configurations or {}
        if not cfg.get("_generating"):
            continue
        wf_def = wf.workflow_definition_with_fallback or {}
        has_real_def = len(wf_def.get("nodes", [])) > 2
        is_stale = wf.created_at.replace(tzinfo=timezone.utc) < _stale_cutoff if wf.created_at else False
        if has_real_def or is_stale:
            cfg["_generating"] = False
            _stale_ids.append(wf.id)

    if _stale_ids:
        logger.info(f"Auto-clearing stale _generating flag for workflow(s): {_stale_ids}")
        for wf_id in _stale_ids:
            asyncio.create_task(
                db_client.update_workflow(
                    workflow_id=wf_id,
                    name=next(w.name for w in workflows if w.id == wf_id),
                    workflow_definition=None,
                    template_context_variables=None,
                    workflow_configurations={"_generating": False},
                    organization_id=user.selected_organization_id,
                )
            )

    # Build response with batch-fetched run counts
    workflow_responses = [
            {
                "id": workflow.id,
                "public_id": workflow.public_id,
                "name": workflow.name,
                "status": workflow.status,
                "created_at": workflow.created_at,
                "workflow_definition": workflow.workflow_definition_with_fallback,
                "current_definition_id": workflow.current_definition_id,
                "template_context_variables": workflow.template_context_variables,
                "call_disposition_codes": workflow.call_disposition_codes,
                "workflow_configurations": workflow.workflow_configurations,
            "total_runs": run_counts.get(workflow.id, 0),
            }
        for workflow in workflows
    ]

    return workflow_responses


@router.get("/fetch/{workflow_id}")
@limiter.limit(RateLimitTiers.HIGH)
async def get_workflow(
    request: Request,
    workflow_id: int,
    user: UserModel = Depends(get_user),
) -> WorkflowResponse:
    """Get a single workflow by ID"""
    workflow = await db_client.get_workflow(
        workflow_id, organization_id=user.selected_organization_id
    )
    if workflow is None:
        raise HTTPException(
            status_code=404, detail=f"Workflow with id {workflow_id} not found"
        )

    return {
        "id": workflow.id,
        "public_id": workflow.public_id,
        "name": workflow.name,
        "status": workflow.status,
        "created_at": workflow.created_at,
        "workflow_definition": workflow.workflow_definition_with_fallback,
        "current_definition_id": workflow.current_definition_id,
        "template_context_variables": workflow.template_context_variables,
        "call_disposition_codes": workflow.call_disposition_codes,
        "workflow_configurations": workflow.workflow_configurations,
    }


@router.get("/by-token/{public_id}")
@limiter.limit(RateLimitTiers.HIGH)
async def get_workflow_by_token(
    request: Request,
    public_id: str,
    user: UserModel = Depends(get_user),
) -> WorkflowResponse:
    """Resolve a workflow by its opaque ``public_id`` token.

    This is the lookup used for user-facing URLs (``/workflow/<token>``). The
    enumerable integer primary key is intentionally NOT accepted here, so a
    guessed/sequential id in the URL cannot resolve to a workflow.
    """
    workflow = await db_client.get_workflow_by_public_id(public_id)
    # Enforce org ownership even though the token is unguessable.
    if workflow is None or workflow.organization_id != user.selected_organization_id:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return {
        "id": workflow.id,
        "public_id": workflow.public_id,
        "name": workflow.name,
        "status": workflow.status,
        "created_at": workflow.created_at,
        "workflow_definition": workflow.workflow_definition_with_fallback,
        "current_definition_id": workflow.current_definition_id,
        "template_context_variables": workflow.template_context_variables,
        "call_disposition_codes": workflow.call_disposition_codes,
        "workflow_configurations": workflow.workflow_configurations,
    }


@router.get("/summary")
@limiter.limit(RateLimitTiers.HIGH)
async def get_workflows_summary(
    request: Request,
    user: UserModel = Depends(get_user),
) -> List[WorkflowSummaryResponse]:
    """Get minimal workflow information (id and name only) for all workflows"""
    workflows = await db_client.get_all_workflows(
        organization_id=user.selected_organization_id
    )
    return [
        WorkflowSummaryResponse(
            id=workflow.id,
            name=workflow.name,
            call_type=(workflow.workflow_configurations or {}).get("call_type"),
        )
        for workflow in workflows
    ]


class DeleteWorkflowResponse(BaseModel):
    success: bool
    message: str


@router.delete("/{workflow_id}")
@limiter.limit(RateLimitTiers.STANDARD)
async def delete_workflow(
    request: Request,
    workflow_id: int,
    user: UserModel = Depends(get_user),
) -> DeleteWorkflowResponse:
    """
    Permanently delete a workflow.

    Args:
        workflow_id: The ID of the workflow to delete
        user: The authenticated user

    Returns:
        Success message
    """
    try:
        await db_client.delete_workflow(
            workflow_id=workflow_id,
            organization_id=user.selected_organization_id,
        )
        return DeleteWorkflowResponse(
            success=True,
            message=f"Workflow {workflow_id} deleted successfully"
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting workflow {workflow_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete workflow: {str(e)}")


@router.put("/{workflow_id}/status")
@limiter.limit(RateLimitTiers.STANDARD)
async def update_workflow_status(
    request: Request,
    workflow_id: int,
    status_request: UpdateWorkflowStatusRequest,
    user: UserModel = Depends(get_user),
) -> WorkflowResponse:
    """
    Update the status of a workflow (e.g., archive/unarchive).

    Args:
        workflow_id: The ID of the workflow to update
        request: The status update request

    Returns:
        The updated workflow
    """
    try:
        workflow = await db_client.update_workflow_status(
            workflow_id=workflow_id,
            status=status_request.status,
            organization_id=user.selected_organization_id,
        )
        run_count = await db_client.get_workflow_run_count(workflow.id)
        return {
            "id": workflow.id,
            "name": workflow.name,
            "status": workflow.status,
            "created_at": workflow.created_at,
            "workflow_definition": workflow.workflow_definition_with_fallback,
            "current_definition_id": workflow.current_definition_id,
            "template_context_variables": workflow.template_context_variables,
            "call_disposition_codes": workflow.call_disposition_codes,
            "workflow_configurations": workflow.workflow_configurations,
            "total_runs": run_count,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _extract_spoken_greeting_from_workflow(workflow) -> str | None:
    """Extract the spoken greeting (first paragraph of start-node prompt)."""
    try:
        wf_def = workflow.workflow_definition_with_fallback
        if wf_def:
            for node in wf_def.get("nodes", []):
                nd = node.get("data", {})
                if nd.get("is_start") or node.get("type") == "startCall":
                    raw_prompt = (nd.get("prompt") or "").strip()
                    if raw_prompt:
                        first_paragraph = raw_prompt.split("\n\n")[0].strip()
                        if len(first_paragraph) > 150:
                            last_space = first_paragraph[:150].rfind(" ")
                            if last_space > 80:
                                first_paragraph = first_paragraph[:last_space] + "..."
                            else:
                                first_paragraph = first_paragraph[:147] + "..."
                        return first_paragraph
                    break
    except Exception:
        pass
    return None


def _schedule_greeting_audio_refresh(workflow) -> None:
    """Fire-and-forget task to regenerate greeting audio after a workflow save.

    Invalidates the metadata cache and re-generates the audio in a
    background ``asyncio.Task`` so the save response is not delayed.
    """
    import asyncio

    from api.services.telephony.greeting_audio import (
        force_regenerate_greeting_audio,
        invalidate_cache,
    )

    wf_configs = workflow.workflow_configurations or {}
    tts_voice_id = wf_configs.get("tts_voice_id")
    workflow_language = wf_configs.get("workflow_language", "English")
    cartesia_model = wf_configs.get("tts_cartesia_model", "sonic-3.5")
    tts_accent = wf_configs.get("tts_accent") or None
    # Gemini for every language so the greeting matches the accent the agent
    # speaks with. Workflows still storing "elevenlabs" fall through to Gemini.
    tts_provider = "cartesia" if wf_configs.get("tts_provider") == "cartesia" else "gemini"

    if not tts_voice_id:
        invalidate_cache(workflow.id)
        return

    greeting_text = _extract_spoken_greeting_from_workflow(workflow)

    if not greeting_text:
        invalidate_cache(workflow.id)
        return

    async def _regen():
        try:
            url = await force_regenerate_greeting_audio(
                workflow.id,
                greeting_text,
                tts_voice_id,
                provider=tts_provider,  # type: ignore[arg-type]
                workflow_language=workflow_language,
                cartesia_model=cartesia_model,
                accent_id=tts_accent,
            )
            if url:
                logger.info(
                    f"[GREETING-AUDIO] Regenerated on save | workflow={workflow.id}, "
                    f"voice={tts_voice_id}, provider={tts_provider}, url={url[:80]}"
                )
        except Exception as e:
            logger.warning(f"[GREETING-AUDIO] Background regeneration failed: {e}")

    try:
        asyncio.get_running_loop().create_task(_regen())
    except RuntimeError:
        pass


@router.put("/{workflow_id}")
@limiter.limit(RateLimitTiers.STANDARD)
async def update_workflow(
    request: Request,
    workflow_id: int,
    update_request: UpdateWorkflowRequest,
    user: UserModel = Depends(get_user),
) -> WorkflowResponse:
    """
    Update an existing workflow.

    Args:
        workflow_id: The ID of the workflow to update
        request: The update request containing the new name and workflow definition

    Returns:
        The updated workflow

    Raises:
        HTTPException: If the workflow is not found or if there's a database error
    """
    try:
        workflow = await db_client.update_workflow(
            workflow_id=workflow_id,
            name=update_request.name,
            workflow_definition=update_request.workflow_definition,
            template_context_variables=update_request.template_context_variables,
            workflow_configurations=update_request.workflow_configurations,
            organization_id=user.selected_organization_id,
        )

        # Regenerate greeting audio in the background when the voice or
        # greeting text may have changed.
        _schedule_greeting_audio_refresh(workflow)

        return {
            "id": workflow.id,
            "name": workflow.name,
            "status": workflow.status,
            "created_at": workflow.created_at,
            "workflow_definition": workflow.workflow_definition_with_fallback,
            "current_definition_id": workflow.current_definition_id,
            "template_context_variables": workflow.template_context_variables,
            "call_disposition_codes": workflow.call_disposition_codes,
            "workflow_configurations": workflow.workflow_configurations,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{workflow_id}/runs")
@limiter.limit(RateLimitTiers.CRITICAL)  # Critical for calling operations
async def create_workflow_run(
    request: Request,
    workflow_id: int,
    run_request: CreateWorkflowRunRequest,
    user: UserModel = Depends(get_user),
) -> CreateWorkflowRunResponse:
    """
    Create a new workflow run when the user decides to execute the workflow via chat or voice

    Args:
        workflow_id: The ID of the workflow to run
        request: The create workflow run request
        user: The user to create the workflow run for
    """
    # Check subscription allows making calls
    can_call = await _sub_service.check_can_make_call(user.selected_organization_id)
    if not can_call["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_call["reason"],
                "message": can_call.get("message", "Subscription limit reached"),
            },
        )

    run = await db_client.create_workflow_run(
        run_request.name, workflow_id, run_request.mode, user.id
    )
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "name": run.name,
        "mode": run.mode,
        "created_at": run.created_at,
        "definition_id": run.definition_id,
        "initial_context": run.initial_context,
        "gathered_context": run.gathered_context,
    }


@router.get("/{workflow_id}/runs/{run_id}")
@limiter.limit(RateLimitTiers.HIGH)
async def get_workflow_run(
    request: Request,
    workflow_id: int,
    run_id: int,
    user: UserModel = Depends(get_user),
) -> WorkflowRunResponseSchema:
    run = await db_client.get_workflow_run(
        run_id, organization_id=user.selected_organization_id
    )
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "name": run.name,
        "mode": run.mode,
        "is_completed": run.is_completed,
        "transcript_url": run.transcript_url,
        "recording_url": run.recording_url,
        "cost_info": {
            "dograh_token_usage": (
                run.cost_info.get("dograh_token_usage")
                if run.cost_info and "dograh_token_usage" in run.cost_info
                else round(float(run.cost_info.get("total_cost_usd", 0)) * 100, 2)
                if run.cost_info and "total_cost_usd" in run.cost_info
                else 0
            ),
            "call_duration_seconds": int(
                round(run.cost_info.get("call_duration_seconds"))
            )
            if run.cost_info
            else None,
        }
        if run.cost_info
        else None,
        "created_at": run.created_at,
        "definition_id": run.definition_id,
        "initial_context": run.initial_context,
        "gathered_context": run.gathered_context,
        "action_results": (run.logs or {}).get("action_results"),
    }


class WorkflowRunsResponse(BaseModel):
    runs: List[WorkflowRunResponseSchema]
    total_count: int
    page: int
    limit: int
    total_pages: int
    applied_filters: Optional[List[dict]] = None


@router.get("/{workflow_id}/runs")
@limiter.limit(RateLimitTiers.HIGH)
async def get_workflow_runs(
    request: Request,
    workflow_id: int,
    page: int = 1,
    limit: int = 50,
    filters: Optional[str] = Query(None, description="JSON-encoded filter criteria"),
    user: UserModel = Depends(get_user),
) -> WorkflowRunsResponse:
    """
    Get workflow runs with optional filtering.

    Filters should be provided as a JSON-encoded array of filter criteria.
    Example: [{"attribute": "dateRange", "value": {"from": "2024-01-01", "to": "2024-01-31"}}]
    """
    offset = (page - 1) * limit

    # Parse filters if provided
    filter_criteria = []
    if filters:
        try:
            filter_criteria = json.loads(filters)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid filter format")

        # Restrict allowed filter attributes for regular users
        allowed_attributes = {
            "dateRange",
            "dispositionCode",
            "duration",
            "status",
            "tokenUsage",
        }
        for filter_item in filter_criteria:
            attribute = filter_item.get("attribute")
            if attribute and attribute not in allowed_attributes:
                raise HTTPException(
                    status_code=403, detail=f"Invalid attribute '{attribute}'"
                )

    # Apply filters if any
    if filter_criteria:
        runs, total_count = await db_client.get_workflow_runs_by_workflow_id(
            workflow_id,
            organization_id=user.selected_organization_id,
            limit=limit,
            offset=offset,
            filters=filter_criteria,
        )
    else:
        # Use existing logic for unfiltered results
        runs, total_count = await db_client.get_workflow_runs_by_workflow_id(
            workflow_id,
            organization_id=user.selected_organization_id,
            limit=limit,
            offset=offset,
        )

    total_pages = (total_count + limit - 1) // limit

    return WorkflowRunsResponse(
        runs=runs,
        total_count=total_count,
        page=page,
        limit=limit,
        total_pages=total_pages,
        applied_filters=filter_criteria if filter_criteria else None,
    )


@router.get("/templates")
@limiter.limit(RateLimitTiers.HIGH)
async def get_workflow_templates(request: Request) -> List[WorkflowTemplateResponse]:
    """
    Get all available workflow templates.

    Returns:
        List of workflow templates
    """
    templates = await db_client.get_all_workflow_templates()

    return [
        {
            "id": template.id,
            "template_name": template.template_name,
            "template_description": template.template_description,
            "template_json": template.template_json,
            "created_at": template.created_at,
        }
        for template in templates
    ]


@router.post("/templates/duplicate")
@limiter.limit(RateLimitTiers.STANDARD)
async def duplicate_workflow_template(
    request: Request,
    duplicate_request: DuplicateTemplateRequest,
    user: UserModel = Depends(get_user),
) -> WorkflowResponse:
    """
    Duplicate a workflow template to create a new workflow for the user.

    Args:
        request: The duplicate template request
        user: The authenticated user

    Returns:
        The newly created workflow
    """
    # Check subscription allows creating more workflows
    can_create = await _sub_service.check_can_create_workflow(user.selected_organization_id)
    if not can_create["allowed"]:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": can_create["reason"],
                "message": can_create.get("message", "Subscription limit reached"),
            },
        )

    template = await db_client.get_workflow_template(duplicate_request.template_id)

    if not template:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow template with id {duplicate_request.template_id} not found",
        )

    # Create a new workflow from the template
    workflow = await db_client.create_workflow(
        duplicate_request.workflow_name,
        template.template_json,
        user.id,
        user.selected_organization_id,
    )

    return {
        "id": workflow.id,
        "public_id": workflow.public_id,
        "name": workflow.name,
        "status": workflow.status,
        "created_at": workflow.created_at,
        "workflow_definition": workflow.workflow_definition_with_fallback,
        "current_definition_id": workflow.current_definition_id,
        "template_context_variables": workflow.template_context_variables,
        "call_disposition_codes": workflow.call_disposition_codes,
        "workflow_configurations": workflow.workflow_configurations,
    }


# ============================================================================
# AI Action Helper Endpoint (standalone, no workflow context needed)
# ============================================================================


class AIActionHelpRequest(BaseModel):
    action_type: str  # "database_query", "api_call", "webhook", "email"
    description: str
    action_data: dict = {}
    available_variables: list = []
    # Database-specific fields
    database_service: Optional[str] = None
    table_name: Optional[str] = None
    operation: Optional[str] = None


@router.post("/ai/action-help")
@limiter.limit(RateLimitTiers.LOW)
async def ai_action_help(
    request: Request,
    body: AIActionHelpRequest,
    user: UserModel = Depends(get_user),
):
    """Generate technical configuration from plain English for action panels."""
    try:
        if body.action_type == "database_query":
            result = await suggest_database_query(
                user.id,
                database_service=body.database_service or "",
                table_name=body.table_name or "",
                operation=body.operation or "query",
                description=body.description,
                available_variables=body.available_variables,
            )
            return {"type": "database_query", "suggestion": result}
        else:
            result = await suggest_action_content(
                user.id,
                action_type=body.action_type,
                description=body.description,
                action_data=body.action_data,
                available_variables=body.available_variables,
            )
            return {"type": body.action_type, "suggestion": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"AI action help error: {e}")
        raise HTTPException(status_code=500, detail="AI generation failed. Please try again.")


# ============================================================================
# AI Suggestion Endpoints
# ============================================================================


class AISuggestRequest(BaseModel):
    type: str  # "edge_condition", "node_prompt", "node_improve", "extraction_improve", "suggest_variables", "suggest_field", "improve_response"
    source_node_id: Optional[str] = None
    target_node_id: Optional[str] = None
    node_id: Optional[str] = None
    current_nodes: Optional[list] = None
    current_edges: Optional[list] = None
    field_name: Optional[str] = None
    current_value: Optional[str] = None
    conversation_context: Optional[str] = None
    target_response: Optional[str] = None


@router.post("/{workflow_id}/ai-suggest")
@limiter.limit(RateLimitTiers.LOW)
async def ai_suggest(
    request: Request,
    workflow_id: int,
    suggest_request: AISuggestRequest,
    user: UserModel = Depends(get_user),
):
    """Get AI suggestions for edge conditions or node prompts."""
    wf = await db_client.get_workflow(workflow_id, user.id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if suggest_request.current_nodes is not None:
        nodes = suggest_request.current_nodes
        edges = suggest_request.current_edges or []
    else:
        wf_def = wf.workflow_definition_with_fallback
        if not wf_def:
            raise HTTPException(status_code=400, detail="Workflow has no definition")
        nodes = wf_def.get("nodes", [])
        edges = wf_def.get("edges", [])

    global_prompt = None
    for n in nodes:
        if n.get("type") == "globalNode":
            global_prompt = n.get("data", {}).get("prompt", "")
            break

    # Extract call_type from workflow_configurations (defaults to "OUTBOUND" if not set)
    call_type = wf.workflow_configurations.get("call_type", "OUTBOUND") if wf.workflow_configurations else "OUTBOUND"

    try:
        if suggest_request.type == "edge_condition":
            if not suggest_request.source_node_id or not suggest_request.target_node_id:
                raise HTTPException(status_code=400, detail="source_node_id and target_node_id required")
            src = next((n for n in nodes if n["id"] == suggest_request.source_node_id), None)
            tgt = next((n for n in nodes if n["id"] == suggest_request.target_node_id), None)
            if not src or not tgt:
                raise HTTPException(status_code=400, detail="Source or target node not found")
            result = await suggest_edge_condition(user.id, src, tgt, edges, global_prompt, call_type)
            return {"type": "edge_condition", "suggestion": result}

        elif suggest_request.type == "node_prompt":
            if not suggest_request.node_id:
                raise HTTPException(status_code=400, detail="node_id required")
            tgt = next((n for n in nodes if n["id"] == suggest_request.node_id), None)
            if not tgt:
                raise HTTPException(status_code=400, detail="Node not found")
            result = await suggest_node_prompt(user.id, tgt, nodes, edges, global_prompt, call_type)
            return {"type": "node_prompt", "suggestion": result}

        elif suggest_request.type == "node_improve":
            if not suggest_request.node_id:
                raise HTTPException(status_code=400, detail="node_id required")
            tgt = next((n for n in nodes if n["id"] == suggest_request.node_id), None)
            if not tgt:
                raise HTTPException(status_code=400, detail="Node not found")
            result = await improve_node_prompt(user.id, tgt, nodes, edges, global_prompt, call_type)
            return {"type": "node_improve", "suggestion": result}

        elif suggest_request.type == "extraction_improve":
            if not suggest_request.node_id:
                raise HTTPException(status_code=400, detail="node_id required")
            tgt = next((n for n in nodes if n["id"] == suggest_request.node_id), None)
            if not tgt:
                raise HTTPException(status_code=400, detail="Node not found")
            result = await improve_extraction_prompt(user.id, tgt, nodes, edges, global_prompt, call_type)
            return {"type": "extraction_improve", "suggestion": result}

        elif suggest_request.type == "suggest_variables":
            if not suggest_request.node_id:
                raise HTTPException(status_code=400, detail="node_id required")
            tgt = next((n for n in nodes if n["id"] == suggest_request.node_id), None)
            if not tgt:
                raise HTTPException(status_code=400, detail="Node not found")
            result = await suggest_extraction_variables(user.id, tgt, nodes, edges, global_prompt, call_type)
            return {"type": "suggest_variables", "suggestion": result}

        elif suggest_request.type == "suggest_field":
            if not suggest_request.node_id:
                raise HTTPException(status_code=400, detail="node_id required")
            tgt = next((n for n in nodes if n["id"] == suggest_request.node_id), None)
            if not tgt:
                raise HTTPException(status_code=400, detail="Node not found")
            result = await suggest_field(
                user.id, tgt, nodes, edges,
                field_name=suggest_request.field_name or "name",
                current_value=suggest_request.current_value or "",
                global_prompt=global_prompt,
                call_type=call_type,
            )
            return {"type": "suggest_field", "suggestion": result}

        elif suggest_request.type == "improve_response":
            if not suggest_request.conversation_context or not suggest_request.target_response:
                raise HTTPException(status_code=400, detail="conversation_context and target_response required")
            result = await improve_agent_response(
                user_id=user.id,
                conversation_context=suggest_request.conversation_context,
                target_response=suggest_request.target_response,
            )
            return {"type": "improve_response", "suggestion": result}

        else:
            raise HTTPException(status_code=400, detail=f"Unknown type: {suggest_request.type}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"AI suggestion error: {e}")
        raise HTTPException(status_code=500, detail="AI suggestion failed. Please try again.")


# ──────────────────────────────────────────────────────────────────────────────
# AI Flow Edit endpoint
# ──────────────────────────────────────────────────────────────────────────────


class AIFlowEditRequest(BaseModel):
    instruction: str
    current_nodes: Optional[list] = None
    current_edges: Optional[list] = None
    current_viewport: Optional[dict] = None


@router.post("/{workflow_id}/ai-edit")
@limiter.limit(RateLimitTiers.LOW)
async def ai_edit(
    request: Request,
    workflow_id: int,
    edit_request: AIFlowEditRequest,
    user: UserModel = Depends(get_user),
):
    """Edit a workflow using natural language instructions."""
    wf = await db_client.get_workflow(workflow_id, user.id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if edit_request.current_nodes is not None:
        nodes = edit_request.current_nodes
        edges = edit_request.current_edges or []
        viewport = edit_request.current_viewport or {"x": 0, "y": 0, "zoom": 1}
    else:
        wf_def = wf.workflow_definition_with_fallback
        if not wf_def:
            raise HTTPException(status_code=400, detail="Workflow has no definition")
        nodes = wf_def.get("nodes", [])
        edges = wf_def.get("edges", [])
        viewport = wf_def.get("viewport", {"x": 0, "y": 0, "zoom": 1})

    global_prompt = None
    for n in nodes:
        if n.get("type") == "globalNode":
            global_prompt = n.get("data", {}).get("prompt", "")
            break

    call_type = wf.workflow_configurations.get("call_type", "OUTBOUND") if wf.workflow_configurations else "OUTBOUND"

    try:
        result = await ai_edit_workflow(
            user_id=user.id,
            instruction=edit_request.instruction,
            current_nodes=nodes,
            current_edges=edges,
            current_viewport=viewport,
            global_prompt=global_prompt,
            call_type=call_type,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"AI flow edit error: {e}")
        raise HTTPException(status_code=500, detail="AI flow edit failed. Please try again.")


# ──────────────────────────────────────────────────────────────────────────────
# Self-Improving Agent endpoints
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/{workflow_id}/improvements")
@limiter.limit(RateLimitTiers.HIGH)
async def get_improvements(
    request: Request,
    workflow_id: int,
    user: UserModel = Depends(get_user),
    status: Optional[str] = Query(None, description="Filter by status: pending, accepted, rejected, auto_applied"),
):
    """List improvement suggestions for a workflow."""
    improvements = await db_client.get_improvements_for_workflow(
        workflow_id=workflow_id,
        status=status,
    )
    return [
        {
            "id": imp.id,
            "status": imp.status,
            "suggestions": imp.suggestions,
            "analysis_summary": imp.analysis_summary,
            "calls_analyzed": imp.calls_analyzed,
            "created_at": imp.created_at,
            "applied_indices": imp.applied_indices or [],
            "rejected_indices": imp.rejected_indices or [],
        }
        for imp in improvements
    ]


@router.get("/{workflow_id}/improvements/count")
@limiter.limit(RateLimitTiers.HIGH)
async def get_improvement_count(
    request: Request,
    workflow_id: int,
    user: UserModel = Depends(get_user),
):
    """Get count of pending improvements (for badge display)."""
    try:
        count = await db_client.get_pending_improvement_count(workflow_id)
        return {"pending_count": count}
    except Exception:
        return {"pending_count": 0}


@router.post("/{workflow_id}/improvements/analyze")
@limiter.limit(RateLimitTiers.LOW)
async def trigger_improvement_analysis(
    request: Request,
    workflow_id: int,
    user: UserModel = Depends(get_user),
):
    """Manually trigger a self-improvement analysis right now.

    Bypasses both the `auto_improve_interval` (N new calls) and the
    `auto_improve_cooldown_minutes` gates so the user can iterate without
    waiting for the automatic threshold. Still respects the per-workflow
    Redis lock — duplicate clicks while an analysis is already running
    will be coalesced into a single run.
    """
    workflow = await db_client.get_workflow(
        workflow_id, organization_id=user.selected_organization_id
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Need at least one completed run to have anything to analyse.
    last_run_id = await db_client.get_last_analyzed_run_id(workflow_id)
    new_count = await db_client.count_completed_runs_since(workflow_id, last_run_id)
    total_completed = await db_client.count_completed_runs_since(workflow_id, None)
    if total_completed == 0:
        return {
            "status": "skipped",
            "reason": "no_completed_calls",
            "message": "No completed calls to analyse yet.",
        }

    from api.tasks.arq import enqueue_job
    from api.tasks.function_names import FunctionNames

    # Separate job_id from the automatic one so a manual click is never
    # coalesced into a queued auto-run (which would skip when the toggle is
    # off). Still idempotent within a single click-burst — duplicate clicks
    # while the same manual job is pending will be coalesced.
    await enqueue_job(
        FunctionNames.RUN_IMPROVEMENT_ANALYSIS,
        workflow_id,
        user.selected_organization_id,
        True,  # force=True
        _job_id=f"improve_run_manual:{workflow_id}",
    )

    return {
        "status": "queued",
        "workflow_id": workflow_id,
        "new_calls_since_last_analysis": new_count,
        "total_completed_calls": total_completed,
    }


@router.post("/{workflow_id}/rehearse")
@limiter.limit(RateLimitTiers.LOW)
async def rehearse_workflow(
    request: Request,
    workflow_id: int,
    user: UserModel = Depends(get_user),
):
    """
    Queue a background rehearsal (text-simulated calls with 3 diverse personas).
    The result is stored on `workflow_configurations.rehearsal` with a health
    score and per-persona issues so the UI can display a Workflow Health badge.
    Idempotent: duplicate triggers within the job TTL are dropped at the queue.
    """
    workflow = await db_client.get_workflow(workflow_id, user.id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    from api.tasks.arq import enqueue_job
    from api.tasks.function_names import FunctionNames

    await enqueue_job(
        FunctionNames.RUN_WORKFLOW_REHEARSAL,
        workflow_id,
        _job_id=f"rehearsal:{workflow_id}",
    )
    return {"status": "queued", "workflow_id": workflow_id}


@router.get("/{workflow_id}/rehearsal")
@limiter.limit(RateLimitTiers.HIGH)
async def get_rehearsal_result(
    request: Request,
    workflow_id: int,
    user: UserModel = Depends(get_user),
):
    """Return the latest rehearsal report for a workflow (for the Health badge)."""
    workflow = await db_client.get_workflow(workflow_id, user.id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    configs = workflow.workflow_configurations or {}
    report = configs.get("rehearsal")
    if not report:
        return {"available": False}
    return {
        "available": True,
        "health_score": report.get("health_score"),
        "personas_tested": report.get("personas_tested"),
        "summary": report.get("summary"),
        "results": report.get("results", []),
        "generated_at": report.get("generated_at"),
    }


def _normalize_exit_condition(ec: dict, fallback_target_name: str = "") -> dict:
    """Ensure an exit condition dict has the (id, name, llm_description) fields
    required by ExitConditionDTO. Returns the same dict (mutated in place)
    with safe non-empty defaults filled in, or `None` if the condition can't
    be salvaged (no name AND no description)."""
    if not isinstance(ec, dict):
        return None
    name = (ec.get("name") or "").strip()
    desc = (ec.get("llm_description") or ec.get("description") or "").strip()
    if not name and not desc:
        return None
    if not name:
        # Slugify the description as a last resort so we never produce nameless exits.
        slug = re.sub(r"[^a-z0-9]+", "_", desc.lower()).strip("_")[:40]
        name = slug or "task_complete"
    if not desc:
        desc = f"Route caller to {fallback_target_name}" if fallback_target_name else f"Trigger when {name}"
    ec["name"] = name
    ec["llm_description"] = desc
    ec.setdefault("id", f"exit-{uuid.uuid4().hex[:8]}")
    return ec


def _normalize_exit_conditions(ecs: list, fallback_target_name: str = "") -> list:
    out: list[dict] = []
    for ec in ecs or []:
        normalized = _normalize_exit_condition(dict(ec) if isinstance(ec, dict) else {}, fallback_target_name)
        if normalized:
            out.append(normalized)
    return out


async def _apply_single_suggestion(
    suggestion: dict,
    wf_def: dict,
    workflow_name: str,
    workflow_id: int,
    user: UserModel,
    workflow_configurations: Optional[dict] = None,
) -> dict:
    """Mutate `wf_def` to apply one suggestion (in place) OR spawn a new workflow.

    Returns metadata about what happened:
        {"applied": bool, "kind": <type>, "new_node_id"?: str, "new_workflow_id"?: int,
         "edge_id"?: str, "reason"?: str}

    Does NOT save the workflow — caller batches saves for efficiency.
    """
    s_type = suggestion.get("type")
    nodes = wf_def.setdefault("nodes", [])
    edges = wf_def.setdefault("edges", [])

    # rewrite_prompt ----------------------------------------------------------
    if s_type == "rewrite_prompt":
        target_id = suggestion.get("target_node_id")
        if not target_id:
            return {"applied": False, "kind": s_type, "reason": "missing target_node_id"}
        for node in nodes:
            if node.get("id") == target_id:
                node.setdefault("data", {})["prompt"] = suggestion.get("after", "")
                return {"applied": True, "kind": s_type, "target_node_id": target_id}
        return {"applied": False, "kind": s_type, "reason": f"target_node_id {target_id} not found"}

    # add_exit_condition ------------------------------------------------------
    if s_type == "add_exit_condition":
        target_id = suggestion.get("target_node_id")
        raw_exit = suggestion.get("new_exit_condition") or {}
        if not target_id:
            return {"applied": False, "kind": s_type, "reason": "missing target_node_id"}
        normalized = _normalize_exit_condition(dict(raw_exit))
        if not normalized:
            return {"applied": False, "kind": s_type, "reason": "exit condition is missing name and description"}
        for node in nodes:
            if node.get("id") == target_id:
                exits = node.setdefault("data", {}).setdefault("exit_conditions", [])
                # Don't duplicate an exit condition the node already has.
                if any((ec.get("name") or "").strip().lower() == normalized["name"].lower() for ec in exits):
                    return {
                        "applied": False,
                        "kind": s_type,
                        "reason": f"exit '{normalized['name']}' already exists on {target_id}",
                    }
                exits.append(normalized)
                return {
                    "applied": True,
                    "kind": s_type,
                    "target_node_id": target_id,
                    "exit_id": normalized["id"],
                    "exit_name": normalized["name"],
                }
        return {"applied": False, "kind": s_type, "reason": f"target_node_id {target_id} not found"}

    # add_node (auto-wired) ---------------------------------------------------
    if s_type == "add_node":
        new_node_data = suggestion.get("new_node") or {}
        source_node_id = new_node_data.get("source_node_id")
        trigger_condition = (new_node_data.get("trigger_condition") or "").strip()

        if (
            not new_node_data.get("name")
            or not (new_node_data.get("prompt") or "").strip()
            or not source_node_id
            or not trigger_condition
        ):
            return {
                "applied": False,
                "kind": s_type,
                "reason": "add_node requires name + non-empty prompt + source_node_id + trigger_condition",
            }

        source_node = next((n for n in nodes if n.get("id") == source_node_id), None)
        if not source_node:
            return {
                "applied": False,
                "kind": s_type,
                "reason": f"source_node_id {source_node_id} not found",
            }

        new_id = new_node_data.get("id") or f"node-{uuid.uuid4().hex[:8]}"

        exit_conditions = _normalize_exit_conditions(
            new_node_data.get("exit_conditions") or [],
            fallback_target_name=new_node_data["name"],
        )
        if not exit_conditions:
            # Always give the new node at least one way to leave so it doesn't
            # become a dead end on the canvas.
            exit_conditions = _normalize_exit_conditions([
                {"name": "task_complete", "llm_description": "Task done — return to the previous step"},
                {"name": "user_wants_to_end", "llm_description": "Caller wants to end the conversation"},
            ])

        src_pos = source_node.get("position", {}) or {}
        new_pos = {
            "x": float(src_pos.get("x", 400)) + 380,
            "y": float(src_pos.get("y", 100)),
        }
        # If something already lives there, nudge down so nodes don't overlap.
        while any(
            abs((n.get("position", {}) or {}).get("x", 0) - new_pos["x"]) < 60
            and abs((n.get("position", {}) or {}).get("y", 0) - new_pos["y"]) < 60
            for n in nodes
        ):
            new_pos["y"] += 240

        nodes.append({
            "id": new_id,
            "type": new_node_data.get("type", "agentNode"),
            "position": new_pos,
            "measured": {"width": 320, "height": 180},
            "data": {
                "name": new_node_data["name"],
                "prompt": new_node_data.get("prompt", ""),
                "is_static": False,
                "allow_interrupt": True,
                "add_global_prompt": True,
                "exit_conditions": exit_conditions,
            },
        })

        # Make sure the trigger exit condition actually exists on the source.
        # If not, append it so the routing engine recognises it.
        src_data = source_node.setdefault("data", {})
        src_exits = src_data.setdefault("exit_conditions", [])
        if not any((ec.get("name") or "").strip().lower() == trigger_condition.lower() for ec in src_exits):
            src_exits.append({
                "id": f"exit-{uuid.uuid4().hex[:8]}",
                "name": trigger_condition,
                "llm_description": new_node_data.get("trigger_description")
                    or f"Route caller to {new_node_data['name']}",
            })

        edge_id = f"edge-{uuid.uuid4().hex[:8]}"
        edges.append({
            "id": edge_id,
            "source": source_node_id,
            "target": new_id,
            "type": "custom",
            "animated": True,
            "data": {
                "condition": trigger_condition,
                "label": trigger_condition,
            },
        })

        # ── Auto-wire OUTGOING edges from the new node ────────────────────
        # The graph validator requires every agentNode to have >=1 outgoing
        # edge. If we leave the new node's exit conditions dangling, the user
        # sees a red border on the node and has to manually drag edges for each
        # one. Pick a target that matches the workflow's existing convention:
        #   1. If the workflow has an endCall node → every exit goes to it
        #      (matches the canvas convention where each agent finishes by
        #      handing off to End Call).
        #   2. Otherwise → fall back to wiring back to the source node so the
        #      caller resumes the main flow. Never leave the new node with
        #      zero outgoing edges.
        end_node_id = next(
            (n.get("id") for n in nodes if n.get("type") == "endCall"),
            None,
        )
        fallback_target = end_node_id or source_node_id
        outgoing_edge_ids: list[str] = []
        for ec in exit_conditions:
            ec_name = (ec.get("name") or "").strip()
            if not ec_name:
                continue
            out_edge_id = f"edge-{uuid.uuid4().hex[:8]}"
            edges.append({
                "id": out_edge_id,
                "source": new_id,
                "target": fallback_target,
                "type": "custom",
                "animated": True,
                "data": {
                    "condition": ec_name,
                    "label": ec_name,
                },
            })
            outgoing_edge_ids.append(out_edge_id)

        return {
            "applied": True,
            "kind": s_type,
            "new_node_id": new_id,
            "new_node_name": new_node_data["name"],
            "source_node_id": source_node_id,
            "trigger_condition": trigger_condition,
            "edge_id": edge_id,
            "outgoing_edge_ids": outgoing_edge_ids,
        }

    # adjust_edge -------------------------------------------------------------
    if s_type == "adjust_edge":
        change = suggestion.get("edge_change") or {}
        src = change.get("from_source")
        tgt = change.get("to_target")
        new_cond = change.get("new_condition")
        if not src or not tgt:
            return {"applied": False, "kind": s_type, "reason": "missing from_source or to_target"}
        for e in edges:
            if e.get("source") == src and e.get("target") == tgt:
                if new_cond is not None:
                    e.setdefault("data", {})["condition"] = new_cond
                    e["data"]["label"] = change.get("new_label", new_cond)
                return {"applied": True, "kind": s_type, "edge_id": e.get("id"), "from": src, "to": tgt}
        if new_cond is not None:
            edge_id = f"edge-{uuid.uuid4().hex[:8]}"
            edges.append({
                "id": edge_id,
                "source": src,
                "target": tgt,
                "type": "custom",
                "animated": True,
                "data": {
                    "condition": new_cond,
                    "label": change.get("new_label", new_cond),
                },
            })
            return {"applied": True, "kind": s_type, "edge_id": edge_id, "from": src, "to": tgt, "created": True}
        return {"applied": False, "kind": s_type, "reason": "no matching edge and no new_condition"}

    # spawn_workflow ----------------------------------------------------------
    if s_type == "spawn_workflow":
        spawn = suggestion.get("spawn") or {}
        new_name = (spawn.get("name") or "").strip()
        initial_prompt = (spawn.get("initial_prompt") or "").strip()
        if not new_name or not initial_prompt:
            return {"applied": False, "kind": s_type, "reason": "spawn missing name or initial_prompt"}

        # Subscription gate: never spawn if the user can't create another workflow.
        try:
            can_create = await _sub_service.check_can_create_workflow(user.selected_organization_id)
            if not can_create.get("allowed"):
                return {
                    "applied": False,
                    "kind": s_type,
                    "reason": can_create.get("reason") or "subscription_limit",
                }
        except Exception as sub_err:
            logger.warning(f"[SelfImprove] Subscription check failed (continuing): {sub_err}")

        call_type = (spawn.get("call_type") or "INBOUND").upper()
        use_case = (spawn.get("use_case") or new_name).strip()

        skeleton = _build_spawn_workflow_skeleton(
            call_type=call_type,
            workflow_name=new_name,
            use_case=use_case,
            agent_prompt=initial_prompt,
        )

        # Inherit voice / language / safety settings from the source workflow so
        # the spawned agent doesn't fall back to whatever the platform defaults
        # happen to be.
        inherited_configs = {
            k: v for k, v in (workflow_configurations or {}).items()
            if k in {
                "tts_provider", "tts_voice_id", "tts_voice_name",
                "tts_cartesia_model", "voice_mode",
                "workflow_language", "max_call_duration",
                "max_user_idle_timeout", "max_cumulative_silence",
                "guardrails_enabled", "redact_pii",
            }
        }
        inherited_configs["call_type"] = call_type
        inherited_configs["spawned_from_workflow_id"] = workflow_id
        inherited_configs["spawned_from_suggestion"] = {
            "source_workflow": workflow_name,
            "evidence_run_ids": suggestion.get("evidence_run_ids") or [],
            "description": suggestion.get("description", ""),
        }

        new_workflow = await db_client.create_workflow(
            name=new_name,
            workflow_definition=skeleton,
            user_id=user.id,
            organization_id=user.selected_organization_id,
            workflow_configurations=inherited_configs,
        )

        return {
            "applied": True,
            "kind": s_type,
            "new_workflow_id": new_workflow.id,
            "new_workflow_public_id": new_workflow.public_id,
            "new_workflow_name": new_workflow.name,
        }

    return {"applied": False, "kind": s_type or "unknown", "reason": "unknown suggestion type"}


def _build_spawn_workflow_skeleton(
    call_type: str, workflow_name: str, use_case: str, agent_prompt: str,
) -> dict:
    """3-node skeleton (startCall -> agentNode -> endCall) seeded with the
    architect's suggested agent prompt. Mirrors the shape produced by
    workflow_generator._create_basic_template so the workflow editor opens
    the spawned agent without any extra normalisation."""
    if call_type == "WEBSITE":
        greeting = f"Hi! Welcome. I'm your assistant and I can help you with {use_case.lower()}. What can I do for you?"
    elif call_type == "OUTBOUND":
        greeting = f"Hello, I'm calling regarding {use_case.lower()}. Do you have a moment to talk?"
    else:
        greeting = f"Hello, thank you for calling. I'm here to help with {use_case.lower()}. How can I assist you today?"

    start_id = f"start-{uuid.uuid4().hex[:8]}"
    agent_id = f"agent-{uuid.uuid4().hex[:8]}"
    end_id = f"end-{uuid.uuid4().hex[:8]}"

    return {
        "nodes": [
            {
                "id": start_id,
                "type": "startCall",
                "position": {"x": 400, "y": 80},
                "measured": {"width": 320, "height": 180},
                "data": {
                    "prompt": greeting,
                    "name": "Start Call",
                    "is_start": True,
                    "is_static": False,
                    "allow_interrupt": True,
                    "add_global_prompt": True,
                    "exit_conditions": [
                        {
                            "id": f"exit-{uuid.uuid4().hex[:8]}",
                            "name": "greeting_complete",
                            "llm_description": "The greeting is complete and ready to proceed",
                        }
                    ],
                },
            },
            {
                "id": agent_id,
                "type": "agentNode",
                "position": {"x": 400, "y": 430},
                "measured": {"width": 320, "height": 180},
                "data": {
                    "name": workflow_name,
                    "prompt": agent_prompt,
                    "is_static": False,
                    "allow_interrupt": True,
                    "add_global_prompt": True,
                    "exit_conditions": [
                        {
                            "id": f"exit-{uuid.uuid4().hex[:8]}",
                            "name": "task_complete",
                            "llm_description": "The caller's request has been handled",
                        },
                        {
                            "id": f"exit-{uuid.uuid4().hex[:8]}",
                            "name": "user_wants_to_end",
                            "llm_description": "The caller wants to end the call",
                        },
                    ],
                },
            },
            {
                "id": end_id,
                "type": "endCall",
                "position": {"x": 400, "y": 780},
                "measured": {"width": 320, "height": 180},
                "data": {
                    "prompt": "Thank you, have a great day. Goodbye.",
                    "name": "End Call",
                    "is_static": False,
                    "allow_interrupt": True,
                    "add_global_prompt": True,
                    "exit_conditions": [],
                },
            },
        ],
        "edges": [
            {
                "id": f"edge-{uuid.uuid4().hex[:8]}",
                "source": start_id,
                "target": agent_id,
                "type": "custom",
                "animated": True,
                "data": {"condition": "greeting_complete", "label": "Greeting Done"},
            },
            {
                "id": f"edge-{uuid.uuid4().hex[:8]}",
                "source": agent_id,
                "target": end_id,
                "type": "custom",
                "animated": True,
                "data": {"condition": "task_complete", "label": "Done"},
            },
            {
                "id": f"edge-{uuid.uuid4().hex[:8]}",
                "source": agent_id,
                "target": end_id,
                "type": "custom",
                "animated": True,
                "data": {"condition": "user_wants_to_end", "label": "Hang Up"},
            },
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def _is_batch_settled(improvement) -> bool:
    """A batch is 'settled' when every suggestion has been either applied or rejected."""
    total = len(improvement.suggestions or [])
    applied = set(improvement.applied_indices or [])
    rejected = set(improvement.rejected_indices or [])
    return total > 0 and len(applied | rejected) >= total


@router.post("/{workflow_id}/improvements/{improvement_id}/apply")
@limiter.limit(RateLimitTiers.LOW)
async def apply_improvement(
    request: Request,
    workflow_id: int,
    improvement_id: int,
    user: UserModel = Depends(get_user),
):
    """Apply every still-undecided suggestion in the batch.

    Backward-compatible wrapper around the per-suggestion apply endpoint —
    loops every suggestion that hasn't been applied/rejected yet and applies
    those whose type is auto-applicable. spawn_workflow is included only when
    the suggestion already passed the architect's evidence threshold (which
    self_improve.py enforces at generation time).
    """
    improvement = await db_client.get_improvement_by_id(improvement_id)
    if not improvement or improvement.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="Improvement not found")
    if improvement.status not in ("pending",):
        raise HTTPException(status_code=400, detail=f"Improvement already {improvement.status}")

    workflow = await db_client.get_workflow_by_id(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    wf_def = workflow.workflow_definition_with_fallback or {}
    suggestions = improvement.suggestions or []
    applied_indices = list(improvement.applied_indices or [])
    rejected_indices = set(improvement.rejected_indices or [])

    results: list[dict] = []
    newly_applied: list[int] = []
    new_workflow_ids: list[int] = []

    for idx, suggestion in enumerate(suggestions):
        if idx in applied_indices or idx in rejected_indices:
            continue
        outcome = await _apply_single_suggestion(
            suggestion=suggestion,
            wf_def=wf_def,
            workflow_name=workflow.name,
            workflow_id=workflow_id,
            user=user,
            workflow_configurations=workflow.workflow_configurations or {},
        )
        outcome["index"] = idx
        results.append(outcome)
        if outcome.get("applied"):
            newly_applied.append(idx)
            if outcome.get("new_workflow_id"):
                new_workflow_ids.append(outcome["new_workflow_id"])

    if any(o.get("applied") and o.get("kind") != "spawn_workflow" for o in results):
        await db_client.update_workflow(
            workflow_id=workflow_id,
            name=workflow.name,
            workflow_definition=wf_def,
            template_context_variables=None,
            workflow_configurations=None,
            organization_id=user.selected_organization_id,
        )

    final_applied = sorted(set(applied_indices) | set(newly_applied))
    await db_client.update_improvement_decision(
        improvement_id=improvement_id,
        applied_indices=final_applied,
        rejected_indices=sorted(rejected_indices),
    )

    new_status = "accepted" if (len(final_applied) + len(rejected_indices)) >= len(suggestions) else "pending"
    if new_status == "accepted":
        await db_client.update_improvement_status(improvement_id, "accepted")

    return {
        "status": new_status,
        "applied_count": len(newly_applied),
        "results": results,
        "new_workflow_ids": new_workflow_ids,
    }


@router.post("/{workflow_id}/improvements/{improvement_id}/suggestions/{index}/apply")
@limiter.limit(RateLimitTiers.LOW)
async def apply_single_improvement_suggestion(
    request: Request,
    workflow_id: int,
    improvement_id: int,
    index: int,
    user: UserModel = Depends(get_user),
):
    """Apply ONE suggestion from an improvement batch (per-row accept)."""
    improvement = await db_client.get_improvement_by_id(improvement_id)
    if not improvement or improvement.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="Improvement not found")

    suggestions = improvement.suggestions or []
    if index < 0 or index >= len(suggestions):
        raise HTTPException(status_code=404, detail="Suggestion index out of range")

    applied_indices = set(improvement.applied_indices or [])
    rejected_indices = set(improvement.rejected_indices or [])
    if index in applied_indices:
        return {"status": "already_applied", "index": index}
    if index in rejected_indices:
        raise HTTPException(status_code=400, detail="Suggestion was already rejected")

    workflow = await db_client.get_workflow_by_id(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    wf_def = workflow.workflow_definition_with_fallback or {}

    outcome = await _apply_single_suggestion(
        suggestion=suggestions[index],
        wf_def=wf_def,
        workflow_name=workflow.name,
        workflow_id=workflow_id,
        user=user,
        workflow_configurations=workflow.workflow_configurations or {},
    )

    if not outcome.get("applied"):
        raise HTTPException(status_code=400, detail=outcome.get("reason") or "Could not apply suggestion")

    if outcome.get("kind") != "spawn_workflow":
        await db_client.update_workflow(
            workflow_id=workflow_id,
            name=workflow.name,
            workflow_definition=wf_def,
            template_context_variables=None,
            workflow_configurations=None,
            organization_id=user.selected_organization_id,
        )

    applied_indices.add(index)
    await db_client.update_improvement_decision(
        improvement_id=improvement_id,
        applied_indices=sorted(applied_indices),
        rejected_indices=sorted(rejected_indices),
    )

    updated = await db_client.get_improvement_by_id(improvement_id)
    if updated and _is_batch_settled(updated) and updated.status == "pending":
        await db_client.update_improvement_status(improvement_id, "accepted")

    outcome["index"] = index
    return outcome


@router.post("/{workflow_id}/improvements/{improvement_id}/suggestions/{index}/reject")
@limiter.limit(RateLimitTiers.LOW)
async def reject_single_improvement_suggestion(
    request: Request,
    workflow_id: int,
    improvement_id: int,
    index: int,
    user: UserModel = Depends(get_user),
):
    """Reject ONE suggestion from an improvement batch (per-row dismiss)."""
    improvement = await db_client.get_improvement_by_id(improvement_id)
    if not improvement or improvement.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="Improvement not found")

    suggestions = improvement.suggestions or []
    if index < 0 or index >= len(suggestions):
        raise HTTPException(status_code=404, detail="Suggestion index out of range")

    applied_indices = set(improvement.applied_indices or [])
    rejected_indices = set(improvement.rejected_indices or [])
    if index in rejected_indices:
        return {"status": "already_rejected", "index": index}
    if index in applied_indices:
        raise HTTPException(status_code=400, detail="Suggestion was already applied")

    rejected_indices.add(index)
    await db_client.update_improvement_decision(
        improvement_id=improvement_id,
        applied_indices=sorted(applied_indices),
        rejected_indices=sorted(rejected_indices),
    )

    updated = await db_client.get_improvement_by_id(improvement_id)
    if updated and _is_batch_settled(updated) and updated.status == "pending":
        # Settled = every suggestion decided. If all were rejected, mark the batch
        # as rejected; otherwise (mix or all accepted), mark accepted.
        final_status = "rejected" if len(updated.applied_indices or []) == 0 else "accepted"
        await db_client.update_improvement_status(improvement_id, final_status)

    return {"status": "rejected", "index": index}


@router.post("/{workflow_id}/improvements/{improvement_id}/reject")
@limiter.limit(RateLimitTiers.LOW)
async def reject_improvement(
    request: Request,
    workflow_id: int,
    improvement_id: int,
    user: UserModel = Depends(get_user),
):
    """Reject/dismiss every still-undecided suggestion in the batch."""
    improvement = await db_client.get_improvement_by_id(improvement_id)
    if not improvement or improvement.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="Improvement not found")

    suggestions = improvement.suggestions or []
    applied_indices = set(improvement.applied_indices or [])
    rejected_indices = set(improvement.rejected_indices or [])

    for idx in range(len(suggestions)):
        if idx not in applied_indices and idx not in rejected_indices:
            rejected_indices.add(idx)

    await db_client.update_improvement_decision(
        improvement_id=improvement_id,
        applied_indices=sorted(applied_indices),
        rejected_indices=sorted(rejected_indices),
    )

    final_status = "rejected" if not applied_indices else "accepted"
    await db_client.update_improvement_status(improvement_id, final_status)
    return {"status": final_status}


# ──────────────────────────────────────────────────────────────────────────────
# Shareable Test Link endpoints
# ──────────────────────────────────────────────────────────────────────────────


class ShareLinkRequest(BaseModel):
    expires_days: Optional[int] = 7
    usage_limit: Optional[int] = None


class ShareLinkResponse(BaseModel):
    token: str
    share_url: str
    expires_at: Optional[str] = None
    usage_limit: Optional[int] = None


@router.post("/{workflow_id}/share", response_model=ShareLinkResponse)
@limiter.limit(RateLimitTiers.STANDARD)
async def create_share_link(
    request: Request,
    workflow_id: int,
    body: ShareLinkRequest,
    user: UserModel = Depends(get_user),
):
    """Generate a shareable public test link for the workflow."""
    from datetime import timedelta, UTC
    from api.constants import (
        EMBED_DEFAULT_EXPIRY_DAYS,
        EMBED_MAX_EXPIRY_DAYS,
        EMBED_MAX_USAGE_LIMIT,
        UI_APP_URL,
    )

    workflow = await db_client.get_workflow(workflow_id, user.id)
    if not workflow or workflow.organization_id != user.selected_organization_id:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Anonymous share links must always expire and are bounded server-side so a
    # leaked link cannot be used indefinitely or to run unbounded sessions.
    requested_days = body.expires_days or EMBED_DEFAULT_EXPIRY_DAYS
    expiry_days = max(1, min(requested_days, EMBED_MAX_EXPIRY_DAYS))
    expires_at = datetime.now(UTC) + timedelta(days=expiry_days)

    requested_limit = body.usage_limit or EMBED_MAX_USAGE_LIMIT
    usage_limit = max(1, min(requested_limit, EMBED_MAX_USAGE_LIMIT))

    token_obj = await db_client.create_embed_token(
        workflow_id=workflow_id,
        organization_id=user.selected_organization_id,
        created_by=user.id,
        allowed_domains=None,
        settings={"mode": "share_link"},
        usage_limit=usage_limit,
        expires_at=expires_at,
    )

    share_url = f"{UI_APP_URL}/share/{token_obj.token}"

    return ShareLinkResponse(
        token=token_obj.token,
        share_url=share_url,
        expires_at=token_obj.expires_at.isoformat() if token_obj.expires_at else None,
        usage_limit=usage_limit,
    )
