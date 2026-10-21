"""ARQ worker configuration - setup logging before importing tasks"""

import ssl
from urllib.parse import urlparse

from api.constants import REDIS_URL

# Setup logging - this is now idempotent and safe to call multiple times
from api.logging_config import setup_logging
from api.tasks.function_names import FunctionNames

setup_logging()

# Now import ARQ and task dependencies
from arq import create_pool, cron
from arq.connections import ArqRedis, RedisSettings

from api.tasks.workflow_run_cost import calculate_workflow_run_cost

parsed_url = urlparse(REDIS_URL)

# Check if we're using TLS (rediss://)
use_ssl = parsed_url.scheme == "rediss"

# Create SSL context if using rediss://
ssl_context = None
if use_ssl:
    ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

REDIS_SETTINGS = RedisSettings(
    host=parsed_url.hostname or "localhost",
    port=parsed_url.port or 6379,
    password=parsed_url.password,
    conn_timeout=10,
    ssl=use_ssl,
    ssl_ca_certs=None if not use_ssl else None,
    ssl_certfile=None,
    ssl_keyfile=None,
    ssl_check_hostname=False if use_ssl else None,
)

from api.tasks.campaign_tasks import (
    monitor_campaign_progress,
    process_campaign_batch,
    sync_campaign_source,
)
from api.tasks.run_integrations import run_integrations_post_workflow_run
from api.tasks.s3_upload import (
    upload_audio_to_s3,
    upload_transcript_to_s3,
    upload_voicemail_audio_to_s3,
)
from api.tasks.self_improve_tasks import (
    check_improvement_threshold,
    run_improvement_analysis_task,
)
from api.tasks.compliance_tasks import (
    compliance_audit_cleanup,
    compliance_dnc_cache_warm,
)
from api.services.workflow.rehearsal import run_workflow_rehearsal_task


import os as _os

_ARQ_MAX_JOBS = int(_os.getenv("ARQ_MAX_JOBS", "200"))


class WorkerSettings:
    functions = [
        calculate_workflow_run_cost,
        run_integrations_post_workflow_run,
        upload_audio_to_s3,
        upload_transcript_to_s3,
        upload_voicemail_audio_to_s3,
        sync_campaign_source,
        process_campaign_batch,
        monitor_campaign_progress,
        check_improvement_threshold,
        run_improvement_analysis_task,
        run_workflow_rehearsal_task,
        compliance_audit_cleanup,
        compliance_dnc_cache_warm,
    ]
    # Daily compliance audit-log retention cleanup at 03:30 UTC.
    cron_jobs = [
        cron(compliance_audit_cleanup, hour=3, minute=30),
    ]
    redis_settings = REDIS_SETTINGS
    max_jobs = _ARQ_MAX_JOBS


LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    # --- Handlers ---
    "handlers": {
        "console": {  # everything goes to stdout
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "level": "WARNING",  # only WARNING and above
            "formatter": "simple",
        },
    },
    # --- Formatters (optional) ---
    "formatters": {
        "simple": {
            "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        },
    },
    # --- Root logger ---
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    # --- Optionally silence Arq itself explicitly ---
    "loggers": {
        "arq": {  # arq.* loggers
            "level": "WARNING",
            "handlers": ["console"],
            "propagate": False,
        },
    },
}


_redis_pool: ArqRedis | None = None
_redis_available: bool = False

from loguru import logger as _arq_logger


async def get_arq_redis() -> ArqRedis | None:
    """Get the ARQ Redis pool. Returns None if Redis is unavailable."""
    global _redis_pool, _redis_available
    if _redis_pool is not None:
        return _redis_pool
    try:
        _redis_pool = await create_pool(REDIS_SETTINGS)
        _redis_available = True
        _arq_logger.info("ARQ Redis pool connected successfully")
        return _redis_pool
    except Exception as e:
        _arq_logger.warning(f"ARQ Redis pool unavailable: {e}. Background tasks will be skipped.")
        _redis_available = False
        return None


async def enqueue_job(
    function_name: FunctionNames,
    *args,
    _defer_until=None,
    _defer_by=None,
    _job_id: str | None = None,
):
    """
    Enqueue a background job with optional deferral and optional idempotency key.

    Passing `_job_id` makes this call idempotent: arq will refuse to enqueue a
    second job with the same id while the first is still queued/running. This
    is critical at scale — e.g. 1000 concurrent calls finishing at once would
    otherwise spawn 1000 duplicate `check_improvement_threshold` jobs.
    """
    redis = await get_arq_redis()
    if redis is None:
        _arq_logger.warning(f"Skipping background job '{function_name}' — Redis unavailable")
        return
    kwargs = {"_defer_until": _defer_until, "_defer_by": _defer_by}
    if _job_id:
        kwargs["_job_id"] = _job_id
    await redis.enqueue_job(function_name, *args, **kwargs)
