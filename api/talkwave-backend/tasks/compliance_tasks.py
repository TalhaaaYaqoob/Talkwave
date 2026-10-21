"""ARQ tasks for compliance maintenance.

- ``compliance_audit_cleanup``: enforces audit-log retention (default 5 years,
  the TCPA record-keeping baseline). Runs daily via cron.
- ``compliance_dnc_cache_warm``: re-warms the per-org Redis suppression cache
  for a given organization (invoked on demand).
"""

from datetime import UTC, datetime, timedelta

from loguru import logger

from api.db import db_client

# 5 years — covers the longer of TCPA (5y) record-keeping. UK GDPR allows
# retention while there's a lawful basis; audit rows store only a hash (no PII).
DEFAULT_AUDIT_RETENTION_DAYS = 5 * 365


async def compliance_audit_cleanup(ctx, retention_days: int = DEFAULT_AUDIT_RETENTION_DAYS):
    """Delete compliance audit log rows older than the retention window."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    try:
        deleted = await db_client.delete_audit_logs_before(cutoff)
        logger.info(
            f"[Compliance] Audit cleanup removed {deleted} rows older than "
            f"{cutoff.isoformat()}"
        )
        return {"deleted": deleted, "cutoff": cutoff.isoformat()}
    except Exception as e:
        logger.error(f"[Compliance] Audit cleanup failed: {e}")
        return {"deleted": 0, "error": str(e)}


async def compliance_dnc_cache_warm(ctx, organization_id: int):
    """Warm the Redis suppression cache for an organization."""
    from api.services.compliance.dnc_service import dnc_service

    try:
        await dnc_service.warm_cache(organization_id)
        return {"warmed": True, "organization_id": organization_id}
    except Exception as e:
        logger.warning(
            f"[Compliance] DNC cache warm failed for org {organization_id}: {e}"
        )
        return {"warmed": False, "error": str(e)}
