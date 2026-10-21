import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

from api.enums import Environment

# Load environment variables from .env file (in api folder)
# Use override=True to ensure .env values take precedence over existing env vars
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path, override=True)

ENVIRONMENT = os.getenv("ENVIRONMENT", Environment.LOCAL.value)
# Absolute path to the project root directory (i.e. the directory containing
# the top-level api/ package). Having a single canonical location helps
# when constructing file-system paths elsewhere in the codebase.
APP_ROOT_DIR: Path = Path(__file__).resolve().parent

FILLER_SOUND_PROBABILITY = 0.0

VOICEMAIL_RECORDING_DURATION = 5.0

# Configuration constants
# Smart Turn Detection - uses ML model for better conversational turn detection
# Enabled by default for improved voice activity detection and interruption handling
ENABLE_SMART_TURN = os.getenv("ENABLE_SMART_TURN", "true").lower() == "true"
ENABLE_TRACING = os.getenv("ENABLE_TRACING", "false").lower() == "true"
ENABLE_RNNOISE = os.getenv("ENABLE_RNNOISE", "false").lower() == "true"

# URLs for deployment
BACKEND_API_ENDPOINT = os.getenv("BACKEND_API_ENDPOINT", "http://localhost:8000")
_raw_ui_app_url = os.getenv("UI_APP_URL", "http://localhost:3010").rstrip("/")
# Strip any trailing path segments (e.g. /pricing) to ensure only the origin is used.
# This prevents double-path bugs like /pricing/pricing in Stripe redirect URLs.
from urllib.parse import urlparse as _urlparse
_parsed = _urlparse(_raw_ui_app_url)
UI_APP_URL = f"{_parsed.scheme}://{_parsed.netloc}"

# Supabase Configuration
# All values must be set via environment variables - no defaults for security
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_PROJECT_ID = os.getenv("SUPABASE_PROJECT_ID", "")

# Supabase database password - get from Supabase Dashboard > Settings > Database
SUPABASE_DB_PASSWORD = os.getenv("SUPABASE_DB_PASSWORD", "")

# URL encode the password to handle special characters like @, #, etc.
_encoded_password = quote_plus(SUPABASE_DB_PASSWORD) if SUPABASE_DB_PASSWORD else ""

# Database URL — set via DATABASE_URL env var.
# Railway Postgres (recommended): automatically provided by Railway as DATABASE_URL
#   Format: postgresql+asyncpg://postgres:[password]@[host].railway.internal:5432/railway
# Supabase fallback: constructed from SUPABASE_* env vars
#   Format: postgresql+asyncpg://postgres.[project-id]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+asyncpg://postgres.{SUPABASE_PROJECT_ID}:{_encoded_password}@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    if SUPABASE_PROJECT_ID else ""
)

REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://:redissecret@localhost:6379"
)

# Qdrant Cloud Vector Database
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")

# Deployment mode. The legacy "oss" mode granted authentication without any
# cryptographic verification and has been removed for security. Deployments
# must run with a real, verified auth provider (see AUTH_PROVIDER).
DEPLOYMENT_MODE = os.getenv("DEPLOYMENT_MODE", "cloud")
DOGRAH_MPS_SECRET_KEY = os.getenv("DOGRAH_MPS_SECRET_KEY", None)
MPS_API_URL = os.getenv("MPS_API_URL", "https://services.dograh.com")

# Secret used to sign short-lived tickets that authorize real-time media
# connections (telephony/WebRTC/LiveKit media WebSockets). Must be a strong,
# shared secret across all worker processes. If unset we derive a stable key
# from DATABASE_URL (a secret already shared across workers) so tickets still
# work, but production deployments SHOULD set WS_TICKET_SECRET explicitly.
WS_TICKET_SECRET = os.getenv("WS_TICKET_SECRET", "")

# Auth Provider Configuration
# Options: "clerk", "stack". Every request is verified against the configured
# provider; there is no unauthenticated/local bypass.
AUTH_PROVIDER = os.getenv("AUTH_PROVIDER", "clerk")


def _parse_csv_env(value: str) -> set[str]:
    return {item.strip().lower() for item in value.split(",") if item.strip()}


# Superuser bootstrap. Any authenticated user whose email or provider id matches
# one of these lists is automatically promoted to superuser on login. This lets
# an operator grant themselves admin access purely via environment variables,
# without direct database access.
# Comma-separated. Example:
#   SUPERUSER_EMAILS=me@example.com,admin@example.com
#   SUPERUSER_PROVIDER_IDS=user_2abc...,user_2def...
SUPERUSER_EMAILS = _parse_csv_env(os.getenv("SUPERUSER_EMAILS", ""))
SUPERUSER_PROVIDER_IDS = _parse_csv_env(os.getenv("SUPERUSER_PROVIDER_IDS", ""))

# Storage Configuration
# STORAGE_BACKEND options: "supabase", "s3", "minio" (default: "supabase")
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "supabase")
ENABLE_AWS_S3 = os.getenv("ENABLE_AWS_S3", "false").lower() == "true"

# Supabase Storage Configuration
SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "voice-audio")

# AWS S3 Configuration (legacy - use Supabase Storage instead)
S3_BUCKET = os.environ.get("S3_BUCKET")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")

# Sentry configuration
SENTRY_DSN = os.getenv("SENTRY_DSN")


# LiveKit Cloud — when set, browser calls use LiveKit instead of aiortc
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")
LIVEKIT_ENABLED = bool(LIVEKIT_URL and LIVEKIT_API_KEY and LIVEKIT_API_SECRET)

ENABLE_ARI_STASIS = os.getenv("ENABLE_ARI_STASIS", "false").lower() == "true"
SERIALIZE_LOG_OUTPUT = os.getenv("SERIALIZE_LOG_OUTPUT", "false").lower() == "true"
ENABLE_TELEMETRY = os.getenv("ENABLE_TELEMETRY", "false").lower() == "true"

# =============================================================================
# Integration Providers
# =============================================================================

# Composio - OAuth integration platform for 500+ apps
# Get your API key from https://app.composio.dev
COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY")

# Nango - Alternative integration platform (legacy)
NANGO_API_KEY = os.getenv("NANGO_API_KEY")

# =============================================================================
# Meeting Agent — concurrency & scaling knobs
# =============================================================================

MEETING_MAX_SESSIONS_PER_USER = int(os.getenv("MEETING_MAX_SESSIONS_PER_USER", "5"))
MEETING_MAX_SESSIONS_GLOBAL = int(os.getenv("MEETING_MAX_SESSIONS_GLOBAL", "100"))
MEETING_MAX_CONCURRENT_RESPONSES = int(os.getenv("MEETING_MAX_CONCURRENT_RESPONSES", "10"))
MEETING_BOT_POLL_INTERVAL_SECONDS = int(os.getenv("MEETING_BOT_POLL_INTERVAL_SECONDS", "15"))
MEETING_SESSION_TTL_HOURS = float(os.getenv("MEETING_SESSION_TTL_HOURS", "24"))
RECALL_API_KEY = os.getenv("RECALL_API_KEY", "")
# Svix-style signing secret for Recall.ai webhooks (starts with "whsec_").
# Required to accept transcript webhooks; requests are rejected when unset.
RECALL_WEBHOOK_SECRET = os.getenv("RECALL_WEBHOOK_SECRET", "")

# =============================================================================
# Anonymous share / embed link abuse controls
# =============================================================================
# These bound the cost/abuse exposure of publicly reachable (unauthenticated)
# share and embed links. All are server-enforced regardless of client input.

# Max lifetime a share/embed token can be created with (days). Requests for a
# longer expiry are clamped; a token with no expiry is not permitted.
EMBED_MAX_EXPIRY_DAYS = int(os.getenv("EMBED_MAX_EXPIRY_DAYS", "30"))
# Default expiry applied when the caller does not specify one.
EMBED_DEFAULT_EXPIRY_DAYS = int(os.getenv("EMBED_DEFAULT_EXPIRY_DAYS", "7"))
# Hard cap on total sessions a single token may ever start. A caller-supplied
# usage_limit is clamped to this; when unset this cap is applied by default.
EMBED_MAX_USAGE_LIMIT = int(os.getenv("EMBED_MAX_USAGE_LIMIT", "500"))
# Max simultaneously-active sessions per token (concurrency cap).
EMBED_MAX_CONCURRENT_SESSIONS = int(os.getenv("EMBED_MAX_CONCURRENT_SESSIONS", "5"))
