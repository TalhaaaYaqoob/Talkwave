"""
Composio Integration Service.
Uses the official Composio Python SDK for OAuth and tool execution.
https://docs.composio.dev/
"""

import asyncio
import os
import time
from typing import Any, Dict, List, Optional
from datetime import datetime
from enum import Enum

from loguru import logger
from pydantic import BaseModel, Field

from api.db import db_client


# =============================================================================
# Configuration
# =============================================================================

# Trim whitespace/newlines — a stray trailing newline in the env var is a
# documented cause of Composio "Invalid API key" (HTTP 401) errors.
COMPOSIO_API_KEY = (os.getenv("COMPOSIO_API_KEY") or "").strip() or None

# Per-app auth config IDs for white-labeling (shows your brand on OAuth consent screens).
# Create custom auth configs at https://platform.composio.dev → Authentication management.
# Set env vars like COMPOSIO_AUTH_CONFIG_GMAIL=ac_xxxx to override Composio's default OAuth.
COMPOSIO_AUTH_CONFIGS: Dict[str, str] = {}
for key, value in os.environ.items():
    if key.startswith("COMPOSIO_AUTH_CONFIG_") and value:
        app_key = key[len("COMPOSIO_AUTH_CONFIG_"):].lower()
        COMPOSIO_AUTH_CONFIGS[app_key] = value

# Apps we support - organized by category
# Logo URLs use official brand assets or Simple Icons CDN
COMPOSIO_APPS = {
    # Messaging & Communication
    "gmail": {
        "name": "Gmail",
        "description": "Send and read emails via Gmail",
        "category": "messaging",
        "icon": "mail",
        "logo": "https://www.gstatic.com/images/branding/product/1x/gmail_2020q4_48dp.png",
        "color": "#EA4335",
        "auth_mode": "oauth",
        "composio_app": "GMAIL",
    },
    "slack": {
        "name": "Slack",
        "description": "Send messages to Slack channels",
        "category": "messaging",
        "icon": "hash",
        "logo": "https://a.slack-edge.com/80588/marketing/img/icons/icon_slack_hash_colored.png",
        "color": "#4A154B",
        "auth_mode": "oauth",
        "composio_app": "SLACK",
    },
    "twilio": {
        "name": "Twilio",
        "description": "SMS and voice calls",
        "category": "messaging",
        "icon": "phone",
        "logo": "https://www.twilio.com/assets/icons/twilio-icon-512.png",
        "color": "#F22F46",
        "auth_mode": "api_key",
        "composio_app": "TWILIO",
    },
    "whatsapp": {
        "name": "WhatsApp",
        "description": "Send WhatsApp messages via Twilio",
        "category": "messaging",
        "icon": "message-circle",
        "logo": "https://upload.wikimedia.org/wikipedia/commons/6/6b/WhatsApp.svg",
        "color": "#25D366",
        "auth_mode": "api_key",
        "composio_app": "WHATSAPP",
    },
    # Productivity
    "googlesheets": {
        "name": "Google Sheets",
        "description": "Read and write spreadsheet data",
        "category": "productivity",
        "icon": "file-spreadsheet",
        "logo": "https://www.gstatic.com/images/branding/product/1x/sheets_2020q4_48dp.png",
        "color": "#0F9D58",
        "auth_mode": "oauth",
        "composio_app": "GOOGLESHEETS",
    },
    "notion": {
        "name": "Notion",
        "description": "Manage Notion pages and databases",
        "category": "productivity",
        "icon": "book",
        "logo": "https://upload.wikimedia.org/wikipedia/commons/4/45/Notion_app_logo.png",
        "color": "#000000",
        "auth_mode": "oauth",
        "composio_app": "NOTION",
    },
    "airtable": {
        "name": "Airtable",
        "description": "Manage Airtable bases and records",
        "category": "productivity",
        "icon": "table",
        "logo": "https://cdn.worldvectorlogo.com/logos/airtable-1.svg",
        "color": "#18BFFF",
        "auth_mode": "api_key",
        "composio_app": "AIRTABLE",
    },
    "googledrive": {
        "name": "Google Drive",
        "description": "Upload and manage files",
        "category": "productivity",
        "icon": "hard-drive",
        "logo": "https://www.gstatic.com/images/branding/product/1x/drive_2020q4_48dp.png",
        "color": "#4285F4",
        "auth_mode": "oauth",
        "composio_app": "GOOGLEDRIVE",
    },
    "googlecalendar": {
        "name": "Google Calendar",
        "description": "Schedule meetings and manage calendar events",
        "category": "productivity",
        "icon": "calendar",
        "logo": "https://www.gstatic.com/images/branding/product/1x/calendar_2020q4_48dp.png",
        "color": "#4285F4",
        "auth_mode": "oauth",
        "composio_app": "GOOGLECALENDAR",
    },
    "outlookcalendar": {
        "name": "Outlook Calendar",
        "description": "Manage calendar events in Microsoft Outlook / Office 365",
        "category": "productivity",
        "icon": "calendar",
        "logo": "https://upload.wikimedia.org/wikipedia/commons/d/df/Microsoft_Office_Outlook_%282018%E2%80%93present%29.svg",
        "color": "#0078D4",
        "auth_mode": "oauth",
        "composio_app": "OUTLOOK",
    },
    # Databases (These are handled directly, not via Composio)
    "supabase": {
        "name": "Supabase",
        "description": "PostgreSQL database with auth and storage",
        "category": "database",
        "icon": "database",
        "logo": "https://supabase.com/favicon/favicon-196x196.png",
        "color": "#3ECF8E",
        "auth_mode": "api_key",
        "direct": True,
    },
    "mysql": {
        "name": "MySQL",
        "description": "Execute MySQL queries",
        "category": "database",
        "icon": "database",
        "logo": "https://labs.mysql.com/common/logos/mysql-logo.svg",
        "color": "#4479A1",
        "auth_mode": "credentials",
        "direct": True,
    },
    "mongodb": {
        "name": "MongoDB",
        "description": "NoSQL document database for flexible data storage",
        "category": "database",
        "icon": "database",
        "logo": "https://www.mongodb.com/assets/images/global/favicon.ico",
        "color": "#47A248",
        "auth_mode": "credentials",
        "direct": True,
    },
    "firebase": {
        "name": "Firebase",
        "description": "Google Firebase Realtime Database & Firestore",
        "category": "database",
        "icon": "flame",
        "logo": "https://www.gstatic.com/devrel-devsite/prod/v0e0f589edd85502a40d78d7d0825db8ea5ef3b99ab4070381ee86977c9168730/firebase/images/favicon.png",
        "color": "#FFCA28",
        "auth_mode": "api_key",
        "direct": True,
    },
    # Developer Tools
    "github": {
        "name": "GitHub",
        "description": "Manage repos, issues, and PRs",
        "category": "developer",
        "icon": "github",
        "logo": "https://github.githubassets.com/assets/GitHub-Mark-ea2971cee799.png",
        "color": "#181717",
        "auth_mode": "oauth",
        "composio_app": "GITHUB",
    },
    "linear": {
        "name": "Linear",
        "description": "Manage issues and projects",
        "category": "developer",
        "icon": "check-square",
        "logo": "https://linear.app/static/logo-mark.png",
        "color": "#5E6AD2",
        "auth_mode": "oauth",
        "composio_app": "LINEAR",
    },
    # CRM & Sales
    "hubspot": {
        "name": "HubSpot",
        "description": "Manage contacts, deals, and companies",
        "category": "crm",
        "icon": "users",
        "logo": "https://www.hubspot.com/hubfs/HubSpot_Logos/HubSpot-Inversed-Favicon.png",
        "color": "#FF7A59",
        "auth_mode": "oauth",
        "composio_app": "HUBSPOT",
    },
}

# Categories
COMPOSIO_CATEGORIES = {
    "messaging": {"name": "Messaging & Email", "description": "Communication tools"},
    "productivity": {"name": "Productivity", "description": "Docs, sheets, and notes"},
    "database": {"name": "Databases", "description": "Data storage and queries"},
    "developer": {"name": "Developer Tools", "description": "Code and project management"},
    "crm": {"name": "CRM & Sales", "description": "Customer relationship management"},
    "other": {"name": "More Apps", "description": "Other apps available via Composio"},
}

# Default fallback color/icon for apps discovered dynamically from Composio
# that aren't part of the curated COMPOSIO_APPS metadata above.
_DYNAMIC_APP_COLOR = "#6366F1"
_DYNAMIC_APP_ICON = "cloud"

# In-process cache for the dynamic Composio app catalog. The catalog is the
# same for every org, so we cache it module-wide with a TTL to avoid hitting
# Composio on every Integrations page load.
_CATALOG_CACHE: Dict[str, Any] = {"apps": None, "ts": 0.0}
_CATALOG_TTL_SECONDS = 3600  # 1 hour
# Serialize catalog fetches so concurrent page loads don't each pull the full
# 1000-toolkit catalog from Composio before the cache is populated.
_CATALOG_LOCK = asyncio.Lock()


def _prettify(slug: str) -> str:
    """Turn a category/app slug into a human-friendly label."""
    return slug.replace("_", " ").replace("-", " ").strip().title()


def _normalize_category(raw: Any) -> str:
    """Normalize a Composio category value into a stable slug id.

    The value can be a plain string, a dict, or a Composio SDK object such as
    ``ItemMetaCategory(id='EMAIL', name='EMAIL')``. For objects/dicts we unwrap
    the id/slug/name field so we never fall back to ``str(obj)`` (which would
    leak the raw repr into the UI as the category name).
    """
    if isinstance(raw, dict):
        raw = raw.get("id") or raw.get("slug") or raw.get("name") or ""
    elif raw is not None and not isinstance(raw, (str, int, float, bool)):
        raw = (
            getattr(raw, "id", None)
            or getattr(raw, "slug", None)
            or getattr(raw, "name", None)
            or ""
        )
    text = str(raw or "").strip().lower()
    if not text:
        return "other"
    return text.replace(" ", "-").replace("_", "-")


# =============================================================================
# Enums
# =============================================================================

class ConnectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING = "PENDING"
    FAILED = "FAILED"
    INACTIVE = "INACTIVE"
    NOT_CONNECTED = "NOT_CONNECTED"


# =============================================================================
# Pydantic Models
# =============================================================================

class ComposioConnectionStatus(BaseModel):
    """Status of a Composio app connection."""
    app_id: str
    app_name: str
    is_connected: bool
    status: ConnectionStatus = ConnectionStatus.NOT_CONNECTED
    connected_account_id: Optional[str] = None
    connected_at: Optional[datetime] = None


class ComposioConnectResponse(BaseModel):
    """Response with OAuth redirect URL."""
    redirect_url: str
    connection_id: str
    status: ConnectionStatus = ConnectionStatus.PENDING


class ComposioActionResponse(BaseModel):
    """Response from action execution."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# =============================================================================
# Composio Service - Using Official SDK
# =============================================================================

class ComposioService:
    """Service for managing Composio integrations using the official Python SDK."""
    
    def __init__(self):
        self.api_key = COMPOSIO_API_KEY
        self._client = None
        # toolkit_slug -> auth_config_id (Composio-managed or custom), cached
        self._auth_config_cache: Dict[str, str] = {}

    @staticmethod
    def _user_id(organization_id: int) -> str:
        """Composio v3 'user_id' replaces the old v1/v2 'entity_id'."""
        return f"org_{organization_id}"

    def _get_client(self):
        """Get or create the Composio v3 client.

        Migrated from the deprecated ``composio-core`` SDK (whose v1/v2 API
        endpoints now return HTTP 410) to the ``composio`` v3 SDK.
        """
        if self._client is None and self.api_key:
            try:
                from composio import Composio
                self._client = Composio(api_key=self.api_key)
                logger.info("Composio v3 client initialized")
            except ImportError:
                logger.warning("Composio SDK not installed. Run: pip install -U composio")
            except Exception as e:
                logger.error(f"Failed to initialize Composio v3 client: {e}")
        return self._client

    # Backwards-compatible aliases (a few callers referenced these names).
    def _get_composio(self):
        return self._get_client()

    def _resolve_auth_config_id(self, client, app_id: str, toolkit: str) -> Optional[str]:
        """Resolve an auth_config_id for a toolkit.

        Priority:
          1. Explicit override from COMPOSIO_AUTH_CONFIG_<APP> env var.
          2. An existing auth config for the toolkit on the Composio project.
          3. A newly created Composio-managed auth config (no dashboard setup
             required for OAuth toolkits that Composio manages).
        Returns None if one cannot be resolved (caller can fall back to the
        'magic' toolkits.authorize path).
        """
        override = COMPOSIO_AUTH_CONFIGS.get(app_id)
        if override:
            return override

        cached = self._auth_config_cache.get(toolkit)
        if cached:
            return cached

        # Try to reuse an existing auth config for this toolkit.
        try:
            existing = client.auth_configs.list(toolkit_slug=toolkit)
            items = getattr(existing, "items", None)
            if items is None and isinstance(existing, list):
                items = existing
            if items:
                ac_id = getattr(items[0], "id", None) or (
                    items[0].get("id") if isinstance(items[0], dict) else None
                )
                if ac_id:
                    self._auth_config_cache[toolkit] = ac_id
                    return ac_id
        except Exception as e:
            logger.debug(f"auth_configs.list failed for {toolkit}: {e}")

        # Create a Composio-managed auth config.
        try:
            created = client.auth_configs.create(
                toolkit=toolkit,
                options={"type": "use_composio_managed_auth"},
            )
            ac_id = getattr(created, "id", None) or (
                created.get("id") if isinstance(created, dict) else None
            )
            if ac_id:
                self._auth_config_cache[toolkit] = ac_id
                return ac_id
        except Exception as e:
            logger.debug(f"auth_configs.create failed for {toolkit}: {e}")

        return None

    @staticmethod
    def _toolkit_slug(app_info: Dict[str, Any], app_id: str) -> str:
        """Composio v3 toolkit slug (lowercase) for an app."""
        return str(app_info.get("composio_app") or app_id).lower()
    
    def _fetch_dynamic_apps(self) -> Dict[str, Dict[str, Any]]:
        """Fetch the full app catalog from Composio (synchronous SDK call).

        Returns a dict keyed by lowercase app id. Empty dict when the SDK is
        unavailable or the API key is not configured, so callers transparently
        fall back to the curated COMPOSIO_APPS list.
        """
        if not self.api_key:
            return {}

        try:
            client = self._get_client()
            if not client or not hasattr(client, "toolkits"):
                return {}

            # v3: apps are now "toolkits".
            response = client.toolkits.get()
            toolkits = getattr(response, "items", None)
            if toolkits is None:
                toolkits = response if isinstance(response, list) else []

            catalog: Dict[str, Dict[str, Any]] = {}

            for tk in toolkits:
                def _f(obj, *names, default=None):
                    for n in names:
                        val = getattr(obj, n, None)
                        if val is None and isinstance(obj, dict):
                            val = obj.get(n)
                        if val is not None:
                            return val
                    return default

                slug = _f(tk, "slug", "key", "name", default="")
                slug = str(slug).strip().lower()
                if not slug:
                    continue

                meta = _f(tk, "meta", default={}) or {}
                name = _f(tk, "name") or _f(meta, "name") or _prettify(slug)
                description = (
                    _f(tk, "description")
                    or _f(meta, "description")
                    or f"Connect {name} via Composio"
                )
                logo = _f(tk, "logo") or _f(meta, "logo")

                # Auth schemes live under meta in v3 (e.g. ["OAUTH2","API_KEY"]).
                auth_mode = "oauth"
                schemes = (
                    _f(tk, "auth_schemes")
                    or _f(meta, "auth_schemes")
                    or _f(meta, "supported_auth_schemes")
                    or []
                )
                modes = [str(s).upper() for s in schemes if s]

                no_auth = bool(
                    _f(tk, "no_auth", default=False)
                    or _f(meta, "no_auth", default=False)
                )

                # Auth schemes Composio manages itself (i.e. one-click / SSO).
                # When this is empty and the toolkit needs auth, connecting
                # requires a custom auth config (client id/secret) and would
                # fail with "Default auth config not found". Skip those apps so
                # the Integrations page only lists apps that connect out of the
                # box.
                managed_schemes = (
                    _f(tk, "composio_managed_auth_schemes")
                    or _f(meta, "composio_managed_auth_schemes")
                    or []
                )
                managed_modes = [str(s).upper() for s in managed_schemes if s]
                if not no_auth and not managed_modes:
                    continue

                if no_auth:
                    auth_mode = "none"
                elif managed_modes:
                    auth_mode = "oauth" if any("OAUTH" in m for m in managed_modes) else "api_key"
                elif modes:
                    auth_mode = "oauth" if any("OAUTH" in m for m in modes) else "api_key"

                categories = _f(tk, "categories") or _f(meta, "categories") or []
                first_category = categories[0] if categories else "other"

                catalog[slug] = {
                    "name": name,
                    "description": (str(description)[:140] if description else ""),
                    "category": _normalize_category(first_category),
                    "icon": _DYNAMIC_APP_ICON,
                    "logo": logo,
                    "color": _DYNAMIC_APP_COLOR,
                    "auth_mode": auth_mode,
                    "composio_app": slug.upper(),
                }

            logger.info(f"Fetched {len(catalog)} toolkits from Composio catalog")
            return catalog
        except Exception as e:
            logger.error(f"Failed to fetch Composio toolkit catalog: {e}")
            return {}

    async def get_all_app_definitions(self, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """Return the merged app catalog (curated overrides + Composio catalog).

        Curated COMPOSIO_APPS entries take precedence so they keep their nice
        icons/colors/categories and so direct-DB integrations remain available.
        Result is cached module-wide for performance.
        """
        now = time.time()
        cached = _CATALOG_CACHE.get("apps")
        if (
            not force_refresh
            and cached is not None
            and (now - _CATALOG_CACHE.get("ts", 0.0)) < _CATALOG_TTL_SECONDS
        ):
            return cached

        # Only one coroutine fetches the catalog at a time; everyone else waits
        # on the lock and then hits the freshly-populated cache below.
        async with _CATALOG_LOCK:
            now = time.time()
            cached = _CATALOG_CACHE.get("apps")
            if (
                not force_refresh
                and cached is not None
                and (now - _CATALOG_CACHE.get("ts", 0.0)) < _CATALOG_TTL_SECONDS
            ):
                return cached

            dynamic = await asyncio.to_thread(self._fetch_dynamic_apps)

            merged: Dict[str, Dict[str, Any]] = dict(dynamic)
            # Curated metadata wins over the dynamic catalog for known apps.
            for app_id, info in COMPOSIO_APPS.items():
                merged[app_id] = {**dynamic.get(app_id, {}), **info}

            _CATALOG_CACHE["apps"] = merged
            _CATALOG_CACHE["ts"] = now
            return merged

    async def get_app_info(self, app_id: str) -> Optional[Dict[str, Any]]:
        """Resolve metadata for a single app from the merged catalog."""
        if app_id in COMPOSIO_APPS:
            return COMPOSIO_APPS[app_id]
        defs = await self.get_all_app_definitions()
        return defs.get(app_id)

    async def get_available_apps(self) -> List[Dict[str, Any]]:
        """Get list of available apps with their metadata."""
        defs = await self.get_all_app_definitions()
        return [{"id": app_id, **app_info} for app_id, app_info in defs.items()]

    async def get_categories(self) -> Dict[str, Dict[str, str]]:
        """Get available categories, including ones discovered dynamically."""
        categories: Dict[str, Dict[str, str]] = {
            cat_id: dict(cat_info) for cat_id, cat_info in COMPOSIO_CATEGORIES.items()
        }
        defs = await self.get_all_app_definitions()
        for app_info in defs.values():
            cat_id = app_info.get("category") or "other"
            if cat_id not in categories:
                categories[cat_id] = {
                    "name": _prettify(cat_id),
                    "description": "Apps available via Composio",
                }
        return categories
    
    async def get_connected_accounts(
        self,
        organization_id: int,
    ) -> List[ComposioConnectionStatus]:
        """Get all connected accounts for an organization."""
        connections = []

        # Get stored connections from DB
        stored_connections = await self._get_stored_connections(organization_id)
        stored_map = {c.get("app_id"): c for c in stored_connections}

        # Also fetch the disconnected-blocklist from DB
        blocklist_config = await db_client.get_configuration(
            organization_id, "composio_disconnected_apps"
        )
        blocked_apps: set = set()
        if blocklist_config and blocklist_config.value:
            blocked_apps = set(blocklist_config.value.get("app_ids", []))

        # Check Composio SDK for OAuth app connections
        sdk_statuses = {}
        if self.api_key:
            sdk_statuses = self._get_sdk_connections(organization_id)

        app_defs = await self.get_all_app_definitions()

        for app_id, app_info in app_defs.items():
            stored = stored_map.get(app_id)
            sdk_status = sdk_statuses.get(app_info.get("composio_app", app_id.upper()), {})

            is_connected = False
            status = ConnectionStatus.NOT_CONNECTED
            connected_account_id = None
            connected_at = None

            # If user explicitly disconnected this app, skip SDK status
            if app_id in blocked_apps:
                connections.append(ComposioConnectionStatus(
                    app_id=app_id,
                    app_name=app_info["name"],
                    is_connected=False,
                    status=ConnectionStatus.NOT_CONNECTED,
                ))
                continue

            # Check SDK connection status first (for OAuth apps).
            # Only ACTIVE counts as connected. An INITIATED/PENDING account on
            # the list means the user started an OAuth flow and never finished
            # it (clicking Connect navigates away, so there's no in-page
            # progress to show). Treat those as NOT_CONNECTED so the app stays
            # retryable instead of getting stuck on "Connecting...".
            if sdk_status:
                status_str = str(sdk_status.get("status", "")).upper()
                if status_str == "ACTIVE":
                    is_connected = True
                    status = ConnectionStatus.ACTIVE
                    connected_account_id = sdk_status.get("id")

            # Check local DB (for API key apps and direct integrations)
            if not is_connected and stored and stored.get("is_active"):
                is_connected = True
                status = ConnectionStatus.ACTIVE
                connected_account_id = stored.get("connected_account_id")
                connected_at = stored.get("connected_at")

            connections.append(ComposioConnectionStatus(
                app_id=app_id,
                app_name=app_info["name"],
                is_connected=is_connected,
                status=status,
                connected_account_id=connected_account_id,
                connected_at=connected_at,
            ))

        return connections
    
    def _get_sdk_connections(self, organization_id: int) -> Dict[str, Dict[str, Any]]:
        """Get connected accounts from Composio (v3), keyed by toolkit slug (upper)."""
        if not self.api_key:
            return {}

        try:
            client = self._get_client()
            if not client:
                return {}

            user_id = self._user_id(organization_id)
            response = client.connected_accounts.list(user_ids=[user_id])
            accounts = getattr(response, "items", None)
            if accounts is None:
                accounts = response if isinstance(response, list) else []

            connections: Dict[str, Dict[str, Any]] = {}
            for conn in accounts:
                # Toolkit slug may live in a nested object or a flat field.
                toolkit = getattr(conn, "toolkit", None)
                slug = ""
                if toolkit is not None:
                    slug = getattr(toolkit, "slug", "") or (
                        toolkit.get("slug", "") if isinstance(toolkit, dict) else ""
                    )
                if not slug:
                    slug = (
                        getattr(conn, "toolkit_slug", "")
                        or getattr(conn, "appName", "")
                        or getattr(conn, "app_name", "")
                    )
                if not slug:
                    continue

                key = str(slug).upper()
                status = getattr(conn, "status", "") or (
                    conn.get("status", "") if isinstance(conn, dict) else ""
                )
                conn_id = getattr(conn, "id", "") or (
                    conn.get("id", "") if isinstance(conn, dict) else ""
                )
                # Prefer an ACTIVE account if multiple exist for the toolkit.
                existing = connections.get(key)
                if existing and str(existing.get("status", "")).upper() == "ACTIVE":
                    continue
                connections[key] = {"id": conn_id, "status": status}
            return connections

        except Exception as e:
            logger.debug(f"Could not fetch Composio connected accounts: {e}")
            return {}
    
    async def initiate_connection(
        self,
        organization_id: int,
        user_id: int,
        app_id: str,
        redirect_url: Optional[str] = None,
    ) -> ComposioConnectResponse:
        """Initiate OAuth connection using Composio SDK."""
        app_info = await self.get_app_info(app_id)
        if not app_info:
            raise ValueError(f"Unknown app: {app_id}")

        # User is reconnecting — clear the disconnect blocklist immediately
        await self._remove_from_blocklist(organization_id, app_id)
        
        # Direct integrations don't use Composio
        if app_info.get("direct"):
            return ComposioConnectResponse(
                redirect_url="",
                connection_id=f"direct_{app_id}_{organization_id}",
                status=ConnectionStatus.PENDING,
            )
        
        if not self.api_key:
            raise ValueError("COMPOSIO_API_KEY not configured. Get your key from https://app.composio.dev")

        client = self._get_client()
        if not client:
            raise ValueError("Composio SDK not available. Install with: pip install -U composio")

        composio_user_id = self._user_id(organization_id)
        toolkit = self._toolkit_slug(app_info, app_id)
        callback = redirect_url or f"/integrations?connected={app_id}"

        try:
            # v3 flow: prefer the hosted Connect Link with a resolved auth
            # config (works with Composio-managed OAuth — no dashboard setup
            # required). Fall back to toolkits.authorize() ("magic") which
            # auto-creates a managed auth config when one is missing.
            def _do_initiate():
                auth_config_id = self._resolve_auth_config_id(client, app_id, toolkit)
                if auth_config_id:
                    try:
                        return client.connected_accounts.link(
                            user_id=composio_user_id,
                            auth_config_id=auth_config_id,
                            callback_url=callback,
                        )
                    except Exception as link_err:
                        logger.warning(
                            f"connected_accounts.link failed for {toolkit}, "
                            f"falling back to toolkits.authorize: {link_err}"
                        )
                return client.toolkits.authorize(
                    user_id=composio_user_id, toolkit=toolkit
                )

            connection_request = await asyncio.to_thread(_do_initiate)

            redirect_uri = (
                getattr(connection_request, "redirect_url", None)
                or getattr(connection_request, "redirectUrl", None)
                or (connection_request.get("redirect_url") if isinstance(connection_request, dict) else None)
                or ""
            )
            connection_id = (
                getattr(connection_request, "id", None)
                or getattr(connection_request, "connected_account_id", None)
                or (connection_request.get("id") if isinstance(connection_request, dict) else None)
                or ""
            )

            # Store pending connection
            await self._store_connection(
                organization_id=organization_id,
                user_id=user_id,
                app_id=app_id,
                connected_account_id=str(connection_id),
                is_active=False,
            )

            logger.info(
                f"Initiated v3 connection for toolkit={toolkit}: "
                f"redirect={str(redirect_uri)[:50]}..."
            )

            return ComposioConnectResponse(
                redirect_url=redirect_uri,
                connection_id=str(connection_id),
                status=ConnectionStatus.PENDING,
            )

        except Exception as e:
            error_text = str(e)
            logger.error(f"Error initiating connection: {error_text}")

            # Composio has no managed OAuth credentials for this toolkit, so
            # one-click connect can't work — it needs a custom auth config
            # (client id/secret) created in the Composio dashboard. Surface a
            # clear, non-scary message instead of the raw 400 payload.
            if (
                "Default auth config not found" in error_text
                or "does not have managed credentials" in error_text
                or "Auth_Config_DefaultAuthConfigNotFound" in error_text
            ):
                app_name = app_info.get("name", app_id)
                raise ValueError(
                    f"{app_name} isn't available for one-click connection. "
                    f"Composio doesn't provide managed credentials for this app, "
                    f"so it needs a custom OAuth auth config (client ID & secret) "
                    f"set up in your Composio dashboard before it can be connected."
                )

            raise ValueError(f"Failed to initiate connection: {error_text}")
    
    async def check_connection_status(
        self,
        organization_id: int,
        app_id: str,
        connection_id: str,
    ) -> ConnectionStatus:
        """Check if a connection is active."""
        if not self.api_key or not connection_id:
            return ConnectionStatus.NOT_CONNECTED
        
        try:
            client = self._get_client()
            if not client:
                return ConnectionStatus.NOT_CONNECTED

            # v3: fetch the connected account by id
            connected_account = await asyncio.to_thread(
                client.connected_accounts.get, connection_id
            )

            if connected_account:
                status_str = str(getattr(connected_account, "status", "") or "").upper()

                if status_str == "ACTIVE":
                    await self._update_connection_status(
                        organization_id=organization_id,
                        app_id=app_id,
                        is_active=True,
                    )
                    return ConnectionStatus.ACTIVE
                elif status_str in ["INITIATED", "INITIALIZING", "PENDING"]:
                    return ConnectionStatus.PENDING
                elif status_str in ["FAILED", "EXPIRED"]:
                    return ConnectionStatus.FAILED

            return ConnectionStatus.NOT_CONNECTED
            
        except Exception as e:
            logger.error(f"Error checking connection status: {e}")
            return ConnectionStatus.NOT_CONNECTED
    
    async def handle_oauth_callback(
        self,
        organization_id: int,
        user_id: int,
        app_id: str,
        connected_account_id: str,
    ) -> bool:
        """Handle OAuth callback."""
        try:
            status = await self.check_connection_status(
                organization_id, app_id, connected_account_id
            )
            
            if status == ConnectionStatus.ACTIVE:
                await self._store_connection(
                    organization_id=organization_id,
                    user_id=user_id,
                    app_id=app_id,
                    connected_account_id=connected_account_id,
                    is_active=True,
                )
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error handling OAuth callback: {e}")
            return False
    
    async def save_api_credentials(
        self,
        organization_id: int,
        user_id: int,
        app_id: str,
        credentials: Dict[str, Any],
    ) -> bool:
        """Save API credentials for non-OAuth apps."""
        try:
            key = f"composio_credentials_{app_id}"
            value = {
                "credentials": credentials,
                "is_active": True,
                "connected_by": user_id,
                "app_id": app_id,
            }
            await db_client.upsert_configuration(organization_id, key, value)
            
            await self._store_connection(
                organization_id=organization_id,
                user_id=user_id,
                app_id=app_id,
                connected_account_id=f"credentials_{app_id}",
                is_active=True,
            )
            
            logger.info(f"Saved credentials for {app_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving credentials: {e}")
            return False
    
    async def disconnect_app(
        self,
        organization_id: int,
        app_id: str,
    ) -> bool:
        """Disconnect an app — revoke SDK connection and clear local DB."""
        try:
            # 1) Try to revoke the connected account via Composio v3 SDK
            app_info = (await self.get_app_info(app_id)) or {}
            composio_app = app_info.get("composio_app", "")
            if composio_app and self.api_key:
                try:
                    client = self._get_client()
                    sdk_connections = self._get_sdk_connections(organization_id)
                    sdk_conn = sdk_connections.get(composio_app, {})
                    conn_id = sdk_conn.get("id")
                    if client and conn_id:
                        try:
                            await asyncio.to_thread(
                                client.connected_accounts.delete, conn_id
                            )
                            logger.info(
                                f"Revoked Composio connected account {conn_id} for {app_id}"
                            )
                        except Exception as api_err:
                            logger.warning(f"Could not revoke Composio connection: {api_err}")
                except Exception as sdk_err:
                    logger.warning(f"Could not revoke SDK connection for {app_id}: {sdk_err}")

            # 2) Add to local blocklist so SDK status is ignored until reconnected
            await self._add_to_blocklist(organization_id, app_id)

            # 3) Delete local DB entries
            key = f"composio_connection_{app_id}"
            await db_client.delete_configuration(organization_id, key)

            cred_key = f"composio_credentials_{app_id}"
            await db_client.delete_configuration(organization_id, cred_key)

            settings_key = f"composio_settings_{app_id}"
            await db_client.delete_configuration(organization_id, settings_key)

            logger.info(f"Disconnected {app_id}")
            return True
        except Exception as e:
            logger.error(f"Error disconnecting: {e}")
            return False

    async def _add_to_blocklist(self, organization_id: int, app_id: str) -> None:
        """Mark an app as explicitly disconnected so SDK status is ignored."""
        key = "composio_disconnected_apps"
        config = await db_client.get_configuration(organization_id, key)
        current: list = []
        if config and config.value:
            current = config.value.get("app_ids", [])
        if app_id not in current:
            current.append(app_id)
        await db_client.upsert_configuration(organization_id, key, {"app_ids": current})

    async def _remove_from_blocklist(self, organization_id: int, app_id: str) -> None:
        """Remove an app from the disconnect blocklist when reconnecting."""
        key = "composio_disconnected_apps"
        config = await db_client.get_configuration(organization_id, key)
        if config and config.value:
            current = config.value.get("app_ids", [])
            if app_id in current:
                current.remove(app_id)
                await db_client.upsert_configuration(
                    organization_id, key, {"app_ids": current}
                )

    async def get_app_settings(
        self,
        organization_id: int,
        app_id: str,
    ) -> Dict[str, Any]:
        """Get app-specific settings (spreadsheet ID, table name, etc.)."""
        key = f"composio_settings_{app_id}"
        config = await db_client.get_configuration(organization_id, key)
        if config and config.value:
            return config.value.get("settings", {})
        return {}

    async def save_app_settings(
        self,
        organization_id: int,
        app_id: str,
        settings: Dict[str, Any],
    ) -> bool:
        """Save app-specific settings."""
        try:
            key = f"composio_settings_{app_id}"
            value = {"settings": settings, "app_id": app_id}
            await db_client.upsert_configuration(organization_id, key, value)
            logger.info(f"Saved settings for {app_id}: {list(settings.keys())}")
            return True
        except Exception as e:
            logger.error(f"Error saving settings for {app_id}: {e}")
            return False
    
    async def execute_action(
        self,
        organization_id: int,
        app_id: str,
        action_name: str,
        params: Dict[str, Any],
    ) -> ComposioActionResponse:
        """Execute an action on a connected app.
        
        The Composio SDK's execute_action is synchronous, so we run it
        in a thread pool to avoid blocking the async event loop.
        """
        app_info = await self.get_app_info(app_id)
        if not app_info:
            return ComposioActionResponse(success=False, error=f"Unknown app: {app_id}")
        
        # First check local database
        connections = await self._get_stored_connections(organization_id)
        connection = next((c for c in connections if c.get("app_id") == app_id), None)
        is_connected = connection and connection.get("is_active")
        
        # If not in local DB, check Composio SDK directly (for OAuth apps)
        if not is_connected:
            logger.debug(f"No local connection for {app_id}, checking Composio SDK...")
            sdk_status = await asyncio.to_thread(self._get_sdk_connections, organization_id)
            composio_app = app_info.get("composio_app", app_id.upper())
            sdk_conn = sdk_status.get(composio_app, {})
            
            if sdk_conn and str(sdk_conn.get("status", "")).upper() == "ACTIVE":
                logger.info(f"Found active {app_id} connection in Composio SDK (not in local DB)")
                is_connected = True
                connected_account_id = sdk_conn.get("id", "")
                if connected_account_id:
                    await self._store_connection(
                        organization_id=organization_id,
                        user_id=0,
                        app_id=app_id,
                        connected_account_id=connected_account_id,
                        is_active=True,
                    )
        
        if not is_connected:
            return ComposioActionResponse(
                success=False,
                error=f"{app_info['name']} is not connected. Please connect it from the Integrations page.",
            )
        
        try:
            client = self._get_client()
            if not client:
                return ComposioActionResponse(success=False, error="Composio SDK not available. Install with: pip install -U composio")

            composio_user_id = self._user_id(organization_id)

            logger.info(f"[COMPOSIO] Executing tool: {action_name} for {app_id} (user={composio_user_id})")
            logger.info(f"[COMPOSIO] Params: {params}")

            # v3: tools.execute(slug, arguments, *, user_id=...)
            def _execute():
                return client.tools.execute(
                    action_name,
                    params,
                    user_id=composio_user_id,
                )

            result = await asyncio.to_thread(_execute)

            logger.info(f"[COMPOSIO] Tool result type: {type(result)}")
            logger.info(f"[COMPOSIO] Tool result: {result}")

            # v3 returns a ToolExecuteResponse with {successful/successfull, data, error}.
            # Normalize both object and dict shapes.
            def _attr(obj, *names):
                for n in names:
                    v = getattr(obj, n, None)
                    if v is None and isinstance(obj, dict):
                        v = obj.get(n)
                    if v is not None:
                        return v
                return None

            successful = _attr(result, "successful", "successfull", "success")
            data = _attr(result, "data")
            error = _attr(result, "error")

            if successful is False or error:
                error_msg = error or "Composio tool execution failed"
                logger.error(f"[COMPOSIO] Tool failed: {error_msg}")
                return ComposioActionResponse(
                    success=False,
                    data=data if isinstance(data, dict) else ({"result": data} if data is not None else None),
                    error=str(error_msg),
                )

            if isinstance(data, dict):
                return ComposioActionResponse(success=True, data=data)
            if data is not None:
                return ComposioActionResponse(success=True, data={"result": data})

            # Fall back to the raw result when no structured fields are present.
            if isinstance(result, dict):
                return ComposioActionResponse(success=True, data=result)
            return ComposioActionResponse(success=True, data={"result": result})

        except Exception as e:
            logger.error(f"[COMPOSIO] Error executing tool {action_name}: {e}", exc_info=True)
            return ComposioActionResponse(success=False, error=f"Composio execution failed: {str(e)}")
    
    async def get_available_actions(self, app_id: str) -> List[Dict[str, Any]]:
        """Get available tools (actions) for an app/toolkit."""
        app_info = await self.get_app_info(app_id)
        if not app_info:
            return []
        
        try:
            client = self._get_client()
            if not client:
                return []
            
            toolkit = self._toolkit_slug(app_info, app_id)
            user_id = "default"  # listing tool schemas does not require a real user

            def _get_tools():
                # v3: tools.get(user_id, toolkits=[...]) returns tool schemas
                return client.tools.get(user_id, toolkits=[toolkit])

            tools = await asyncio.to_thread(_get_tools)
            items = getattr(tools, "items", None)
            if items is None:
                items = tools if isinstance(tools, list) else []

            results = []
            for tool in items:
                name = (
                    getattr(tool, "slug", None)
                    or getattr(tool, "name", None)
                    or (tool.get("slug") or tool.get("name") if isinstance(tool, dict) else None)
                    or str(tool)
                )
                description = (
                    getattr(tool, "description", None)
                    or (tool.get("description") if isinstance(tool, dict) else None)
                    or ""
                )
                results.append({"name": name, "description": description})
            return results
                
        except Exception as e:
            logger.error(f"Error getting tools: {e}")
            return []
    
    # =========================================================================
    # Database Helpers
    # =========================================================================
    
    async def _get_stored_connections(self, organization_id: int) -> List[Dict[str, Any]]:
        """Get stored connections from database.

        Scans by the ``composio_connection_`` key prefix so any connected app
        (including ones discovered dynamically from the Composio catalog) is
        returned, not just the curated COMPOSIO_APPS entries.
        """
        prefix = "composio_connection_"
        all_configs = await db_client.get_all_configurations(organization_id)

        connections = []
        for config in all_configs:
            key = getattr(config, "key", "")
            if not key.startswith(prefix) or not config.value:
                continue
            app_id = key[len(prefix):]
            connections.append({
                "app_id": app_id,
                "connected_account_id": config.value.get("connected_account_id"),
                "is_active": config.value.get("is_active", False),
                "connected_at": config.created_at,
            })

        return connections
    
    async def _store_connection(
        self,
        organization_id: int,
        user_id: int,
        app_id: str,
        connected_account_id: str,
        is_active: bool = True,
    ) -> None:
        """Store connection in database and remove from blocklist."""
        key = f"composio_connection_{app_id}"
        value = {
            "connected_account_id": connected_account_id,
            "is_active": is_active,
            "connected_by": user_id,
            "app_id": app_id,
        }
        await db_client.upsert_configuration(organization_id, key, value)
        await self._remove_from_blocklist(organization_id, app_id)
        logger.info(f"Stored connection {app_id} (active={is_active})")
    
    async def _update_connection_status(
        self,
        organization_id: int,
        app_id: str,
        is_active: bool,
    ) -> None:
        """Update connection status."""
        key = f"composio_connection_{app_id}"
        config = await db_client.get_configuration(organization_id, key)
        
        if config and config.value:
            value = config.value.copy()
            value["is_active"] = is_active
            await db_client.upsert_configuration(organization_id, key, value)


# =============================================================================
# Database Service (Direct connections, not via Composio)
# =============================================================================

class DatabaseService:
    """Direct database connections for Supabase and MySQL."""

    @staticmethod
    def _extract_supabase_credentials(raw_value: Any) -> Dict[str, str]:
        """Normalize Supabase credentials across legacy/new config shapes."""
        if not isinstance(raw_value, dict):
            return {"project_url": "", "api_key": ""}

        candidates: List[Dict[str, Any]] = [raw_value]
        nested = raw_value.get("credentials")
        if isinstance(nested, dict):
            candidates.append(nested)
            nested_nested = nested.get("credentials")
            if isinstance(nested_nested, dict):
                candidates.append(nested_nested)

        best_project_url = ""
        best_api_key = ""
        for candidate in candidates:
            project_url = str(
                candidate.get("project_url")
                or candidate.get("supabase_url")
                or candidate.get("url")
                or ""
            ).strip()
            api_key = str(
                candidate.get("service_role_key")
                or candidate.get("api_key")
                or candidate.get("anon_key")
                or ""
            ).strip()
            if project_url and api_key:
                return {"project_url": project_url.rstrip("/"), "api_key": api_key}
            if project_url and not best_project_url:
                best_project_url = project_url.rstrip("/")
            if api_key and not best_api_key:
                best_api_key = api_key

        return {"project_url": best_project_url, "api_key": best_api_key}
    
    @staticmethod
    async def execute_supabase_query(
        organization_id: int,
        table: str,
        operation: str,
        data: Optional[Dict[str, Any]] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute Supabase query."""
        from supabase import create_client, Client
        
        key = "integration_supabase"
        config = await db_client.get_configuration(organization_id, key)
        
        if not config or not config.value:
            return {"success": False, "error": "Supabase not configured"}

        creds = DatabaseService._extract_supabase_credentials(config.value)
        project_url = creds.get("project_url")
        api_key = creds.get("api_key")

        if not project_url or not api_key:
            return {"success": False, "error": "Missing credentials"}
        
        try:
            supabase: Client = create_client(project_url, api_key)
            
            if operation == "select":
                query = supabase.table(table).select("*")
                if filters:
                    for k, v in filters.items():
                        query = query.eq(k, v)
                result = query.execute()
                return {"success": True, "data": result.data}
            
            elif operation == "insert":
                if not data:
                    return {"success": False, "error": "No data"}
                result = supabase.table(table).insert(data).execute()
                return {"success": True, "data": result.data}
            
            elif operation == "update":
                if not data or not filters:
                    return {"success": False, "error": "Data and filters required"}
                query = supabase.table(table).update(data)
                for k, v in filters.items():
                    query = query.eq(k, v)
                result = query.execute()
                return {"success": True, "data": result.data}
            
            elif operation == "delete":
                if not filters:
                    return {"success": False, "error": "Filters required"}
                query = supabase.table(table).delete()
                for k, v in filters.items():
                    query = query.eq(k, v)
                result = query.execute()
                return {"success": True, "data": result.data}
            
            return {"success": False, "error": f"Unknown operation: {operation}"}
                
        except Exception as e:
            logger.error(f"Supabase error: {e}")
            return {"success": False, "error": str(e)}
    
    @staticmethod
    def _is_read_only_query(query: str) -> bool:
        """Allow only a single read-only SELECT/WITH statement.

        This blocks data modification (INSERT/UPDATE/DELETE), DDL
        (DROP/ALTER/CREATE/TRUNCATE), privilege changes, stored-procedure calls,
        file access, and multi-statement/stacked injection.
        """
        import re

        if not query or not query.strip():
            return False

        # Strip a single trailing semicolon, then reject any remaining ';'
        # (i.e. stacked/multiple statements).
        stripped = query.strip().rstrip(";").strip()
        if ";" in stripped:
            return False

        upper = stripped.upper()
        if not (upper.startswith("SELECT") or upper.startswith("WITH")):
            return False

        # Reject dangerous keywords even inside an otherwise SELECT-shaped query.
        forbidden = (
            r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b",
            r"\bALTER\b", r"\bCREATE\b", r"\bTRUNCATE\b", r"\bREPLACE\b",
            r"\bGRANT\b", r"\bREVOKE\b", r"\bCALL\b", r"\bMERGE\b",
            r"\bINTO\s+OUTFILE\b", r"\bINTO\s+DUMPFILE\b", r"\bLOAD_FILE\b",
            r"\bLOAD\s+DATA\b", r"\bSET\b", r"\bLOCK\b", r"\bHANDLER\b",
        )
        for pattern in forbidden:
            if re.search(pattern, upper):
                return False
        return True

    @staticmethod
    async def execute_mysql_query(
        organization_id: int,
        query: str,
        params: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a read-only, parameterized MySQL query.

        Only a single SELECT/WITH statement is permitted; any attempt to modify
        data, run DDL, stack statements, or access files is rejected.
        """
        import aiomysql

        if not DatabaseService._is_read_only_query(query):
            logger.warning(
                f"[MySQL] Rejected non-read-only query for org {organization_id}"
            )
            return {
                "success": False,
                "error": "Only single read-only SELECT queries are permitted.",
            }

        key = "integration_mysql"
        config = await db_client.get_configuration(organization_id, key)
        
        if not config or not config.value:
            return {"success": False, "error": "MySQL not configured"}
        
        creds = config.value.get("credentials", {})
        
        conn = None
        try:
            conn = await aiomysql.connect(
                host=creds.get("host", "localhost"),
                port=int(creds.get("port", 3306)),
                user=creds.get("username"),
                password=creds.get("password"),
                db=creds.get("database"),
            )
            
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(query, params or ())
                result = await cursor.fetchall()
                return {"success": True, "data": list(result)}
            
        except Exception as e:
            logger.error(f"MySQL error: {e}")
            return {"success": False, "error": str(e)}
        finally:
            if conn:
                conn.close()


# =============================================================================
# Singleton Instances
# =============================================================================

composio_service = ComposioService()
database_service = DatabaseService()
