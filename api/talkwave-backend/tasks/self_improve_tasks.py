"""
ARQ tasks for self-improving agent analysis.

check_improvement_threshold: lightweight check after each call — counts runs
since last analysis and triggers full analysis only when the threshold is met.

run_improvement_analysis: loads recent transcripts (memory-efficient sampling),
runs the CrewAI crew, and stores results.

Scale-safety:
  - Both tasks are idempotency-keyed at the ARQ layer so duplicate scheduling
    from 1000 simultaneous call-end events doesn't spawn 1000 analyses.
  - `run_improvement_analysis_task` takes a per-workflow Redis lock (SET NX
    with TTL) so two workers can never run overlapping analyses on the
    same workflow — preventing duplicate improvement rows and racey costs.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict

from loguru import logger

# Minimum gap between two consecutive AUTOMATIC analyses for the same workflow.
# 10 hours by default so the LLM-heavy crew doesn't fire too often in
# production. Users who want to iterate faster can either:
#   - lower it per-workflow via `workflow_configurations.auto_improve_cooldown_minutes`
#   - hit the "Re-analyse all calls" button in workflow Settings (manual
#     trigger bypasses the cooldown entirely).
DEFAULT_COOLDOWN_MINUTES = 10 * 60
DEFAULT_INTERVAL = 10

# Self-improve analysis is CPU/token-heavy (4 LLM calls × 3 agents). Cap to
# 10 minutes so a stuck run releases the lock and doesn't block forever.
ANALYSIS_LOCK_TTL_SECONDS = 600
_ANALYSIS_LOCK_PREFIX = "lock:self_improve:"


@asynccontextmanager
async def _analysis_lock(workflow_id: int):
    """
    Async context manager that acquires a per-workflow Redis lock.
    Yields True if the lock was acquired, False otherwise. Always releases
    on exit (if it was actually acquired by us).
    """
    from api.tasks.arq import get_arq_redis

    redis = await get_arq_redis()
    if redis is None:
        # Redis unavailable → skip locking, proceed best-effort
        yield True
        return

    key = f"{_ANALYSIS_LOCK_PREFIX}{workflow_id}"
    # Random token so we only delete the lock if we still own it.
    import os
    token = os.urandom(8).hex()
    try:
        # SET NX PX  (arq's redis client supports this)
        acquired = await redis.set(key, token, ex=ANALYSIS_LOCK_TTL_SECONDS, nx=True)
    except Exception as e:
        logger.warning(f"[SelfImprove] Lock acquire error for workflow {workflow_id}: {e}")
        yield True  # don't block analysis on lock failures
        return

    if not acquired:
        logger.info(f"[SelfImprove] Lock busy for workflow {workflow_id} — skipping (another worker is analyzing)")
        yield False
        return

    try:
        yield True
    finally:
        try:
            # Only delete if token still matches (safe unlock)
            current = await redis.get(key)
            if current and (current.decode() if isinstance(current, bytes) else current) == token:
                await redis.delete(key)
        except Exception:
            pass


async def check_improvement_threshold(ctx: Dict, workflow_id: int, organization_id: int):
    """Check if a workflow has enough new calls to trigger improvement analysis."""
    from api.db import db_client

    try:
        workflow = await db_client.get_workflow_by_id(workflow_id)
        if not workflow:
            return

        configs = workflow.workflow_configurations or {}
        if not configs.get("auto_improve_enabled", False):
            return

        interval = configs.get("auto_improve_interval", DEFAULT_INTERVAL)
        cooldown_minutes = configs.get("auto_improve_cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)

        last_run_id = await db_client.get_last_analyzed_run_id(workflow_id)

        new_count = await db_client.count_completed_runs_since(workflow_id, last_run_id)

        if new_count < interval:
            return

        if cooldown_minutes > 0:
            improvements = await db_client.get_improvements_for_workflow(workflow_id, limit=1)
            if improvements:
                last_analysis_time = improvements[0].created_at
                if last_analysis_time and last_analysis_time.tzinfo is None:
                    last_analysis_time = last_analysis_time.replace(tzinfo=timezone.utc)
                cooldown_cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
                if last_analysis_time > cooldown_cutoff:
                    logger.debug(
                        f"[SelfImprove] Cooldown active for workflow {workflow_id} "
                        f"(last run was {last_analysis_time.isoformat()}, "
                        f"cooldown={cooldown_minutes}min) — skipping"
                    )
                    return

        logger.info(f"[SelfImprove] Threshold met for workflow {workflow_id}: {new_count} new calls (interval={interval})")

        from api.tasks.arq import enqueue_job
        from api.tasks.function_names import FunctionNames

        # Idempotent enqueue: only one run_improvement_analysis job can exist
        # per workflow at a time. Clears after ANALYSIS_LOCK_TTL_SECONDS.
        await enqueue_job(
            FunctionNames.RUN_IMPROVEMENT_ANALYSIS,
            workflow_id,
            organization_id,
            _job_id=f"improve_run:{workflow_id}",
        )

    except Exception as e:
        err_str = str(e)
        if "does not exist" in err_str or "UndefinedTableError" in err_str:
            logger.warning(f"[SelfImprove] workflow_improvements table missing — run 'alembic upgrade head' to create it")
        else:
            logger.error(f"[SelfImprove] Error checking threshold for workflow {workflow_id}: {e}")


async def run_improvement_analysis_task(
    ctx: Dict,
    workflow_id: int,
    organization_id: int,
    force: bool = False,
):
    """Load recent transcripts, run CrewAI analysis, store suggestions.

    `force=True` bypasses the `auto_improve_enabled` gate so a manual
    "Analyze now" click from the UI can produce results even when the
    workflow has the automatic toggle off.
    """
    from api.db import db_client

    async with _analysis_lock(workflow_id) as acquired:
        if not acquired:
            return

        try:
            workflow = await db_client.get_workflow_by_id(workflow_id)
            if not workflow:
                logger.warning(f"[SelfImprove] Workflow {workflow_id} not found")
                return

            configs = workflow.workflow_configurations or {}
            if not force and not configs.get("auto_improve_enabled", False):
                return

            last_run_id = await db_client.get_last_analyzed_run_id(workflow_id)

            runs = await db_client.get_recent_completed_runs(
                workflow_id=workflow_id,
                since_run_id=last_run_id,
                limit=20,
            )

            # If a manual "Analyze now" was fired but nothing has happened since
            # the last marker, fall back to the most recent 20 calls overall so
            # the user still gets a fresh analysis instead of silent skip.
            if not runs and force:
                runs = await db_client.get_recent_completed_runs(
                    workflow_id=workflow_id,
                    since_run_id=None,
                    limit=20,
                )

            if not runs:
                logger.info(f"[SelfImprove] No new runs to analyze for workflow {workflow_id}")
                return

            disposition_counts: dict = {}
            total_duration = 0
            early_hangups = 0
            for r in runs:
                gc = r.gathered_context or {}
                d = gc.get("mapped_call_disposition", "UNKNOWN")
                disposition_counts[d] = disposition_counts.get(d, 0) + 1
                dur = (r.usage_info or {}).get("call_duration_seconds", 0)
                total_duration += dur
                if dur < 15:
                    early_hangups += 1

            aggregate_stats = {
                "total_calls": len(runs),
                "disposition_counts": disposition_counts,
                "avg_duration_seconds": round(total_duration / len(runs), 1) if runs else 0,
                "early_hangup_count": early_hangups,
                "early_hangup_pct": round(early_hangups / len(runs) * 100, 1) if runs else 0,
            }

            # Prefer the current-definition relationship over the legacy field so
            # the architect reasons against the actual live workflow shape.
            workflow_def = (
                getattr(workflow, "workflow_definition_with_fallback", None)
                or workflow.workflow_definition
                or {}
            )

            past_improvements = await db_client.get_improvements_for_workflow(workflow_id, limit=5)
            past_suggestions: list[dict] = []
            for imp in past_improvements:
                if imp.suggestions:
                    past_suggestions.extend(imp.suggestions)

            from api.services.workflow.self_improve import run_improvement_analysis

            result = await run_improvement_analysis(
                workflow_id=workflow_id,
                organization_id=organization_id,
                workflow_name=workflow.name,
                workflow_definition=workflow_def,
                runs=runs,
                aggregate_stats=aggregate_stats,
                past_suggestions=past_suggestions,
            )

            suggestions = result.get("suggestions", [])

            if not suggestions:
                # No issues to suggest — still advance the "last analyzed" marker
                # so the threshold doesn't re-trigger on every new call.
                last_analyzed = result.get("last_run_id", 0)
                if last_analyzed:
                    marker = await db_client.create_improvement(
                        workflow_id=workflow_id,
                        organization_id=organization_id,
                        suggestions=[],
                        analysis_summary=result.get("analysis_summary", "No issues detected."),
                        calls_analyzed=result.get("calls_analyzed", 0),
                        last_run_id_analyzed=last_analyzed,
                    )
                    await db_client.update_improvement_status(marker.id, "auto_applied")
                logger.info(f"[SelfImprove] No suggestions generated for workflow {workflow_id} (marker stored)")
                return

            auto_apply_threshold = configs.get("auto_apply_threshold", 0)

            # spawn_workflow creates a brand-new workflow on the user's dashboard —
            # always require an explicit click for that, regardless of how confident
            # the architect was.
            NEVER_AUTO_APPLY_TYPES = {"spawn_workflow"}

            auto_applied = []
            pending = []
            for s in suggestions:
                if (
                    auto_apply_threshold > 0
                    and s.get("confidence", 0) >= auto_apply_threshold
                    and s.get("type") not in NEVER_AUTO_APPLY_TYPES
                ):
                    auto_applied.append(s)
                else:
                    pending.append(s)

            if pending:
                await db_client.create_improvement(
                    workflow_id=workflow_id,
                    organization_id=organization_id,
                    suggestions=pending,
                    analysis_summary=result.get("analysis_summary", ""),
                    calls_analyzed=result.get("calls_analyzed", 0),
                    last_run_id_analyzed=result.get("last_run_id", 0),
                )

            if auto_applied:
                await db_client.create_improvement(
                    workflow_id=workflow_id,
                    organization_id=organization_id,
                    suggestions=auto_applied,
                    analysis_summary=f"Auto-applied {len(auto_applied)} high-confidence improvements.",
                    calls_analyzed=result.get("calls_analyzed", 0),
                    last_run_id_analyzed=result.get("last_run_id", 0),
                )
                improvements = await db_client.get_improvements_for_workflow(workflow_id, limit=1)
                if improvements:
                    await db_client.update_improvement_status(improvements[0].id, "auto_applied")

            total = len(pending) + len(auto_applied)
            logger.info(
                f"[SelfImprove] Stored {total} suggestions for workflow {workflow_id} "
                f"({len(pending)} pending, {len(auto_applied)} auto-applied)"
            )

        except Exception as e:
            logger.error(f"[SelfImprove] Analysis failed for workflow {workflow_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
