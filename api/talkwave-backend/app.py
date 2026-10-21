"""Set up logging before importing anything else.

Composio integration: Using SDK for OAuth connections.
"""

import os
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from api.constants import REDIS_URL, SENTRY_DSN, UI_APP_URL
from api.logging_config import ENVIRONMENT, setup_logging

# Set up logging and get the listener for cleanup
setup_logging()

SENTRY_TRACES_SAMPLE_RATE = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.2"))
SENTRY_PROFILES_SAMPLE_RATE = float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.1"))

import logging as _logging

print(f"[SENTRY] DSN present: {bool(SENTRY_DSN)}")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=ENVIRONMENT,
        release=os.getenv("RAILWAY_GIT_COMMIT_SHA", "dev"),
        send_default_pii=True,
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=SENTRY_PROFILES_SAMPLE_RATE,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
            AsyncioIntegration(),
            LoggingIntegration(
                level=_logging.WARNING,
                event_level=_logging.ERROR,
            ),
        ],
        _experiments={
            "continuous_profiling_auto_start": True,
        },
    )
    print(f"[SENTRY] Initialized in environment: {ENVIRONMENT}")
else:
    print("[SENTRY] SKIPPED — SENTRY_DSN environment variable is not set")

    # Bridge loguru -> Sentry so logger.error() / logger.critical() become Sentry events
    # and logger.warning() becomes Sentry breadcrumbs.
    import loguru as _loguru

    def _sentry_sink(message):
        record = message.record
        level = record["level"].name
        exc = record["exception"]

        if exc and exc.value:
            sentry_sdk.capture_exception(exc.value)
        elif level in ("ERROR", "CRITICAL"):
            sentry_sdk.capture_message(
                record["message"],
                level="fatal" if level == "CRITICAL" else "error",
            )
        elif level == "WARNING":
            sentry_sdk.add_breadcrumb(
                message=record["message"],
                level="warning",
                category="loguru",
            )

    _loguru.logger.add(_sentry_sink, level="WARNING", format="{message}")


import asyncio
import traceback
from contextlib import asynccontextmanager
from typing import Optional

import redis.asyncio as aioredis
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from api.routes.main import router as main_router
from api.routes.rtc_offer import pcs_map
from api.services.security.rate_limiter import limiter
from api.services.security.headers import SecurityHeadersMiddleware
from api.services.telephony.worker_event_subscriber import (
    WorkerEventSubscriber,
    setup_worker_subscriber,
)
from api.tasks.arq import get_arq_redis

API_PREFIX = "/api/v1"

# Global reference to worker subscriber for graceful shutdown
worker_subscriber_instance: Optional[WorkerEventSubscriber] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global worker_subscriber_instance

    redis = None
    worker_subscriber = None

    # ── Ensure KB workflow_id column exists (non-fatal) ─────────
    try:
        from sqlalchemy import text as sa_text
        from api.db.base_client import _shared_engine

        async with _shared_engine.begin() as _conn:
            col_exists = await _conn.scalar(sa_text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='knowledge_base_documents' AND column_name='workflow_id'"
            ))
            if not col_exists:
                await _conn.execute(sa_text(
                    "ALTER TABLE knowledge_base_documents "
                    "ADD COLUMN workflow_id INTEGER REFERENCES workflows(id) ON DELETE SET NULL"
                ))
                await _conn.execute(sa_text(
                    "CREATE INDEX IF NOT EXISTS ix_kb_documents_workflow_id "
                    "ON knowledge_base_documents (workflow_id)"
                ))
                logger.info("Added workflow_id column to knowledge_base_documents")
            else:
                logger.info("workflow_id column already exists on knowledge_base_documents")
    except Exception as e:
        logger.warning(f"KB schema migration failed (non-fatal): {e}")

    # ── Ensure workflow_improvements table exists (non-fatal) ────
    try:
        from sqlalchemy import text as sa_text
        from api.db.base_client import _shared_engine

        async with _shared_engine.begin() as _conn:
            table_exists = await _conn.scalar(sa_text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name='workflow_improvements'"
            ))
            if not table_exists:
                # Create the enum type first (idempotent with IF NOT EXISTS via DO block)
                await _conn.execute(sa_text(
                    "DO $$ BEGIN "
                    "  CREATE TYPE improvement_status AS ENUM "
                    "    ('pending', 'accepted', 'rejected', 'auto_applied'); "
                    "EXCEPTION WHEN duplicate_object THEN NULL; "
                    "END $$"
                ))
                await _conn.execute(sa_text("""
                    CREATE TABLE workflow_improvements (
                        id SERIAL PRIMARY KEY,
                        workflow_id INTEGER NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
                        organization_id INTEGER NOT NULL REFERENCES organizations(id),
                        status improvement_status NOT NULL DEFAULT 'pending',
                        suggestions JSONB NOT NULL DEFAULT '[]',
                        analysis_summary TEXT,
                        calls_analyzed INTEGER NOT NULL DEFAULT 0,
                        last_run_id_analyzed INTEGER,
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """))
                await _conn.execute(sa_text(
                    "CREATE INDEX IF NOT EXISTS ix_workflow_improvements_workflow_id "
                    "ON workflow_improvements (workflow_id)"
                ))
                await _conn.execute(sa_text(
                    "CREATE INDEX IF NOT EXISTS ix_workflow_improvements_status "
                    "ON workflow_improvements (status)"
                ))
                await _conn.execute(sa_text(
                    "CREATE INDEX IF NOT EXISTS ix_workflow_improvements_workflow_status "
                    "ON workflow_improvements (workflow_id, status)"
                ))
                logger.info("Created workflow_improvements table")
            else:
                logger.info("workflow_improvements table already exists")
    except Exception as e:
        logger.warning(f"workflow_improvements table creation failed (non-fatal): {e}")

    # ── ARQ pool warmup (non-fatal) ──────────────────────────────
    try:
        await get_arq_redis()
    except Exception as e:
        logger.warning(f"ARQ Redis warmup failed — background tasks will be unavailable: {e}")

    # ── Redis for worker subscriber / pub-sub (non-fatal) ────────
    try:
        redis = await aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=10,
            retry_on_timeout=False,
        )
        # Quick ping to verify the connection actually works
        await asyncio.wait_for(redis.ping(), timeout=5)

        # Setup worker subscriber (ARI Manager runs separately)
        worker_subscriber = await setup_worker_subscriber(redis)
        worker_subscriber_instance = worker_subscriber

        # Store worker ID in app state for health check
        app.state.worker_id = worker_subscriber.worker_id
        app.state.worker_subscriber = worker_subscriber
        logger.info(f"Redis connected. Worker subscriber started (id={worker_subscriber.worker_id})")
    except Exception as e:
        logger.warning(f"Redis unavailable — worker subscriber disabled: {e}")
        redis = None
        worker_subscriber = None
        app.state.worker_id = "no-redis"
        app.state.worker_subscriber = None

    # Start the meeting agent auto-join scheduler
    try:
        from api.services.meeting.auto_join import auto_join_scheduler
        auto_join_scheduler.start()
    except Exception as e:
        logger.warning(f"Auto-join scheduler failed to start: {e}")

    yield  # ── Run app ───────────────────────────────────────────

    # Shutdown sequence
    logger.info("Starting graceful shutdown...")

    # Stop the meeting auto-join scheduler
    try:
        from api.services.meeting.auto_join import auto_join_scheduler as _ajs
        _ajs.stop()
    except Exception:
        pass

    # Wait for active call pipelines to finish
    from api.services.pipecat.run_pipeline import active_call_tracker
    logger.info(f"Active calls at shutdown: {active_call_tracker.active_count}")
    await active_call_tracker.wait_for_all(timeout=30.0)

    if worker_subscriber:
        try:
            await worker_subscriber.graceful_shutdown(max_wait_seconds=300)
        except Exception as e:
            logger.error(f"Error during graceful shutdown: {e}")
            try:
                await worker_subscriber.stop()
            except Exception:
                pass

    # Close shared HTTP session used by telephony providers
    from api.services.telephony.base import SharedHTTPSession
    await SharedHTTPSession.close()

    # Close meeting agent connection pools
    try:
        from api.services.meeting.connection_pool import pool_manager
        await pool_manager.close_all()
    except Exception as e:
        logger.warning(f"Meeting pool cleanup: {e}")

    # close all dangling pipecat connections
    coros = [pc.close() for pc in pcs_map.values()]
    await asyncio.gather(*coros)
    pcs_map.clear()

    # Flush PostHog events before shutdown
    from api.services.analytics.posthog_service import flush as posthog_flush
    posthog_flush()

    if redis:
        try:
            await redis.aclose()
        except Exception:
            pass


# Interactive API docs and the OpenAPI schema are useful in development but
# leak the full API surface (routes, schemas, auth requirements) in production.
# Disable them outside of local/dev/test unless explicitly re-enabled.
_docs_enabled = (
    ENVIRONMENT in ("local", "development", "test")
    or os.getenv("ENABLE_API_DOCS", "false").lower() == "true"
)

app = FastAPI(
    title="LanternAI API",
    description="API for the LanternAI voice agent platform",
    version="1.0.0",
    openapi_url=f"{API_PREFIX}/openapi.json" if _docs_enabled else None,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    lifespan=lifespan,
)

# ============================================================================
# Rate Limiting Configuration
# ============================================================================
# Attach rate limiter to app state for use in routes
app.state.limiter = limiter

# Add rate limit exceeded handler with user-friendly message
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Handle rate limit exceeded errors with a friendly message."""
    logger.warning(f"Rate limit exceeded for {request.url.path} from {request.client.host if request.client else 'unknown'}")
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please slow down your requests.",
            "error": "rate_limit_exceeded",
            "retry_after": getattr(exc, 'retry_after', 60),
        },
        headers={"Retry-After": str(getattr(exc, 'retry_after', 60))},
    )

# ============================================================================
# Middleware Stack Configuration
# ============================================================================
# Middleware is applied in REVERSE order of addition
# Order: CORS -> Security Headers -> Exception Logging -> SlowAPI Rate Limiting

# Add middleware to catch and log all exceptions
from starlette.middleware.base import BaseHTTPMiddleware

class ExceptionLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            logger.error(f"Exception in middleware on {request.method} {request.url.path}:")
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"Exception message: {str(e)}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            sentry_sdk.capture_exception(e)
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
            )

# 1. SlowAPI rate limiting (innermost - runs closest to route handlers)
app.add_middleware(SlowAPIMiddleware)

# 2. Exception logging
app.add_middleware(ExceptionLoggingMiddleware)

# 3. Security headers (adds security headers to all responses)
app.add_middleware(
    SecurityHeadersMiddleware,
    enable_hsts=ENVIRONMENT not in ("local", "development", "test"),
)

# 4. CORS (outermost - runs first on request, last on response)
# Configure CORS using environment variables for production flexibility
def get_cors_origins() -> list:
    """Get CORS origins from environment or use defaults."""
    # Check for custom CORS origins in environment
    custom_origins = os.getenv("CORS_ALLOWED_ORIGINS", "")
    if custom_origins:
        # Parse comma-separated origins
        origins = [origin.strip() for origin in custom_origins.split(",") if origin.strip()]
        if origins:
            return origins
    
    # Default origins for development
    default_origins = [
        "http://localhost:3000",
        "http://localhost:3010",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3010",
    ]
    
    # Add UI_APP_URL if configured and not already in list
    if UI_APP_URL and UI_APP_URL not in default_origins:
        default_origins.append(UI_APP_URL)
    
    return default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Add global exception handler to log all unhandled exceptions
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Log all unhandled exceptions and forward to Sentry."""
    logger.error(f"Unhandled exception on {request.method} {request.url.path}:")
    logger.error(f"Exception type: {type(exc).__name__}")
    logger.error(f"Exception message: {str(exc)}")
    logger.error(f"Traceback:\n{traceback.format_exc()}")
    sentry_sdk.capture_exception(exc)
    
    if ENVIRONMENT in ("local", "development", "test"):
        detail = f"Internal server error: {str(exc)}"
    else:
        detail = "An internal error occurred. Please try again later."
    
    return JSONResponse(
        status_code=500,
        content={"detail": detail},
    )

api_router = APIRouter()

# include subrouters here
api_router.include_router(main_router)

# main router with api prefix
app.include_router(api_router, prefix=API_PREFIX)

# Serve static assets (logo, embed widget, etc.)
_assets_dir = Path(__file__).resolve().parent / "assets"
if _assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")
