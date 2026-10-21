"""
Simplified Integrations API Routes.
This provides a cleaner interface for the 6 essential integrations used in agentic workflows.
Uses the same storage as service_credentials but with a simpler API.

Also bridges Composio connections so workflow nodes see them as configured.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user
from api.services.integrations.composio_service import composio_service

router = APIRouter(prefix="/integrations", tags=["Integrations"])


# =============================================================================
# Integration Definitions - 6 Essential Tools
# =============================================================================

INTEGRATION_DEFINITIONS = {
    "twilio": {
        "name": "Twilio Voice & SMS",
        "description": "Make calls and send SMS messages using Twilio",
        "category": "messaging",
        "fields": [
            {"key": "account_sid", "label": "Account SID", "type": "text", "required": True},
            {"key": "auth_token", "label": "Auth Token", "type": "password", "required": True},
            {"key": "phone_number", "label": "Twilio Phone Number", "type": "text", "required": True},
        ],
    },
    "whatsapp": {
        "name": "WhatsApp Business",
        "description": "Send WhatsApp messages via Twilio WhatsApp API",
        "category": "messaging",
        "fields": [
            {"key": "account_sid", "label": "Twilio Account SID", "type": "text", "required": True},
            {"key": "auth_token", "label": "Twilio Auth Token", "type": "password", "required": True},
            {"key": "whatsapp_number", "label": "WhatsApp Number", "type": "text", "required": True},
        ],
    },
    "email_smtp": {
        "name": "Email (SMTP)",
        "description": "Send emails using any SMTP server",
        "category": "messaging",
        "fields": [
            {"key": "smtp_host", "label": "SMTP Host", "type": "text", "required": True},
            {"key": "smtp_port", "label": "SMTP Port", "type": "number", "required": True},
            {"key": "smtp_username", "label": "Username", "type": "email", "required": True},
            {"key": "smtp_password", "label": "Password / App Password", "type": "password", "required": True},
            {"key": "from_email", "label": "From Email", "type": "email", "required": True},
            {"key": "from_name", "label": "From Name", "type": "text", "required": False},
        ],
    },
    "google_sheets": {
        "name": "Google Sheets",
        "description": "Read and write data to Google Spreadsheets",
        "category": "productivity",
        "fields": [
            {"key": "service_account_json", "label": "Service Account JSON", "type": "textarea", "required": True},
        ],
    },
    "http_api": {
        "name": "HTTP API",
        "description": "Make custom HTTP requests to any API endpoint",
        "category": "custom",
        "fields": [
            {"key": "base_url", "label": "Base URL (optional)", "type": "url", "required": False},
            {"key": "default_headers", "label": "Default Headers (JSON)", "type": "textarea", "required": False},
        ],
    },
    "webhook": {
        "name": "Webhook",
        "description": "Send data to custom webhook endpoints",
        "category": "custom",
        "fields": [
            {"key": "default_url", "label": "Default Webhook URL (optional)", "type": "url", "required": False},
            {"key": "secret_header", "label": "Secret Header Name", "type": "text", "required": False},
            {"key": "secret_value", "label": "Secret Value", "type": "password", "required": False},
        ],
    },
}

# Maps Composio app IDs -> simple integration IDs that workflow nodes use.
# When a Composio app is connected, the corresponding simple integration is
# also reported as configured so the Action/Agent panels show a green status.
COMPOSIO_TO_SIMPLE_MAP: Dict[str, str] = {
    "gmail": "email_smtp",
    "googlesheets": "google_sheets",
    "twilio": "twilio",
    "whatsapp": "whatsapp",
    "slack": "slack",
    "notion": "notion",
    "airtable": "airtable",
    "googledrive": "googledrive",
    "googlecalendar": "googlecalendar",
    "github": "github",
    "hubspot": "hubspot",
    "linear": "linear",
    "supabase": "supabase",
    "mysql": "mysql",
    "mongodb": "mongodb",
    "firebase": "firebase",
    "postgresql": "postgresql",
}


# =============================================================================
# Pydantic Models
# =============================================================================

class IntegrationCredentials(BaseModel):
    """Model for saving integration credentials."""
    credentials: Dict[str, Any] = Field(..., description="Integration-specific credentials")
    is_enabled: bool = Field(default=True, description="Whether the integration is enabled")


class IntegrationStatusResponse(BaseModel):
    """Response model for integration status."""
    integration_id: str
    is_configured: bool
    is_enabled: bool


class AllIntegrationsStatusResponse(BaseModel):
    """Response model for all integrations status."""
    integrations: List[IntegrationStatusResponse]


class IntegrationCredentialResponse(BaseModel):
    """Response model for integration credentials (with raw values for editing)."""
    integration_id: str
    is_enabled: bool
    credentials: Dict[str, str] = Field(default_factory=dict)


# =============================================================================
# Helper Functions
# =============================================================================

def get_integration_key(integration_id: str) -> str:
    """Get the configuration key for an integration."""
    return f"integration_{integration_id}"


# =============================================================================
# API Routes
# =============================================================================

@router.get("/status")
async def get_all_integrations_status(
    user: UserModel = Depends(get_user),
) -> AllIntegrationsStatusResponse:
    """Get configuration status for all integrations.

    Primary source: Composio connections (Integrations page).
    Fallback: simple integration keys for non-Composio tools (http_api, webhook).
    """
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")

    configured: Dict[str, bool] = {}

    # 1) PRIMARY — Composio connections are the source of truth
    try:
        composio_accounts = await composio_service.get_connected_accounts(
            user.selected_organization_id
        )
        for account in composio_accounts:
            if account.is_connected:
                # Register by Composio app_id (gmail, slack, googlesheets …)
                configured[account.app_id] = True
                # Also register mapped simple ID so legacy checks still work
                simple_id = COMPOSIO_TO_SIMPLE_MAP.get(account.app_id)
                if simple_id:
                    configured[simple_id] = True
    except Exception as e:
        logger.warning(f"Could not fetch Composio connection statuses: {e}")

    # 2) FALLBACK — check simple integration keys for non-Composio tools
    config_keys = [get_integration_key(iid) for iid in INTEGRATION_DEFINITIONS.keys()]
    configs = await db_client.get_configurations_by_keys(
        user.selected_organization_id, config_keys
    )
    for integration_id in INTEGRATION_DEFINITIONS.keys():
        if integration_id not in configured:
            key = get_integration_key(integration_id)
            config = configs.get(key)
            if config and config.value:
                configured[integration_id] = config.value.get("is_enabled", True)

    # 3) Build response — include every known ID
    all_ids = set(INTEGRATION_DEFINITIONS.keys()) | set(configured.keys())
    integrations = []
    for iid in sorted(all_ids):
        if iid in configured:
            integrations.append(IntegrationStatusResponse(
                integration_id=iid,
                is_configured=True,
                is_enabled=configured[iid],
            ))
        else:
            integrations.append(IntegrationStatusResponse(
                integration_id=iid,
                is_configured=False,
                is_enabled=False,
            ))

    return AllIntegrationsStatusResponse(integrations=integrations)


@router.get("/{integration_id}")
async def get_integration_credentials(
    integration_id: str,
    user: UserModel = Depends(get_user),
) -> IntegrationCredentialResponse:
    """Get credentials for a specific integration."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    if integration_id not in INTEGRATION_DEFINITIONS:
        raise HTTPException(status_code=400, detail=f"Unknown integration: {integration_id}")
    
    key = get_integration_key(integration_id)
    config = await db_client.get_configuration(user.selected_organization_id, key)
    
    if not config or not config.value:
        raise HTTPException(status_code=404, detail="Integration not configured")
    
    return IntegrationCredentialResponse(
        integration_id=integration_id,
        is_enabled=config.value.get("is_enabled", True),
        credentials=config.value.get("credentials", {}),
    )


@router.post("/{integration_id}")
async def save_integration(
    integration_id: str,
    data: IntegrationCredentials,
    user: UserModel = Depends(get_user),
) -> IntegrationStatusResponse:
    """Create or update an integration."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    if integration_id not in INTEGRATION_DEFINITIONS:
        raise HTTPException(status_code=400, detail=f"Unknown integration: {integration_id}")
    
    key = get_integration_key(integration_id)
    
    value = {
        "credentials": data.credentials,
        "is_enabled": data.is_enabled,
    }
    
    await db_client.upsert_configuration(
        user.selected_organization_id,
        key,
        value,
    )
    
    logger.info(f"Saved integration {integration_id} for org {user.selected_organization_id}")
    
    return IntegrationStatusResponse(
        integration_id=integration_id,
        is_configured=True,
        is_enabled=data.is_enabled,
    )


@router.delete("/{integration_id}")
async def delete_integration(
    integration_id: str,
    user: UserModel = Depends(get_user),
) -> Dict[str, str]:
    """Delete an integration."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    if integration_id not in INTEGRATION_DEFINITIONS:
        raise HTTPException(status_code=400, detail=f"Unknown integration: {integration_id}")
    
    key = get_integration_key(integration_id)
    
    deleted = await db_client.delete_configuration(user.selected_organization_id, key)
    
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Integration {integration_id} not found")
    
    logger.info(f"Deleted integration {integration_id} for org {user.selected_organization_id}")
    
    return {"message": f"Integration {integration_id} deleted successfully"}


# =============================================================================
# Internal Functions (for use by Tool executor)
# =============================================================================

async def get_integration_credentials_internal(
    organization_id: int,
    integration_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Internal function to get integration credentials for tool execution.
    Returns the raw credentials or None if not configured/enabled.
    """
    key = get_integration_key(integration_id)
    config = await db_client.get_configuration(organization_id, key)
    
    if not config or not config.value:
        return None
    
    if not config.value.get("is_enabled", True):
        return None
    
    return config.value.get("credentials")

