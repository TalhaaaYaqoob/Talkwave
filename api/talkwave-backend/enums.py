from enum import Enum


class IntegrationAction(Enum):
    ALL_CALLS = "All Calls"
    QUALIFIED_CALLS = "Qualified Calls"


class Environment(Enum):
    LOCAL = "local"
    PRODUCTION = "production"
    TEST = "test"


class WorkflowRunMode(Enum):
    TWILIO = "twilio"
    VONAGE = "vonage"
    VOBIZ = "vobiz"
    STASIS = "stasis"
    WEBRTC = "webrtc"
    SMALLWEBRTC = "smallwebrtc"

    # Historical, not used anymore. Don't
    # use and don't remove
    VOICE = "VOICE"
    CHAT = "CHAT"


class StorageBackend(Enum):
    """Storage backend enumeration.

    Currently supported backends:
    - SUPABASE: Supabase Storage (default, recommended)
    - S3: Amazon S3

    Future extensibility: Additional backends like GCS, Azure can be added by:
    1. Adding new enum values as strings
    2. Implementing storage logic in services/storage.py
    3. Database will automatically support new values via SQLAlchemy Enum type
    """

    # Currently implemented backends
    SUPABASE = "supabase"  # Supabase Storage (default)
    S3 = "s3"  # AWS S3 for cloud deployments

    @classmethod
    def get_current_backend(cls):
        """Get current backend based on STORAGE_BACKEND env var or ENABLE_AWS_S3 flag."""
        from api.constants import ENABLE_AWS_S3, STORAGE_BACKEND

        # Check explicit STORAGE_BACKEND first
        if STORAGE_BACKEND:
            backend_lower = STORAGE_BACKEND.lower()
            if backend_lower == "supabase":
                return cls.SUPABASE
            elif backend_lower == "s3":
                return cls.S3
        
        # Fall back to legacy ENABLE_AWS_S3 flag
        if ENABLE_AWS_S3:
            return cls.S3
        
        # Default to Supabase
        return cls.SUPABASE


class WorkflowRunState(Enum):
    INITIALIZED = "initialized"  # Workflow run created, ready for connection
    RUNNING = "running"          # Websocket connected and pipeline active
    COMPLETED = "completed"      # Workflow run finished


class WorkflowRunStatus(Enum):
    # historical modes
    VOICE = "VOICE"
    CHAT = "CHAT"


class OrganizationConfigurationKey(Enum):
    DISPOSITION_CODE_MAPPING = "DISPOSITION_CODE_MAPPING"
    DISPOSITION_MESSAGE_TEMPLATE = "DISPOSITION_MESSAGE_TEMPLATE"
    CONCURRENT_CALL_LIMIT = "CONCURRENT_CALL_LIMIT"
    TELEPHONY_CONFIGURATION = (
        "TELEPHONY_CONFIGURATION"  # Stores all providers + active one
    )
    TWILIO_CONFIGURATION = (
        "TWILIO_CONFIGURATION"  # Deprecated - for backward compatibility
    )
    COMPLIANCE_SETTINGS = "COMPLIANCE_SETTINGS"  # Org-level compliance configuration


class WorkflowStatus(Enum):
    """Workflow status values"""

    ACTIVE = "active"
    ARCHIVED = "archived"
    # Future statuses can be added here like:
    # DRAFT = "draft"
    # PAUSED = "paused"


class RedisChannel(Enum):
    """Redis pub/sub channel names"""

    CAMPAIGN_EVENTS = "campaign_events"


class ToolType(Enum):
    """Types of custom tools that can be created"""

    HTTP_REQUEST = "http_request"  # Make HTTP/REST API calls
    WEBHOOK = "webhook"  # Trigger external webhooks
    DATABASE_QUERY = "database_query"  # Execute database queries via webhook
    CUSTOM_CODE = "custom_code"  # Run custom JavaScript/Python code
    INTEGRATION = "integration"  # Use third-party integrations (CRM, etc.)


class ExecutionStatus(Enum):
    """Status of tool execution"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class HttpMethod(Enum):
    """HTTP methods for webhook endpoints"""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class AuthType(Enum):
    """Authentication types for webhook endpoints"""

    NONE = "none"
    API_KEY = "api_key"
    BEARER = "bearer"
    BASIC = "basic"
    OAUTH2 = "oauth2"