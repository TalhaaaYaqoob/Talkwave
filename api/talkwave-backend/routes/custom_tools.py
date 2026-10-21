"""
API Routes for Custom Tools

Provides endpoints for:
- Managing custom tools (CRUD)
- Managing webhook endpoints
- Testing tools in the playground
- Getting tool schemas for workflows
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from api.db.custom_tools_client import custom_tools_client
from api.db.models import UserModel
from api.enums import ExecutionStatus, HttpMethod, ToolType
from api.services.auth.depends import get_user
from api.services.custom_tools import tool_executor, tool_registry
from api.services.subscription.subscription_service import SubscriptionService

router = APIRouter(prefix="/custom-tools")

# Subscription service for feature gating
_sub_service = SubscriptionService()


# =============================================================================
# Request/Response Models
# =============================================================================


class CreateToolRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    tool_type: ToolType
    configuration: Dict[str, Any] = Field(default_factory=dict)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Optional[Dict[str, Any]] = None
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    retry_config: Optional[Dict[str, Any]] = None


class UpdateToolRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, min_length=1)
    configuration: Optional[Dict[str, Any]] = None
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    timeout_seconds: Optional[int] = Field(None, ge=1, le=300)
    retry_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class ToolResponse(BaseModel):
    id: int
    organization_id: int
    name: str
    display_name: str
    description: str
    tool_type: str
    configuration: Dict[str, Any]
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]]
    is_active: bool
    is_system: bool
    timeout_seconds: int
    retry_config: Optional[Dict[str, Any]]
    created_by: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]


class ToolListResponse(BaseModel):
    tools: List[ToolResponse]
    total: int
    page: int
    limit: int


class TestToolRequest(BaseModel):
    input_data: Dict[str, Any] = Field(default_factory=dict)
    context_vars: Optional[Dict[str, Any]] = None


class TestToolResponse(BaseModel):
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    execution_time_ms: int


class ToolSchemaResponse(BaseModel):
    tools: List[Dict[str, Any]]


# Webhook Endpoints Models
class CreateWebhookEndpointRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    endpoint_url: str = Field(..., min_length=1)
    http_method: HttpMethod = HttpMethod.POST
    headers: Optional[Dict[str, str]] = None
    auth_type: Optional[str] = None
    auth_config: Optional[Dict[str, Any]] = None


class UpdateWebhookEndpointRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    endpoint_url: Optional[str] = Field(None, min_length=1)
    http_method: Optional[HttpMethod] = None
    headers: Optional[Dict[str, str]] = None
    auth_type: Optional[str] = None
    auth_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class WebhookEndpointResponse(BaseModel):
    id: int
    organization_id: int
    name: str
    endpoint_url: str
    http_method: str
    headers: Optional[Dict[str, str]]
    auth_type: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]


class ExecutionHistoryResponse(BaseModel):
    id: int
    tool_id: int
    workflow_run_id: Optional[int]
    status: str
    input_data: Optional[Dict[str, Any]]
    output_data: Optional[Dict[str, Any]]
    error_message: Optional[str]
    execution_time_ms: Optional[int]
    created_at: datetime
    completed_at: Optional[datetime]


# =============================================================================
# Subscription helper
# =============================================================================


async def _require_custom_tools_access(organization_id: int) -> None:
    """Check that the organization's plan allows custom tools access.

    Raises HTTPException(403) if the plan doesn't include custom tools.
    """
    from api.services.subscription.plans import get_plan

    sub = await _sub_service.get_or_create_subscription(organization_id)
    plan_features = get_plan(sub.plan)
    if not plan_features.custom_tools_enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "subscription_limit",
                "reason": "custom_tools_not_available",
                "message": "Custom tools are not available on your current plan. Please upgrade to Plus or Pro.",
            },
        )


# =============================================================================
# Custom Tools Endpoints
# =============================================================================


@router.post("/", response_model=ToolResponse)
async def create_tool(
    request: CreateToolRequest,
    user: UserModel = Depends(get_user),
):
    """Create a new custom tool."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    # Check subscription allows custom tools (Plus or Pro only)
    await _require_custom_tools_access(user.selected_organization_id)

    # Validate configuration
    is_valid, error = await tool_registry.validate_tool_configuration(
        request.tool_type, request.configuration
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid configuration: {error}")

    # Check if tool name already exists
    existing = await custom_tools_client.get_tool_by_name(
        request.name, user.selected_organization_id
    )
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Tool with name '{request.name}' already exists"
        )

    tool = await custom_tools_client.create_tool(
        organization_id=user.selected_organization_id,
        name=request.name,
        display_name=request.display_name,
        description=request.description,
        tool_type=request.tool_type,
        configuration=request.configuration,
        input_schema=request.input_schema,
        output_schema=request.output_schema,
        timeout_seconds=request.timeout_seconds,
        retry_config=request.retry_config,
        created_by=user.id,
    )

    # Clear cache
    tool_registry.clear_cache(user.selected_organization_id)

    return _tool_to_response(tool)


@router.get("/", response_model=ToolListResponse)
async def list_tools(
    tool_type: Optional[ToolType] = None,
    is_active: Optional[bool] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user: UserModel = Depends(get_user),
):
    """List all custom tools for the organization."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    await _require_custom_tools_access(user.selected_organization_id)

    offset = (page - 1) * limit
    tools, total = await custom_tools_client.get_all_tools(
        organization_id=user.selected_organization_id,
        tool_type=tool_type,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )

    return ToolListResponse(
        tools=[_tool_to_response(t) for t in tools],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/schemas", response_model=ToolSchemaResponse)
async def get_tool_schemas(
    tool_ids: Optional[str] = Query(None, description="Comma-separated tool IDs"),
    user: UserModel = Depends(get_user),
):
    """Get tool schemas for LLM function calling."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    tool_id_list = None
    if tool_ids:
        try:
            tool_id_list = [int(id.strip()) for id in tool_ids.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid tool IDs format")

    schemas = await tool_registry.get_tool_schemas_for_llm(
        user.selected_organization_id, tool_id_list
    )

    return ToolSchemaResponse(tools=schemas)


@router.get("/{tool_id}", response_model=ToolResponse)
async def get_tool(
    tool_id: int,
    user: UserModel = Depends(get_user),
):
    """Get a specific custom tool."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    tool = await custom_tools_client.get_tool(tool_id, user.selected_organization_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    return _tool_to_response(tool)


@router.put("/{tool_id}", response_model=ToolResponse)
async def update_tool(
    tool_id: int,
    request: UpdateToolRequest,
    user: UserModel = Depends(get_user),
):
    """Update a custom tool."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    await _require_custom_tools_access(user.selected_organization_id)

    # Get existing tool to validate configuration
    existing = await custom_tools_client.get_tool(tool_id, user.selected_organization_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Tool not found")

    # Validate configuration if provided
    if request.configuration is not None:
        is_valid, error = await tool_registry.validate_tool_configuration(
            existing.tool_type, request.configuration
        )
        if not is_valid:
            raise HTTPException(status_code=400, detail=f"Invalid configuration: {error}")

    updates = request.model_dump(exclude_unset=True)
    
    try:
        tool = await custom_tools_client.update_tool(
            tool_id=tool_id,
            organization_id=user.selected_organization_id,
            **updates,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    # Clear cache
    tool_registry.clear_cache(user.selected_organization_id)

    return _tool_to_response(tool)


@router.delete("/{tool_id}")
async def delete_tool(
    tool_id: int,
    user: UserModel = Depends(get_user),
):
    """Delete a custom tool."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    await _require_custom_tools_access(user.selected_organization_id)

    try:
        deleted = await custom_tools_client.delete_tool(
            tool_id, user.selected_organization_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not deleted:
        raise HTTPException(status_code=404, detail="Tool not found")

    # Clear cache
    tool_registry.clear_cache(user.selected_organization_id)

    return {"status": "deleted"}


@router.post("/{tool_id}/test", response_model=TestToolResponse)
async def test_tool(
    tool_id: int,
    request: TestToolRequest,
    user: UserModel = Depends(get_user),
):
    """Test a custom tool with sample input."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    await _require_custom_tools_access(user.selected_organization_id)

    tool = await custom_tools_client.get_tool(tool_id, user.selected_organization_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    result = await tool_executor.test_tool(
        tool=tool,
        test_input=request.input_data,
        context_vars=request.context_vars,
    )

    return TestToolResponse(**result)


@router.get("/{tool_id}/executions", response_model=List[ExecutionHistoryResponse])
async def get_tool_executions(
    tool_id: int,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: UserModel = Depends(get_user),
):
    """Get execution history for a tool."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    tool = await custom_tools_client.get_tool(tool_id, user.selected_organization_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    executions = await custom_tools_client.get_tool_executions(
        tool_id=tool_id,
        limit=limit,
        offset=offset,
    )

    return [
        ExecutionHistoryResponse(
            id=e.id,
            tool_id=e.tool_id,
            workflow_run_id=e.workflow_run_id,
            status=e.status.value,
            input_data=e.input_data,
            output_data=e.output_data,
            error_message=e.error_message,
            execution_time_ms=e.execution_time_ms,
            created_at=e.created_at,
            completed_at=e.completed_at,
        )
        for e in executions
    ]


# =============================================================================
# Webhook Endpoints CRUD
# =============================================================================


@router.post("/webhooks/", response_model=WebhookEndpointResponse)
async def create_webhook_endpoint(
    request: CreateWebhookEndpointRequest,
    user: UserModel = Depends(get_user),
):
    """Create a new webhook endpoint."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    await _require_custom_tools_access(user.selected_organization_id)

    endpoint = await custom_tools_client.create_webhook_endpoint(
        organization_id=user.selected_organization_id,
        name=request.name,
        endpoint_url=request.endpoint_url,
        http_method=request.http_method,
        headers=request.headers,
        auth_type=request.auth_type,
        auth_config=request.auth_config,
    )

    return _webhook_to_response(endpoint)


@router.get("/webhooks/", response_model=List[WebhookEndpointResponse])
async def list_webhook_endpoints(
    user: UserModel = Depends(get_user),
):
    """List all webhook endpoints for the organization."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    endpoints = await custom_tools_client.get_all_webhook_endpoints(
        user.selected_organization_id
    )

    return [_webhook_to_response(e) for e in endpoints]


@router.get("/webhooks/{endpoint_id}", response_model=WebhookEndpointResponse)
async def get_webhook_endpoint(
    endpoint_id: int,
    user: UserModel = Depends(get_user),
):
    """Get a specific webhook endpoint."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    endpoint = await custom_tools_client.get_webhook_endpoint(
        endpoint_id, user.selected_organization_id
    )
    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    return _webhook_to_response(endpoint)


@router.put("/webhooks/{endpoint_id}", response_model=WebhookEndpointResponse)
async def update_webhook_endpoint(
    endpoint_id: int,
    request: UpdateWebhookEndpointRequest,
    user: UserModel = Depends(get_user),
):
    """Update a webhook endpoint."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    await _require_custom_tools_access(user.selected_organization_id)

    updates = request.model_dump(exclude_unset=True)
    
    endpoint = await custom_tools_client.update_webhook_endpoint(
        endpoint_id=endpoint_id,
        organization_id=user.selected_organization_id,
        **updates,
    )

    if not endpoint:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    return _webhook_to_response(endpoint)


@router.delete("/webhooks/{endpoint_id}")
async def delete_webhook_endpoint(
    endpoint_id: int,
    user: UserModel = Depends(get_user),
):
    """Delete a webhook endpoint."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    await _require_custom_tools_access(user.selected_organization_id)

    deleted = await custom_tools_client.delete_webhook_endpoint(
        endpoint_id, user.selected_organization_id
    )

    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    return {"status": "deleted"}


# =============================================================================
# Helper Functions
# =============================================================================


def _tool_to_response(tool) -> ToolResponse:
    """Convert a CustomToolModel to ToolResponse."""
    return ToolResponse(
        id=tool.id,
        organization_id=tool.organization_id,
        name=tool.name,
        display_name=tool.display_name,
        description=tool.description,
        tool_type=tool.tool_type.value,
        configuration=tool.configuration,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        is_active=tool.is_active,
        is_system=tool.is_system,
        timeout_seconds=tool.timeout_seconds,
        retry_config=tool.retry_config,
        created_by=tool.created_by,
        created_at=tool.created_at,
        updated_at=tool.updated_at,
    )


def _webhook_to_response(endpoint) -> WebhookEndpointResponse:
    """Convert a WebhookEndpointModel to WebhookEndpointResponse."""
    return WebhookEndpointResponse(
        id=endpoint.id,
        organization_id=endpoint.organization_id,
        name=endpoint.name,
        endpoint_url=endpoint.endpoint_url,
        http_method=endpoint.http_method.value,
        headers=endpoint.headers,
        auth_type=endpoint.auth_type,
        is_active=endpoint.is_active,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )





