"""
Service Credentials API Routes.
Handles CRUD operations for external service credentials (Twilio, SendGrid, Supabase, etc.)
"""

from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from api.db import db_client
from api.db.models import UserModel
from api.services.auth.depends import get_user

router = APIRouter(prefix="/service-credentials", tags=["Service Credentials"])


# =============================================================================
# Pydantic Models
# =============================================================================

class ServiceCredentialBase(BaseModel):
    """Base model for service credentials."""
    service_type: str = Field(..., description="Type of service (twilio, sendgrid, smtp, supabase)")
    credentials: Dict[str, Any] = Field(..., description="Service-specific credentials")
    is_enabled: bool = Field(default=True, description="Whether the service is enabled")


class ServiceCredentialCreate(ServiceCredentialBase):
    """Model for creating service credentials."""
    pass


class ServiceCredentialUpdate(BaseModel):
    """Model for updating service credentials."""
    credentials: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None


class ServiceCredentialResponse(BaseModel):
    """Response model for service credentials."""
    service_type: str
    is_configured: bool
    is_enabled: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Masked credentials for display (e.g., show last 4 chars)
    masked_credentials: Dict[str, str] = Field(default_factory=dict)


class ServiceStatusResponse(BaseModel):
    """Response model for checking service status."""
    service_type: str
    is_configured: bool
    is_enabled: bool


class AllServicesStatusResponse(BaseModel):
    """Response model for all services status."""
    services: List[ServiceStatusResponse]


# =============================================================================
# Helper Functions
# =============================================================================

def get_credential_key(service_type: str) -> str:
    """Get the configuration key for a service type."""
    return f"service_credentials_{service_type}"


def mask_credential(value: str, show_last: int = 4) -> str:
    """Mask a credential value, showing only last N characters."""
    if not value or len(value) <= show_last:
        return "*" * len(value) if value else ""
    return "*" * (len(value) - show_last) + value[-show_last:]


def get_masked_credentials(credentials: Dict[str, Any], service_type: str) -> Dict[str, str]:
    """Get masked version of credentials for display."""
    masked = {}
    
    # Common sensitive field patterns that should always be masked
    sensitive_patterns = [
        "password", "secret", "token", "api_key", "auth_token", "private_key",
        "access_key", "service_account", "service_role", "auth_header",
    ]
    
    for key, value in credentials.items():
        if isinstance(value, str):
            # Check if field name contains any sensitive pattern
            is_sensitive = any(pattern in key.lower() for pattern in sensitive_patterns)
            if is_sensitive:
                masked[key] = mask_credential(value)
            else:
                masked[key] = value
        elif isinstance(value, dict):
            # For complex values like JSON, just indicate it's set
            masked[key] = "[JSON configured]"
        else:
            masked[key] = str(value) if value is not None else ""
    
    return masked


# =============================================================================
# Service Type Definitions (for frontend reference)
# =============================================================================

# Service Categories
SERVICE_CATEGORIES = {
    "messaging": {"name": "Messaging", "description": "SMS, WhatsApp, and messaging services"},
    "email": {"name": "Email", "description": "Email delivery services"},
    "database": {"name": "Databases", "description": "Database connections and storage"},
    "ai": {"name": "AI & LLM", "description": "AI and language model providers"},
    "storage": {"name": "Storage", "description": "File and object storage services"},
    "other": {"name": "Other", "description": "Additional integrations"},
}

SERVICE_DEFINITIONS = {
    # =========================================================================
    # MESSAGING SERVICES
    # =========================================================================
    "twilio": {
        "name": "Twilio SMS",
        "category": "messaging",
        "description": "Send SMS messages via Twilio",
        "icon": "message-square",
        "fields": [
            {"key": "account_sid", "label": "Account SID", "type": "text", "required": True},
            {"key": "auth_token", "label": "Auth Token", "type": "password", "required": True},
            {"key": "from_number", "label": "From Phone Number", "type": "text", "required": False, "placeholder": "+1234567890", "help": "Direct phone number to send from (optional if using Messaging Service)"},
            {"key": "messaging_service_sid", "label": "Messaging Service SID", "type": "text", "required": False, "placeholder": "MGXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX", "help": "For A2P 10DLC, toll-free, or short codes (recommended)"},
        ],
        "docs_url": "https://www.twilio.com/docs/sms",
    },
    "whatsapp": {
        "name": "WhatsApp Business",
        "category": "messaging",
        "description": "Send WhatsApp messages via Twilio or Meta API",
        "icon": "message-circle",
        "fields": [
            {"key": "provider", "label": "Provider", "type": "select", "required": True, "options": ["twilio", "meta"], "default": "twilio"},
            {"key": "account_sid", "label": "Account SID / App ID", "type": "text", "required": True},
            {"key": "auth_token", "label": "Auth Token / Access Token", "type": "password", "required": True},
            {"key": "from_number", "label": "WhatsApp Sender Number", "type": "text", "required": True, "placeholder": "+14155238886", "help": "For Twilio Sandbox testing: use +14155238886. Recipients must first send 'join <sandbox-code>' to this number."},
        ],
        "docs_url": "https://www.twilio.com/docs/whatsapp",
    },
    "slack": {
        "name": "Slack",
        "category": "messaging",
        "description": "Send messages to Slack channels",
        "icon": "hash",
        "fields": [
            {"key": "bot_token", "label": "Bot Token", "type": "password", "required": True, "placeholder": "xoxb-..."},
            {"key": "default_channel", "label": "Default Channel", "type": "text", "required": False, "placeholder": "#general"},
        ],
        "docs_url": "https://api.slack.com/docs",
    },
    
    # =========================================================================
    # EMAIL SERVICES
    # =========================================================================
    "sendgrid": {
        "name": "SendGrid",
        "category": "email",
        "description": "Send emails via SendGrid API",
        "icon": "mail",
        "fields": [
            {"key": "api_key", "label": "API Key", "type": "password", "required": True},
            {"key": "from_email", "label": "From Email Address", "type": "email", "required": True},
            {"key": "from_name", "label": "From Name", "type": "text", "required": False},
        ],
        "docs_url": "https://docs.sendgrid.com/",
    },
    "smtp": {
        "name": "SMTP",
        "category": "email",
        "description": "Send emails via SMTP server (Gmail, Outlook, etc.)",
        "icon": "server",
        "fields": [
            {"key": "smtp_host", "label": "SMTP Host", "type": "text", "required": True, "placeholder": "smtp.gmail.com"},
            {"key": "smtp_port", "label": "SMTP Port", "type": "number", "required": True, "placeholder": "587"},
            {"key": "username", "label": "Username", "type": "text", "required": True},
            {"key": "password", "label": "Password / App Password", "type": "password", "required": True},
            {"key": "from_email", "label": "From Email Address", "type": "email", "required": True},
            {"key": "use_tls", "label": "Use TLS", "type": "boolean", "required": False, "default": True},
        ],
        "docs_url": "https://support.google.com/mail/answer/7126229",
    },
    "mailgun": {
        "name": "Mailgun",
        "category": "email",
        "description": "Send emails via Mailgun API",
        "icon": "send",
        "fields": [
            {"key": "api_key", "label": "API Key", "type": "password", "required": True},
            {"key": "domain", "label": "Domain", "type": "text", "required": True, "placeholder": "mg.yourdomain.com"},
            {"key": "from_email", "label": "From Email Address", "type": "email", "required": True},
            {"key": "region", "label": "Region", "type": "select", "required": False, "options": ["us", "eu"], "default": "us"},
        ],
        "docs_url": "https://documentation.mailgun.com/",
    },
    
    # =========================================================================
    # DATABASE SERVICES
    # =========================================================================
    "postgresql": {
        "name": "PostgreSQL",
        "category": "database",
        "description": "Connect to PostgreSQL database",
        "icon": "database",
        "color": "#336791",
        "fields": [
            {"key": "host", "label": "Host", "type": "text", "required": True, "placeholder": "localhost"},
            {"key": "port", "label": "Port", "type": "number", "required": True, "placeholder": "5432", "default": 5432},
            {"key": "database", "label": "Database Name", "type": "text", "required": True},
            {"key": "username", "label": "Username", "type": "text", "required": True},
            {"key": "password", "label": "Password", "type": "password", "required": True},
            {"key": "ssl_mode", "label": "SSL Mode", "type": "select", "required": False, "options": ["disable", "require", "verify-ca", "verify-full"], "default": "require"},
        ],
        "docs_url": "https://www.postgresql.org/docs/",
        "connection_string_template": "postgresql://{username}:{password}@{host}:{port}/{database}",
    },
    "mysql": {
        "name": "MySQL",
        "category": "database",
        "description": "Connect to MySQL database",
        "icon": "database",
        "color": "#4479A1",
        "fields": [
            {"key": "host", "label": "Host", "type": "text", "required": True, "placeholder": "localhost"},
            {"key": "port", "label": "Port", "type": "number", "required": True, "placeholder": "3306", "default": 3306},
            {"key": "database", "label": "Database Name", "type": "text", "required": True},
            {"key": "username", "label": "Username", "type": "text", "required": True},
            {"key": "password", "label": "Password", "type": "password", "required": True},
            {"key": "ssl_enabled", "label": "Enable SSL", "type": "boolean", "required": False, "default": False},
        ],
        "docs_url": "https://dev.mysql.com/doc/",
        "connection_string_template": "mysql://{username}:{password}@{host}:{port}/{database}",
    },
    "mongodb": {
        "name": "MongoDB",
        "category": "database",
        "description": "Connect to MongoDB database (including Atlas)",
        "icon": "database",
        "color": "#47A248",
        "fields": [
            {"key": "connection_type", "label": "Connection Type", "type": "select", "required": True, "options": ["standard", "atlas_srv"], "default": "standard"},
            {"key": "host", "label": "Host / Cluster URL", "type": "text", "required": True, "placeholder": "localhost or cluster.mongodb.net"},
            {"key": "port", "label": "Port", "type": "number", "required": False, "placeholder": "27017", "default": 27017},
            {"key": "database", "label": "Database Name", "type": "text", "required": True},
            {"key": "username", "label": "Username", "type": "text", "required": False},
            {"key": "password", "label": "Password", "type": "password", "required": False},
            {"key": "auth_source", "label": "Auth Source", "type": "text", "required": False, "placeholder": "admin"},
        ],
        "docs_url": "https://www.mongodb.com/docs/",
        "connection_string_template": "mongodb://{username}:{password}@{host}:{port}/{database}",
    },
    "redis": {
        "name": "Redis",
        "category": "database",
        "description": "Connect to Redis cache/database",
        "icon": "zap",
        "color": "#DC382D",
        "fields": [
            {"key": "host", "label": "Host", "type": "text", "required": True, "placeholder": "localhost"},
            {"key": "port", "label": "Port", "type": "number", "required": True, "placeholder": "6379", "default": 6379},
            {"key": "password", "label": "Password", "type": "password", "required": False},
            {"key": "database", "label": "Database Number", "type": "number", "required": False, "placeholder": "0", "default": 0},
            {"key": "ssl_enabled", "label": "Enable SSL/TLS", "type": "boolean", "required": False, "default": False},
        ],
        "docs_url": "https://redis.io/docs/",
        "connection_string_template": "redis://:{password}@{host}:{port}/{database}",
    },
    "supabase": {
        "name": "Supabase",
        "category": "database",
        "description": "Connect to Supabase (PostgreSQL + Auth + Storage)",
        "icon": "database",
        "color": "#3ECF8E",
        "fields": [
            {"key": "project_url", "label": "Project URL", "type": "text", "required": True, "placeholder": "https://xxx.supabase.co"},
            {"key": "api_key", "label": "Anon/Public Key", "type": "password", "required": True},
            {"key": "service_role_key", "label": "Service Role Key", "type": "password", "required": False},
            {"key": "db_password", "label": "Database Password", "type": "password", "required": False},
        ],
        "docs_url": "https://supabase.com/docs",
    },
    "firebase": {
        "name": "Firebase / Firestore",
        "category": "database",
        "description": "Connect to Firebase Realtime Database or Firestore",
        "icon": "flame",
        "color": "#FFCA28",
        "fields": [
            {"key": "project_id", "label": "Project ID", "type": "text", "required": True},
            {"key": "service_account_json", "label": "Service Account JSON", "type": "textarea", "required": True, "placeholder": "Paste your service account JSON here"},
            {"key": "database_url", "label": "Database URL (Realtime DB)", "type": "text", "required": False, "placeholder": "https://xxx.firebaseio.com"},
        ],
        "docs_url": "https://firebase.google.com/docs",
    },
    "sqlserver": {
        "name": "SQL Server",
        "category": "database",
        "description": "Connect to Microsoft SQL Server",
        "icon": "database",
        "color": "#CC2927",
        "fields": [
            {"key": "host", "label": "Server Host", "type": "text", "required": True, "placeholder": "localhost"},
            {"key": "port", "label": "Port", "type": "number", "required": True, "placeholder": "1433", "default": 1433},
            {"key": "database", "label": "Database Name", "type": "text", "required": True},
            {"key": "username", "label": "Username", "type": "text", "required": True},
            {"key": "password", "label": "Password", "type": "password", "required": True},
            {"key": "encrypt", "label": "Encrypt Connection", "type": "boolean", "required": False, "default": True},
            {"key": "trust_server_certificate", "label": "Trust Server Certificate", "type": "boolean", "required": False, "default": False},
        ],
        "docs_url": "https://docs.microsoft.com/en-us/sql/",
        "connection_string_template": "mssql://{username}:{password}@{host}:{port}/{database}",
    },
    "sqlite": {
        "name": "SQLite",
        "category": "database",
        "description": "Use a local SQLite database file",
        "icon": "file",
        "color": "#003B57",
        "fields": [
            {"key": "database_path", "label": "Database File Path", "type": "text", "required": True, "placeholder": "./data/database.db"},
            {"key": "create_if_missing", "label": "Create If Missing", "type": "boolean", "required": False, "default": True},
        ],
        "docs_url": "https://www.sqlite.org/docs.html",
    },
    "dynamodb": {
        "name": "DynamoDB",
        "category": "database",
        "description": "Connect to AWS DynamoDB",
        "icon": "cloud",
        "color": "#4053D6",
        "fields": [
            {"key": "aws_access_key_id", "label": "AWS Access Key ID", "type": "text", "required": True},
            {"key": "aws_secret_access_key", "label": "AWS Secret Access Key", "type": "password", "required": True},
            {"key": "region", "label": "AWS Region", "type": "text", "required": True, "placeholder": "us-east-1"},
            {"key": "endpoint_url", "label": "Endpoint URL (Local)", "type": "text", "required": False, "placeholder": "http://localhost:8000"},
        ],
        "docs_url": "https://docs.aws.amazon.com/dynamodb/",
    },
    "planetscale": {
        "name": "PlanetScale",
        "category": "database",
        "description": "Connect to PlanetScale MySQL-compatible database",
        "icon": "globe",
        "color": "#000000",
        "fields": [
            {"key": "host", "label": "Host", "type": "text", "required": True, "placeholder": "xxx.us-east-3.psdb.cloud"},
            {"key": "database", "label": "Database Name", "type": "text", "required": True},
            {"key": "username", "label": "Username", "type": "text", "required": True},
            {"key": "password", "label": "Password", "type": "password", "required": True},
        ],
        "docs_url": "https://planetscale.com/docs",
        "connection_string_template": "mysql://{username}:{password}@{host}/{database}?ssl={\"rejectUnauthorized\":true}",
    },
    "neon": {
        "name": "Neon",
        "category": "database",
        "description": "Connect to Neon serverless PostgreSQL",
        "icon": "zap",
        "color": "#00E599",
        "fields": [
            {"key": "connection_string", "label": "Connection String", "type": "password", "required": True, "placeholder": "postgres://user:pass@xxx.neon.tech/dbname"},
            {"key": "pooled", "label": "Use Pooled Connection", "type": "boolean", "required": False, "default": True},
        ],
        "docs_url": "https://neon.tech/docs",
    },
    "turso": {
        "name": "Turso",
        "category": "database",
        "description": "Connect to Turso edge SQLite database",
        "icon": "globe",
        "color": "#4FF8D2",
        "fields": [
            {"key": "database_url", "label": "Database URL", "type": "text", "required": True, "placeholder": "libsql://xxx.turso.io"},
            {"key": "auth_token", "label": "Auth Token", "type": "password", "required": True},
        ],
        "docs_url": "https://docs.turso.tech/",
    },
    
    # =========================================================================
    # AI & LLM SERVICES
    # =========================================================================
    "openai": {
        "name": "OpenAI",
        "category": "ai",
        "description": "Connect to OpenAI API (GPT, DALL-E, Whisper)",
        "icon": "brain",
        "color": "#412991",
        "fields": [
            {"key": "api_key", "label": "API Key", "type": "password", "required": True, "placeholder": "sk-..."},
            {"key": "organization_id", "label": "Organization ID", "type": "text", "required": False},
            {"key": "default_model", "label": "Default Model", "type": "text", "required": False, "placeholder": "gpt-4o", "default": "gpt-4o"},
        ],
        "docs_url": "https://platform.openai.com/docs",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "category": "ai",
        "description": "Connect to Anthropic Claude API",
        "icon": "bot",
        "color": "#D4A574",
        "fields": [
            {"key": "api_key", "label": "API Key", "type": "password", "required": True},
            {"key": "default_model", "label": "Default Model", "type": "text", "required": False, "placeholder": "claude-3-opus-20240229"},
        ],
        "docs_url": "https://docs.anthropic.com/",
    },
    "google_ai": {
        "name": "Google AI (Gemini)",
        "category": "ai",
        "description": "Connect to Google AI / Gemini API",
        "icon": "sparkles",
        "color": "#4285F4",
        "fields": [
            {"key": "api_key", "label": "API Key", "type": "password", "required": True},
            {"key": "default_model", "label": "Default Model", "type": "text", "required": False, "placeholder": "gemini-pro"},
        ],
        "docs_url": "https://ai.google.dev/docs",
    },
    
    # =========================================================================
    # STORAGE SERVICES
    # =========================================================================
    "aws_s3": {
        "name": "AWS S3",
        "category": "storage",
        "description": "Connect to Amazon S3 for file storage",
        "icon": "cloud",
        "color": "#FF9900",
        "fields": [
            {"key": "aws_access_key_id", "label": "AWS Access Key ID", "type": "text", "required": True},
            {"key": "aws_secret_access_key", "label": "AWS Secret Access Key", "type": "password", "required": True},
            {"key": "region", "label": "AWS Region", "type": "text", "required": True, "placeholder": "us-east-1"},
            {"key": "bucket", "label": "Default Bucket", "type": "text", "required": True},
        ],
        "docs_url": "https://docs.aws.amazon.com/s3/",
    },
    "cloudflare_r2": {
        "name": "Cloudflare R2",
        "category": "storage",
        "description": "Connect to Cloudflare R2 storage (S3-compatible)",
        "icon": "cloud",
        "color": "#F38020",
        "fields": [
            {"key": "account_id", "label": "Account ID", "type": "text", "required": True},
            {"key": "access_key_id", "label": "Access Key ID", "type": "text", "required": True},
            {"key": "secret_access_key", "label": "Secret Access Key", "type": "password", "required": True},
            {"key": "bucket", "label": "Bucket Name", "type": "text", "required": True},
        ],
        "docs_url": "https://developers.cloudflare.com/r2/",
    },
    
    # =========================================================================
    # OTHER SERVICES
    # =========================================================================
    "google_sheets": {
        "name": "Google Sheets",
        "category": "other",
        "description": "Read/write data to Google Sheets",
        "icon": "table",
        "color": "#0F9D58",
        "fields": [
            {"key": "service_account_json", "label": "Service Account JSON", "type": "textarea", "required": True, "placeholder": "Paste your service account JSON here"},
            {"key": "default_spreadsheet_id", "label": "Default Spreadsheet ID", "type": "text", "required": False},
        ],
        "docs_url": "https://developers.google.com/sheets/api",
    },
    "airtable": {
        "name": "Airtable",
        "category": "other",
        "description": "Connect to Airtable bases",
        "icon": "grid",
        "color": "#18BFFF",
        "fields": [
            {"key": "api_key", "label": "API Key / Personal Access Token", "type": "password", "required": True},
            {"key": "base_id", "label": "Default Base ID", "type": "text", "required": False, "placeholder": "appXXXXXXXXXXXX"},
        ],
        "docs_url": "https://airtable.com/developers/web/api/introduction",
    },
    "notion": {
        "name": "Notion",
        "category": "other",
        "description": "Connect to Notion workspaces",
        "icon": "book-open",
        "color": "#000000",
        "fields": [
            {"key": "integration_token", "label": "Integration Token", "type": "password", "required": True, "placeholder": "secret_..."},
        ],
        "docs_url": "https://developers.notion.com/",
    },
    "webhook": {
        "name": "Custom Webhook",
        "category": "other",
        "description": "Configure a custom webhook endpoint",
        "icon": "link",
        "fields": [
            {"key": "url", "label": "Webhook URL", "type": "text", "required": True, "placeholder": "https://your-endpoint.com/webhook"},
            {"key": "auth_header", "label": "Authorization Header", "type": "password", "required": False},
            {"key": "method", "label": "HTTP Method", "type": "select", "required": False, "options": ["POST", "PUT", "PATCH"], "default": "POST"},
        ],
        "docs_url": None,
    },
}


# =============================================================================
# API Routes
# =============================================================================

@router.get("/categories")
async def get_service_categories() -> Dict[str, Any]:
    """Get all service categories."""
    return SERVICE_CATEGORIES


@router.get("/definitions")
async def get_service_definitions() -> Dict[str, Any]:
    """Get all available service definitions with their field schemas."""
    return SERVICE_DEFINITIONS


@router.get("/definitions/{category}")
async def get_service_definitions_by_category(category: str) -> Dict[str, Any]:
    """Get service definitions filtered by category."""
    if category not in SERVICE_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown category: {category}")
    
    return {
        key: value for key, value in SERVICE_DEFINITIONS.items() 
        if value.get("category") == category
    }


@router.get("/status")
async def get_all_services_status(
    user: UserModel = Depends(get_user),
) -> AllServicesStatusResponse:
    """Get configuration status for all services."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    # Build list of all configuration keys we need to fetch
    config_keys = [get_credential_key(service_type) for service_type in SERVICE_DEFINITIONS.keys()]
    
    # Fetch all configurations in a single batch query (N+1 optimization)
    configs = await db_client.get_configurations_by_keys(user.selected_organization_id, config_keys)
    
    # Build response using batch-fetched configurations
    services = []
    for service_type in SERVICE_DEFINITIONS.keys():
        key = get_credential_key(service_type)
        config = configs.get(key)
        
        if config and config.value:
            services.append(ServiceStatusResponse(
                service_type=service_type,
                is_configured=True,
                is_enabled=config.value.get("is_enabled", True),
            ))
        else:
            services.append(ServiceStatusResponse(
                service_type=service_type,
                is_configured=False,
                is_enabled=False,
            ))
    
    return AllServicesStatusResponse(services=services)


@router.get("/status/{service_type}")
async def get_service_status(
    service_type: str,
    user: UserModel = Depends(get_user),
) -> ServiceStatusResponse:
    """Check if a specific service is configured and enabled."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    if service_type not in SERVICE_DEFINITIONS:
        raise HTTPException(status_code=400, detail=f"Unknown service type: {service_type}")
    
    key = get_credential_key(service_type)
    config = await db_client.get_configuration(user.selected_organization_id, key)
    
    if config and config.value:
        return ServiceStatusResponse(
            service_type=service_type,
            is_configured=True,
            is_enabled=config.value.get("is_enabled", True),
        )
    
    return ServiceStatusResponse(
        service_type=service_type,
        is_configured=False,
        is_enabled=False,
    )


@router.get("/{service_type}")
async def get_service_credentials(
    service_type: str,
    user: UserModel = Depends(get_user),
) -> ServiceCredentialResponse:
    """Get credentials for a specific service (masked)."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    if service_type not in SERVICE_DEFINITIONS:
        raise HTTPException(status_code=400, detail=f"Unknown service type: {service_type}")
    
    key = get_credential_key(service_type)
    config = await db_client.get_configuration(user.selected_organization_id, key)
    
    if not config or not config.value:
        return ServiceCredentialResponse(
            service_type=service_type,
            is_configured=False,
            is_enabled=False,
            masked_credentials={},
        )
    
    credentials = config.value.get("credentials", {})
    
    return ServiceCredentialResponse(
        service_type=service_type,
        is_configured=True,
        is_enabled=config.value.get("is_enabled", True),
        created_at=config.created_at,
        updated_at=config.updated_at,
        masked_credentials=get_masked_credentials(credentials, service_type),
    )


@router.post("/{service_type}")
async def create_or_update_service_credentials(
    service_type: str,
    data: ServiceCredentialCreate,
    user: UserModel = Depends(get_user),
) -> ServiceCredentialResponse:
    """Create or update credentials for a service."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    if service_type not in SERVICE_DEFINITIONS:
        raise HTTPException(status_code=400, detail=f"Unknown service type: {service_type}")
    
    if data.service_type != service_type:
        raise HTTPException(status_code=400, detail="Service type mismatch")
    
    key = get_credential_key(service_type)
    
    value = {
        "credentials": data.credentials,
        "is_enabled": data.is_enabled,
    }
    
    config = await db_client.upsert_configuration(
        user.selected_organization_id,
        key,
        value,
    )
    
    logger.info(f"Saved {service_type} credentials for org {user.selected_organization_id}")
    
    return ServiceCredentialResponse(
        service_type=service_type,
        is_configured=True,
        is_enabled=data.is_enabled,
        created_at=config.created_at,
        updated_at=config.updated_at,
        masked_credentials=get_masked_credentials(data.credentials, service_type),
    )


@router.patch("/{service_type}")
async def update_service_credentials(
    service_type: str,
    data: ServiceCredentialUpdate,
    user: UserModel = Depends(get_user),
) -> ServiceCredentialResponse:
    """Partially update credentials for a service."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    if service_type not in SERVICE_DEFINITIONS:
        raise HTTPException(status_code=400, detail=f"Unknown service type: {service_type}")
    
    key = get_credential_key(service_type)
    config = await db_client.get_configuration(user.selected_organization_id, key)
    
    if not config:
        raise HTTPException(status_code=404, detail=f"No credentials found for {service_type}")
    
    current_value = config.value or {}
    
    if data.credentials is not None:
        # Merge new credentials with existing (allows partial updates)
        current_creds = current_value.get("credentials", {})
        current_creds.update(data.credentials)
        current_value["credentials"] = current_creds
    
    if data.is_enabled is not None:
        current_value["is_enabled"] = data.is_enabled
    
    config = await db_client.upsert_configuration(
        user.selected_organization_id,
        key,
        current_value,
    )
    
    logger.info(f"Patched {service_type} credentials for org {user.selected_organization_id}")
    
    return ServiceCredentialResponse(
        service_type=service_type,
        is_configured=True,
        is_enabled=current_value.get("is_enabled", True),
        created_at=config.created_at,
        updated_at=config.updated_at,
        masked_credentials=get_masked_credentials(current_value.get("credentials", {}), service_type),
    )


@router.delete("/{service_type}")
async def delete_service_credentials(
    service_type: str,
    user: UserModel = Depends(get_user),
) -> Dict[str, str]:
    """Delete credentials for a service."""
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    
    if service_type not in SERVICE_DEFINITIONS:
        raise HTTPException(status_code=400, detail=f"Unknown service type: {service_type}")
    
    key = get_credential_key(service_type)
    
    deleted = await db_client.delete_configuration(user.selected_organization_id, key)
    
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No credentials found for {service_type}")
    
    logger.info(f"Deleted {service_type} credentials for org {user.selected_organization_id}")
    
    return {"message": f"Credentials for {service_type} deleted successfully"}


# =============================================================================
# Connection Testing
# =============================================================================

class ConnectionTestRequest(BaseModel):
    """Request model for testing a connection."""
    credentials: Dict[str, Any]


class ConnectionTestResponse(BaseModel):
    """Response model for connection test results."""
    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None


async def test_postgresql_connection(credentials: Dict[str, Any]) -> ConnectionTestResponse:
    """Test PostgreSQL connection."""
    try:
        import asyncpg
        conn = await asyncpg.connect(
            host=credentials.get("host"),
            port=int(credentials.get("port", 5432)),
            database=credentials.get("database"),
            user=credentials.get("username"),
            password=credentials.get("password"),
            ssl=credentials.get("ssl_mode", "require") != "disable",
            timeout=10,
        )
        version = await conn.fetchval("SELECT version()")
        await conn.close()
        return ConnectionTestResponse(
            success=True,
            message="Connection successful",
            details={"version": version}
        )
    except Exception as e:
        return ConnectionTestResponse(success=False, message=str(e))


async def test_mysql_connection(credentials: Dict[str, Any]) -> ConnectionTestResponse:
    """Test MySQL connection."""
    try:
        import aiomysql
        conn = await aiomysql.connect(
            host=credentials.get("host"),
            port=int(credentials.get("port", 3306)),
            db=credentials.get("database"),
            user=credentials.get("username"),
            password=credentials.get("password"),
            connect_timeout=10,
        )
        async with conn.cursor() as cur:
            await cur.execute("SELECT VERSION()")
            version = await cur.fetchone()
        conn.close()
        return ConnectionTestResponse(
            success=True,
            message="Connection successful",
            details={"version": version[0] if version else "Unknown"}
        )
    except ImportError:
        return ConnectionTestResponse(success=False, message="aiomysql package not installed")
    except Exception as e:
        return ConnectionTestResponse(success=False, message=str(e))


async def test_mongodb_connection(credentials: Dict[str, Any]) -> ConnectionTestResponse:
    """Test MongoDB connection."""
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        
        if credentials.get("connection_type") == "atlas_srv":
            uri = f"mongodb+srv://{credentials.get('username')}:{credentials.get('password')}@{credentials.get('host')}/{credentials.get('database')}"
        else:
            auth = ""
            if credentials.get("username") and credentials.get("password"):
                auth = f"{credentials.get('username')}:{credentials.get('password')}@"
            uri = f"mongodb://{auth}{credentials.get('host')}:{credentials.get('port', 27017)}/{credentials.get('database')}"
        
        client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=10000)
        info = await client.server_info()
        client.close()
        return ConnectionTestResponse(
            success=True,
            message="Connection successful",
            details={"version": info.get("version")}
        )
    except ImportError:
        return ConnectionTestResponse(success=False, message="motor package not installed")
    except Exception as e:
        return ConnectionTestResponse(success=False, message=str(e))


async def test_redis_connection(credentials: Dict[str, Any]) -> ConnectionTestResponse:
    """Test Redis connection."""
    try:
        import redis.asyncio as aioredis
        
        client = aioredis.Redis(
            host=credentials.get("host"),
            port=int(credentials.get("port", 6379)),
            password=credentials.get("password") or None,
            db=int(credentials.get("database", 0)),
            ssl=credentials.get("ssl_enabled", False),
            socket_timeout=10,
        )
        pong = await client.ping()
        info = await client.info("server")
        await client.close()
        return ConnectionTestResponse(
            success=True,
            message="Connection successful",
            details={"version": info.get("redis_version")}
        )
    except ImportError:
        return ConnectionTestResponse(success=False, message="redis package not installed")
    except Exception as e:
        return ConnectionTestResponse(success=False, message=str(e))


async def test_twilio_connection(credentials: Dict[str, Any]) -> ConnectionTestResponse:
    """Test Twilio SMS connection by fetching account info."""
    try:
        import httpx
        
        account_sid = credentials.get("account_sid")
        auth_token = credentials.get("auth_token")
        from_number = credentials.get("from_number")  # SMS "from" phone number
        
        if not account_sid or not auth_token:
            return ConnectionTestResponse(success=False, message="Account SID and Auth Token are required")
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Test the account credentials
            response = await client.get(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}.json",
                auth=(account_sid, auth_token)
            )
        
        if response.status_code == 200:
            data = response.json()
            return ConnectionTestResponse(
                success=True,
                message="Twilio SMS connection successful",
                details={
                    "account_name": data.get("friendly_name"),
                    "account_status": data.get("status"),
                    "from_number": from_number,
                    "service": "Twilio SMS"
                }
            )
        elif response.status_code == 401:
            return ConnectionTestResponse(success=False, message="Invalid Account SID or Auth Token")
        else:
            return ConnectionTestResponse(success=False, message=f"Twilio API error: {response.status_code}")
    except httpx.TimeoutException:
        return ConnectionTestResponse(success=False, message="Connection timeout - please try again")
    except Exception as e:
        return ConnectionTestResponse(success=False, message=str(e))


async def test_sendgrid_connection(credentials: Dict[str, Any]) -> ConnectionTestResponse:
    """Test SendGrid connection by fetching sender verification."""
    try:
        import httpx
        
        api_key = credentials.get("api_key")
        
        if not api_key:
            return ConnectionTestResponse(success=False, message="API Key is required")
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://api.sendgrid.com/v3/user/profile",
                headers={"Authorization": f"Bearer {api_key}"}
            )
        
        if response.status_code == 200:
            data = response.json()
            return ConnectionTestResponse(
                success=True,
                message="Connection successful",
                details={
                    "first_name": data.get("first_name"),
                    "last_name": data.get("last_name"),
                    "email": data.get("email")
                }
            )
        elif response.status_code == 401:
            return ConnectionTestResponse(success=False, message="Invalid API Key")
        elif response.status_code == 403:
            return ConnectionTestResponse(success=False, message="API Key lacks permissions")
        else:
            return ConnectionTestResponse(success=False, message=f"SendGrid API error: {response.status_code}")
    except httpx.TimeoutException:
        return ConnectionTestResponse(success=False, message="Connection timeout - please try again")
    except Exception as e:
        return ConnectionTestResponse(success=False, message=str(e))


async def test_mailgun_connection(credentials: Dict[str, Any]) -> ConnectionTestResponse:
    """Test Mailgun connection."""
    try:
        import httpx
        
        api_key = credentials.get("api_key")
        domain = credentials.get("domain")
        region = credentials.get("region", "us")
        
        if not api_key or not domain:
            return ConnectionTestResponse(success=False, message="API Key and Domain are required")
        
        base_url = "https://api.eu.mailgun.net" if region == "eu" else "https://api.mailgun.net"
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{base_url}/v3/domains/{domain}",
                auth=("api", api_key)
            )
        
        if response.status_code == 200:
            data = response.json()
            domain_info = data.get("domain", {})
            return ConnectionTestResponse(
                success=True,
                message="Connection successful",
                details={
                    "domain": domain_info.get("name"),
                    "state": domain_info.get("state"),
                    "type": domain_info.get("type")
                }
            )
        elif response.status_code == 401:
            return ConnectionTestResponse(success=False, message="Invalid API Key")
        elif response.status_code == 404:
            return ConnectionTestResponse(success=False, message=f"Domain '{domain}' not found")
        else:
            return ConnectionTestResponse(success=False, message=f"Mailgun API error: {response.status_code}")
    except httpx.TimeoutException:
        return ConnectionTestResponse(success=False, message="Connection timeout - please try again")
    except Exception as e:
        return ConnectionTestResponse(success=False, message=str(e))


async def test_openai_connection(credentials: Dict[str, Any]) -> ConnectionTestResponse:
    """Test OpenAI connection."""
    try:
        import httpx
        
        api_key = credentials.get("api_key")
        
        if not api_key:
            return ConnectionTestResponse(success=False, message="API Key is required")
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
        
        if response.status_code == 200:
            data = response.json()
            models = [m["id"] for m in data.get("data", [])[:5]]
            return ConnectionTestResponse(
                success=True,
                message="Connection successful",
                details={
                    "available_models_sample": models,
                    "total_models": len(data.get("data", []))
                }
            )
        elif response.status_code == 401:
            return ConnectionTestResponse(success=False, message="Invalid API Key")
        else:
            return ConnectionTestResponse(success=False, message=f"OpenAI API error: {response.status_code}")
    except httpx.TimeoutException:
        return ConnectionTestResponse(success=False, message="Connection timeout - please try again")
    except Exception as e:
        return ConnectionTestResponse(success=False, message=str(e))


async def test_anthropic_connection(credentials: Dict[str, Any]) -> ConnectionTestResponse:
    """Test Anthropic Claude connection."""
    try:
        import httpx
        
        api_key = credentials.get("api_key")
        
        if not api_key:
            return ConnectionTestResponse(success=False, message="API Key is required")
        
        # Anthropic doesn't have a simple "ping" endpoint, so we make a minimal API call
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "Hi"}]
                }
            )
        
        if response.status_code == 200:
            return ConnectionTestResponse(
                success=True,
                message="Connection successful",
                details={"status": "API key is valid"}
            )
        elif response.status_code == 401:
            return ConnectionTestResponse(success=False, message="Invalid API Key")
        else:
            return ConnectionTestResponse(success=False, message=f"Anthropic API error: {response.status_code}")
    except httpx.TimeoutException:
        return ConnectionTestResponse(success=False, message="Connection timeout - please try again")
    except Exception as e:
        return ConnectionTestResponse(success=False, message=str(e))


async def test_aws_s3_connection(credentials: Dict[str, Any]) -> ConnectionTestResponse:
    """Test AWS S3 connection."""
    try:
        import aioboto3
        
        access_key = credentials.get("access_key_id")
        secret_key = credentials.get("secret_access_key")
        region = credentials.get("region", "us-east-1")
        bucket = credentials.get("bucket_name")
        
        if not access_key or not secret_key:
            return ConnectionTestResponse(success=False, message="Access Key ID and Secret Access Key are required")
        
        session = aioboto3.Session()
        async with session.client(
            's3',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        ) as s3:
            # List buckets to verify credentials
            response = await s3.list_buckets()
            buckets = [b['Name'] for b in response.get('Buckets', [])[:5]]
            
            return ConnectionTestResponse(
                success=True,
                message="Connection successful",
                details={
                    "buckets_sample": buckets,
                    "total_buckets": len(response.get('Buckets', []))
                }
            )
    except ImportError:
        return ConnectionTestResponse(success=False, message="aioboto3 package not installed")
    except Exception as e:
        error_msg = str(e)
        if "InvalidAccessKeyId" in error_msg:
            return ConnectionTestResponse(success=False, message="Invalid Access Key ID")
        elif "SignatureDoesNotMatch" in error_msg:
            return ConnectionTestResponse(success=False, message="Invalid Secret Access Key")
        return ConnectionTestResponse(success=False, message=error_msg)


async def test_supabase_connection(credentials: Dict[str, Any]) -> ConnectionTestResponse:
    """Test Supabase connection."""
    try:
        import httpx
        
        project_url = credentials.get("project_url")
        anon_key = (
            credentials.get("anon_key")
            or credentials.get("api_key")
            or credentials.get("service_role_key")
        )
        
        if not project_url or not anon_key:
            return ConnectionTestResponse(
                success=False,
                message="Project URL and Supabase key are required",
            )
        
        # Clean URL
        project_url = project_url.rstrip('/')
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Check if the Supabase REST API is accessible
            response = await client.get(
                f"{project_url}/rest/v1/",
                headers={
                    "apikey": anon_key,
                    "Authorization": f"Bearer {anon_key}"
                }
            )
        
        # Supabase returns 200 with OpenAPI spec on root
        if response.status_code == 200:
            return ConnectionTestResponse(
                success=True,
                message="Connection successful",
                details={"project_url": project_url}
            )
        elif response.status_code == 401:
            return ConnectionTestResponse(success=False, message="Invalid Supabase key")
        else:
            return ConnectionTestResponse(success=False, message=f"Supabase API error: {response.status_code}")
    except httpx.TimeoutException:
        return ConnectionTestResponse(success=False, message="Connection timeout - please try again")
    except Exception as e:
        return ConnectionTestResponse(success=False, message=str(e))


async def test_generic_service(credentials: Dict[str, Any], service_type: str) -> ConnectionTestResponse:
    """Generic test for services that don't have specific connection test."""
    # Check if required fields are present
    service_def = SERVICE_DEFINITIONS.get(service_type)
    if not service_def:
        return ConnectionTestResponse(success=False, message=f"Unknown service type: {service_type}")
    
    missing_fields = []
    for field in service_def.get("fields", []):
        if field.get("required") and not credentials.get(field.get("key")):
            missing_fields.append(field.get("label", field.get("key")))
    
    if missing_fields:
        return ConnectionTestResponse(
            success=False,
            message=f"Missing required fields: {', '.join(missing_fields)}"
        )
    
    return ConnectionTestResponse(
        success=True,
        message="Configuration appears valid (connection not tested)",
        details={"note": "Full connection test not available for this service"}
    )


CONNECTION_TESTERS = {
    # Databases
    "postgresql": test_postgresql_connection,
    "mysql": test_mysql_connection,
    "mongodb": test_mongodb_connection,
    "redis": test_redis_connection,
    # Messaging
    "twilio": test_twilio_connection,
    # Email
    "sendgrid": test_sendgrid_connection,
    "mailgun": test_mailgun_connection,
    # AI/LLM
    "openai": test_openai_connection,
    "anthropic": test_anthropic_connection,
    # Storage
    "aws_s3": test_aws_s3_connection,
    # Database PaaS
    "supabase": test_supabase_connection,
}


@router.post("/{service_type}/test")
async def test_service_connection(
    service_type: str,
    data: ConnectionTestRequest,
    user: UserModel = Depends(get_user),
) -> ConnectionTestResponse:
    """Test connection to a service without saving credentials."""
    if service_type not in SERVICE_DEFINITIONS:
        raise HTTPException(status_code=400, detail=f"Unknown service type: {service_type}")
    
    tester = CONNECTION_TESTERS.get(service_type)
    if tester:
        return await tester(data.credentials)
    else:
        return await test_generic_service(data.credentials, service_type)


# =============================================================================
# Internal Functions (for use by Action Node executor)
# =============================================================================

async def get_service_credentials_internal(
    organization_id: int,
    service_type: str,
) -> Optional[Dict[str, Any]]:
    """
    Internal function to get service credentials for action execution.
    Returns the raw credentials or None if not configured/enabled.
    """
    key = get_credential_key(service_type)
    config = await db_client.get_configuration(organization_id, key)
    
    if not config or not config.value:
        return None
    
    if not config.value.get("is_enabled", True):
        return None
    
    return config.value.get("credentials")

