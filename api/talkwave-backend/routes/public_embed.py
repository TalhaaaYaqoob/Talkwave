"""
Public Embed API Routes

Manages embed tokens for workflows and initializes public voice sessions.
Users generate an embed token for a workflow, then embed a widget on their
website using that token.  The widget calls /init to create a session,
then connects via the public WebSocket signaling endpoint.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.security.rate_limiter import limiter, RateLimitTiers

router = APIRouter(prefix="/embed", tags=["embed"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class EmbedTokenRequest(BaseModel):
    workflow_id: int
    allowed_domains: Optional[List[str]] = None
    settings: Optional[dict] = None
    usage_limit: Optional[int] = None
    expires_days: Optional[int] = None


class EmbedTokenResponse(BaseModel):
    id: int
    token: str
    workflow_id: int
    allowed_domains: Optional[list] = None
    settings: Optional[dict] = None
    is_active: bool
    usage_count: int
    usage_limit: Optional[int] = None
    created_at: str
    expires_at: Optional[str] = None
    embed_snippet: str


class InitEmbedRequest(BaseModel):
    token: str


class InitEmbedResponse(BaseModel):
    session_token: str
    workflow_run_id: int
    websocket_url: str
    expires_at: str


class EmbedConfigResponse(BaseModel):
    workflow_name: str
    settings: dict


# ---------------------------------------------------------------------------
# Authenticated endpoints (manage embed tokens)
# ---------------------------------------------------------------------------

def _build_snippet(token: str, backend_url: str) -> str:
    """Generate a copy-paste embed snippet for the user."""
    return (
        f'<script src="{backend_url}/static/embed-widget.js" '
        f'data-token="{token}" async></script>'
    )


@router.post("/tokens", response_model=EmbedTokenResponse)
@limiter.limit(RateLimitTiers.STANDARD)
async def create_embed_token(
    request: Request,
    body: EmbedTokenRequest,
    user: UserModel = Depends(get_user),
):
    """Create a new embed token for a workflow."""
    from api.constants import BACKEND_API_ENDPOINT

    workflow = await db_client.get_workflow(body.workflow_id, user.id)
    if not workflow or workflow.organization_id != user.selected_organization_id:
        raise HTTPException(status_code=404, detail="Workflow not found")

    expires_at = None
    if body.expires_days:
        expires_at = datetime.now(UTC) + timedelta(days=body.expires_days)

    token_obj = await db_client.create_embed_token(
        workflow_id=body.workflow_id,
        organization_id=user.selected_organization_id,
        created_by=user.id,
        allowed_domains=body.allowed_domains,
        settings=body.settings or {},
        usage_limit=body.usage_limit,
        expires_at=expires_at,
    )

    return EmbedTokenResponse(
        id=token_obj.id,
        token=token_obj.token,
        workflow_id=token_obj.workflow_id,
        allowed_domains=token_obj.allowed_domains,
        settings=token_obj.settings,
        is_active=token_obj.is_active,
        usage_count=token_obj.usage_count,
        usage_limit=token_obj.usage_limit,
        created_at=token_obj.created_at.isoformat(),
        expires_at=token_obj.expires_at.isoformat() if token_obj.expires_at else None,
        embed_snippet=_build_snippet(token_obj.token, BACKEND_API_ENDPOINT),
    )


@router.get("/tokens/{workflow_id}", response_model=List[EmbedTokenResponse])
@limiter.limit(RateLimitTiers.STANDARD)
async def list_embed_tokens(
    request: Request,
    workflow_id: int,
    user: UserModel = Depends(get_user),
):
    """List embed tokens for a workflow."""
    from api.constants import BACKEND_API_ENDPOINT

    tokens = await db_client.get_embed_tokens_by_workflow(
        workflow_id=workflow_id,
        organization_id=user.selected_organization_id,
        active_only=False,
    )
    return [
        EmbedTokenResponse(
            id=t.id,
            token=t.token,
            workflow_id=t.workflow_id,
            allowed_domains=t.allowed_domains,
            settings=t.settings,
            is_active=t.is_active,
            usage_count=t.usage_count,
            usage_limit=t.usage_limit,
            created_at=t.created_at.isoformat(),
            expires_at=t.expires_at.isoformat() if t.expires_at else None,
            embed_snippet=_build_snippet(t.token, BACKEND_API_ENDPOINT),
        )
        for t in tokens
    ]


@router.delete("/tokens/{token_id}")
@limiter.limit(RateLimitTiers.STANDARD)
async def deactivate_embed_token(
    request: Request,
    token_id: int,
    user: UserModel = Depends(get_user),
):
    """Deactivate an embed token."""
    ok = await db_client.deactivate_embed_token(token_id, user.selected_organization_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"success": True}


# ---------------------------------------------------------------------------
# Public endpoints (no auth — validated via embed token)
# ---------------------------------------------------------------------------

@router.post("/init", response_model=InitEmbedResponse)
@limiter.limit(RateLimitTiers.PUBLIC)
async def initialize_embed_session(
    request: Request,
    body: InitEmbedRequest,
):
    """Initialize a public voice session from an embed token.

    This is called by the widget loaded on the customer's website.
    It validates the token, creates a workflow run, and returns a
    session token for the public WebSocket signaling endpoint.
    """
    from api.constants import BACKEND_API_ENDPOINT

    token_obj = await db_client.get_embed_token_by_token(body.token)
    if not token_obj or not token_obj.is_active:
        raise HTTPException(status_code=403, detail="Invalid or inactive embed token")

    # Check expiry
    if token_obj.expires_at and token_obj.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=403, detail="Embed token has expired")

    # Check usage limit
    if token_obj.usage_limit and token_obj.usage_count >= token_obj.usage_limit:
        raise HTTPException(status_code=429, detail="Embed token usage limit reached")

    # Concurrency cap: limit simultaneously-active sessions per token so a
    # single public link cannot be used to spin up unbounded parallel
    # (cost-incurring) voice sessions.
    from api.constants import EMBED_MAX_CONCURRENT_SESSIONS

    active_sessions = await db_client.count_active_embed_sessions(token_obj.id)
    if active_sessions >= EMBED_MAX_CONCURRENT_SESSIONS:
        raise HTTPException(
            status_code=429,
            detail="Too many active sessions for this link. Please try again later.",
        )

    # Domain validation
    origin = request.headers.get("origin", "")
    if token_obj.allowed_domains:
        from urllib.parse import urlparse
        origin_host = urlparse(origin).hostname or ""
        if not any(
            origin_host == d or origin_host.endswith(f".{d}")
            for d in token_obj.allowed_domains
        ):
            raise HTTPException(status_code=403, detail="Domain not allowed for this embed token")

    # Create a workflow run for this session
    creator = await db_client.get_user_by_id(token_obj.created_by)
    if not creator:
        raise HTTPException(status_code=500, detail="Token creator not found")

    workflow = await db_client.get_workflow(token_obj.workflow_id, creator.id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow_run = await db_client.create_workflow_run(
        name=f"Embed Session ({origin or 'unknown'})",
        workflow_id=token_obj.workflow_id,
        mode="browser",
        user_id=creator.id,
    )

    # Create embed session
    session_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    await db_client.create_embed_session(
        session_token=session_token,
        embed_token_id=token_obj.id,
        workflow_run_id=workflow_run.id,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        origin=origin,
        expires_at=expires_at,
    )

    # Increment usage
    await db_client.increment_embed_token_usage(token_obj.id)

    ws_scheme = "wss" if "https" in BACKEND_API_ENDPOINT else "ws"
    ws_base = BACKEND_API_ENDPOINT.replace("https://", "").replace("http://", "")
    websocket_url = f"{ws_scheme}://{ws_base}/api/v1/ws/public/signaling/{session_token}"

    return InitEmbedResponse(
        session_token=session_token,
        workflow_run_id=workflow_run.id,
        websocket_url=websocket_url,
        expires_at=expires_at.isoformat(),
    )


@router.get("/config/{token}")
async def get_embed_config(token: str):
    """Get widget configuration for an embed token (public, no auth)."""
    token_obj = await db_client.get_embed_token_by_token(token)
    if not token_obj or not token_obj.is_active:
        raise HTTPException(status_code=404, detail="Token not found")

    workflow = await db_client.get_workflow_by_id(token_obj.workflow_id)
    workflow_name = workflow.name if workflow else "Voice Assistant"

    return EmbedConfigResponse(
        workflow_name=workflow_name,
        settings=token_obj.settings or {},
    )
