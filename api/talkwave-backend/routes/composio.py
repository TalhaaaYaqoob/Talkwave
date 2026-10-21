"""
Composio Integration API Routes.
Handles OAuth connections, app management, and action execution.

Updated: Uses SDK-based service for Composio integration.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.integrations.composio_service import (
    composio_service,
    database_service,
    ComposioConnectionStatus,
    ConnectionStatus,
)

router = APIRouter(prefix="/composio", tags=["Composio Integrations"])


# =============================================================================
# Pydantic Models
# =============================================================================

class AppInfo(BaseModel):
    """App information."""
    id: str
    name: str
    description: str
    category: str
    icon: str
    logo: Optional[str] = None  # URL to the app's logo image
    color: str
    auth_mode: str = "oauth"
    is_connected: bool = False
    status: str = "NOT_CONNECTED"  # ACTIVE, PENDING, FAILED, INACTIVE, NOT_CONNECTED
    connected_at: Optional[str] = None


class CategoryInfo(BaseModel):
    """Category information."""
    id: str
    name: str
    description: str


class ConnectRequest(BaseModel):
    """Request to connect an app."""
    app_id: str
    redirect_url: Optional[str] = None
    credentials: Optional[Dict[str, Any]] = None  # For API key based auth


class ConnectResponse(BaseModel):
    """Response with connection details."""
    redirect_url: str
    connection_id: str
    requires_credentials: bool = False


class OAuthCallbackRequest(BaseModel):
    """OAuth callback request."""
    app_id: str
    connected_account_id: str  # The ID returned from Composio after OAuth


class DisconnectRequest(BaseModel):
    """Request to disconnect an app."""
    app_id: str


class ExecuteActionRequest(BaseModel):
    """Request to execute an action."""
    app_id: str
    action_name: str
    params: Dict[str, Any] = Field(default_factory=dict)


class ExecuteActionResponse(BaseModel):
    """Response from action execution."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class SupabaseQueryRequest(BaseModel):
    """Request to execute Supabase query."""
    table: str
    operation: str  # select, insert, update, delete
    data: Optional[Dict[str, Any]] = None
    filters: Optional[Dict[str, Any]] = None


class MySQLQueryRequest(BaseModel):
    """Request to execute MySQL query."""
    query: str
    params: Optional[List[Any]] = None


class AppSettingsRequest(BaseModel):
    """Request to save app-specific settings (spreadsheet, table, channel, etc.)."""
    settings: Dict[str, Any]


class DatabaseCredentialsRequest(BaseModel):
    """Request to save database credentials."""
    database_type: str  # supabase, mysql
    credentials: Dict[str, Any]
    is_enabled: bool = True


# =============================================================================
# Apps & Categories
# =============================================================================

@router.get("/apps")
async def get_apps(
    user: UserModel = Depends(get_user),
) -> List[AppInfo]:
    """Get all available apps with connection status."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    # Get connection statuses
    connections = await composio_service.get_connected_accounts(
        user.selected_organization_id
    )
    connection_map = {c.app_id: c for c in connections}

    # Merged catalog: curated metadata + full Composio app catalog
    app_defs = await composio_service.get_all_app_definitions()

    apps = []
    for app_id, app_info in app_defs.items():
        conn = connection_map.get(app_id)
        apps.append(AppInfo(
            id=app_id,
            name=app_info.get("name", app_id),
            description=app_info.get("description", ""),
            category=app_info.get("category", "other"),
            icon=app_info.get("icon", "cloud"),
            logo=app_info.get("logo"),  # Include logo URL
            color=app_info.get("color", "#6366F1"),
            auth_mode=app_info.get("auth_mode", "oauth"),
            is_connected=conn.is_connected if conn else False,
            status=conn.status.value if conn else "NOT_CONNECTED",
            connected_at=conn.connected_at.isoformat() if conn and conn.connected_at else None,
        ))

    return apps


@router.get("/categories")
async def get_categories() -> List[CategoryInfo]:
    """Get all app categories (including ones discovered dynamically)."""
    categories = await composio_service.get_categories()
    return [
        CategoryInfo(id=cat_id, **cat_info)
        for cat_id, cat_info in categories.items()
    ]


@router.get("/apps/{app_id}/status")
async def get_app_status(
    app_id: str,
    user: UserModel = Depends(get_user),
) -> ComposioConnectionStatus:
    """Get connection status for a specific app."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    app_info = await composio_service.get_app_info(app_id)
    if not app_info:
        raise HTTPException(status_code=400, detail=f"Unknown app: {app_id}")
    
    connections = await composio_service.get_connected_accounts(
        user.selected_organization_id
    )
    
    for conn in connections:
        if conn.app_id == app_id:
            return conn
    
    return ComposioConnectionStatus(
        app_id=app_id,
        app_name=app_info["name"],
        is_connected=False,
    )


# =============================================================================
# OAuth Connection Flow
# =============================================================================

@router.post("/connect")
async def initiate_connection(
    request: ConnectRequest,
    user: UserModel = Depends(get_user),
) -> ConnectResponse:
    """
    Initiate connection for an app.
    For OAuth apps: returns redirect URL
    For API key apps: saves credentials directly
    """
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    app_info = await composio_service.get_app_info(request.app_id)
    if not app_info:
        raise HTTPException(status_code=400, detail=f"Unknown app: {request.app_id}")
    
    # Handle API key based auth
    if app_info.get("auth_mode") in ["api_key", "credentials"] or app_info.get("direct"):
        if request.credentials:
            # Save credentials directly
            success = await composio_service.save_api_credentials(
                organization_id=user.selected_organization_id,
                user_id=user.id,
                app_id=request.app_id,
                credentials=request.credentials,
            )
            if success:
                return ConnectResponse(
                    redirect_url="",
                    connection_id=f"credentials_{request.app_id}",
                    requires_credentials=False,
                )
            else:
                raise HTTPException(status_code=500, detail="Failed to save credentials")
        else:
            # Need credentials from user
            return ConnectResponse(
                redirect_url="",
                connection_id="",
                requires_credentials=True,
            )
    
    # OAuth based auth
    try:
        result = await composio_service.initiate_connection(
            organization_id=user.selected_organization_id,
            user_id=user.id,
            app_id=request.app_id,
            redirect_url=request.redirect_url,
        )
        
        return ConnectResponse(
            redirect_url=result.redirect_url,
            connection_id=result.connection_id,
            requires_credentials=False,
        )
        
    except ValueError as e:
        error_msg = str(e)
        logger.error(f"Error initiating connection: {error_msg}")

        # For OAuth apps we must NOT silently fall back to an API-key form —
        # that confuses users into thinking Gmail/Slack/etc. need a manual key.
        # Surface a clear, actionable error instead.
        if "COMPOSIO_API_KEY" in error_msg:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Composio is not configured on the server. Set COMPOSIO_API_KEY "
                    "in the backend environment to enable OAuth connections. "
                    "Get a key from https://app.composio.dev"
                ),
            )

        raise HTTPException(status_code=400, detail=error_msg)
    except Exception as e:
        logger.error(f"Error initiating connection: {e}")
        raise HTTPException(status_code=500, detail="Failed to initiate connection")


@router.post("/callback")
async def handle_oauth_callback(
    request: OAuthCallbackRequest,
    user: UserModel = Depends(get_user),
) -> Dict[str, Any]:
    """Handle OAuth callback after user authorizes."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    success = await composio_service.handle_oauth_callback(
        organization_id=user.selected_organization_id,
        user_id=user.id,
        app_id=request.app_id,
        connected_account_id=request.connected_account_id,
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to complete connection")
    
    app_info = await composio_service.get_app_info(request.app_id)
    app_name = app_info["name"] if app_info else request.app_id
    return {
        "success": True,
        "message": f"{app_name} connected successfully",
    }


@router.get("/apps/{app_id}/check-status")
async def check_connection_status(
    app_id: str,
    connection_id: str,
    user: UserModel = Depends(get_user),
) -> Dict[str, Any]:
    """Check connection status for polling after OAuth redirect."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    if not await composio_service.get_app_info(app_id):
        raise HTTPException(status_code=400, detail=f"Unknown app: {app_id}")
    
    status = await composio_service.check_connection_status(
        organization_id=user.selected_organization_id,
        app_id=app_id,
        connection_id=connection_id,
    )
    
    return {
        "status": status.value,
        "is_connected": status == ConnectionStatus.ACTIVE,
    }


@router.post("/disconnect")
async def disconnect_app(
    request: DisconnectRequest,
    user: UserModel = Depends(get_user),
) -> Dict[str, str]:
    """Disconnect an app."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    app_info = await composio_service.get_app_info(request.app_id)
    if not app_info:
        raise HTTPException(status_code=400, detail=f"Unknown app: {request.app_id}")
    
    success = await composio_service.disconnect_app(
        organization_id=user.selected_organization_id,
        app_id=request.app_id,
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to disconnect app")
    
    return {"message": f"{app_info['name']} disconnected successfully"}


# =============================================================================
# Action Execution
# =============================================================================

@router.get("/apps/{app_id}/actions")
async def get_app_actions(
    app_id: str,
    user: UserModel = Depends(get_user),
) -> List[Dict[str, Any]]:
    """Get available actions for an app."""
    if not await composio_service.get_app_info(app_id):
        raise HTTPException(status_code=400, detail=f"Unknown app: {app_id}")
    
    actions = await composio_service.get_available_actions(app_id)
    return actions


@router.post("/execute")
async def execute_action(
    request: ExecuteActionRequest,
    user: UserModel = Depends(get_user),
) -> ExecuteActionResponse:
    """Execute an action on a connected app."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    result = await composio_service.execute_action(
        organization_id=user.selected_organization_id,
        app_id=request.app_id,
        action_name=request.action_name,
        params=request.params,
    )
    
    return result


# =============================================================================
# App Settings (post-connection configuration)
# =============================================================================

@router.get("/apps/{app_id}/settings")
async def get_app_settings(
    app_id: str,
    user: UserModel = Depends(get_user),
) -> Dict[str, Any]:
    """Get app-specific settings.

    Integration-level app settings are deprecated. Tool configuration now lives
    in Agent/Action nodes, so this endpoint returns an empty settings payload.
    """
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    if not await composio_service.get_app_info(app_id):
        raise HTTPException(status_code=400, detail=f"Unknown app: {app_id}")

    return {
        "app_id": app_id,
        "settings": {},
        "message": "Integration-level app settings are disabled. Configure tools in Agent/Action nodes.",
    }


@router.put("/apps/{app_id}/settings")
async def save_app_settings(
    app_id: str,
    request: AppSettingsRequest,
    user: UserModel = Depends(get_user),
) -> Dict[str, str]:
    """Save app-specific settings.

    Integration-level app settings are deprecated and no longer persisted.
    Tool configuration should be set on Agent/Action nodes.
    """
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    app_info = await composio_service.get_app_info(app_id)
    if not app_info:
        raise HTTPException(status_code=400, detail=f"Unknown app: {app_id}")

    logger.info(
        f"Ignoring deprecated app settings save for '{app_id}' in org "
        f"{user.selected_organization_id}: {request.settings}"
    )
    return {
        "message": (
            f"Integration-level settings for {app_info['name']} are disabled. "
            "Configure this integration in Agent/Action nodes."
        )
    }


# =============================================================================
# Database Operations (Direct, not via Composio)
# =============================================================================

@router.post("/database/credentials")
async def save_database_credentials(
    request: DatabaseCredentialsRequest,
    user: UserModel = Depends(get_user),
) -> Dict[str, str]:
    """Save database credentials for Supabase or MySQL."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    if request.database_type not in ["supabase", "mysql", "mongodb", "firebase"]:
        raise HTTPException(status_code=400, detail="Invalid database type")
    
    from api.db import db_client as dbc
    
    key = f"integration_{request.database_type}"
    value = {
        "credentials": request.credentials,
        "is_enabled": request.is_enabled,
    }
    
    await dbc.upsert_configuration(
        user.selected_organization_id,
        key,
        value,
    )
    
    # Also mark in composio connections
    await composio_service.save_api_credentials(
        organization_id=user.selected_organization_id,
        user_id=user.id,
        app_id=request.database_type,
        credentials=request.credentials,
    )
    
    return {"message": f"{request.database_type.capitalize()} credentials saved successfully"}


@router.get("/database/{database_type}/status")
async def get_database_status(
    database_type: str,
    user: UserModel = Depends(get_user),
) -> Dict[str, Any]:
    """Check if database is configured."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    if database_type not in ["supabase", "mysql", "mongodb", "firebase"]:
        raise HTTPException(status_code=400, detail="Invalid database type")
    
    from api.db import db_client as dbc
    
    key = f"integration_{database_type}"
    config = await dbc.get_configuration(user.selected_organization_id, key)
    
    if config and config.value:
        return {
            "is_configured": True,
            "is_enabled": config.value.get("is_enabled", True),
        }
    
    return {"is_configured": False, "is_enabled": False}


@router.post("/database/supabase/query")
async def execute_supabase_query(
    request: SupabaseQueryRequest,
    user: UserModel = Depends(get_user),
) -> Dict[str, Any]:
    """Execute a Supabase query."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    result = await database_service.execute_supabase_query(
        organization_id=user.selected_organization_id,
        table=request.table,
        operation=request.operation,
        data=request.data,
        filters=request.filters,
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Query failed"))
    
    return result


@router.post("/database/mysql/query")
async def execute_mysql_query(
    request: MySQLQueryRequest,
    user: UserModel = Depends(get_user),
) -> Dict[str, Any]:
    """Execute a MySQL query."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    result = await database_service.execute_mysql_query(
        organization_id=user.selected_organization_id,
        query=request.query,
        params=request.params,
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Query failed"))
    
    return result


@router.delete("/database/{database_type}")
async def delete_database_credentials(
    database_type: str,
    user: UserModel = Depends(get_user),
) -> Dict[str, str]:
    """Delete database credentials."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    if database_type not in ["supabase", "mysql", "mongodb", "firebase"]:
        raise HTTPException(status_code=400, detail="Invalid database type")
    
    from api.db import db_client as dbc
    
    key = f"integration_{database_type}"
    deleted = await dbc.delete_configuration(user.selected_organization_id, key)
    
    # Also remove from composio connections
    await composio_service.disconnect_app(user.selected_organization_id, database_type)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Database not configured")
    
    return {"message": f"{database_type.capitalize()} credentials deleted successfully"}
