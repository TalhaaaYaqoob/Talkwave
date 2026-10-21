"""Campaign Orchestrator Service.

This service ensures continuous campaign processing by listening to events
and scheduling batches immediately upon completion. It also monitors campaigns
for final completion after 1 hour of inactivity and handles retry events.

State is stored in Redis so multiple orchestrator instances can run in parallel.
"""

from api.logging_config import setup_logging

setup_logging()


import asyncio
import os
import signal
from datetime import UTC, datetime, timedelta
from typing import Dict, Optional

import redis.asyncio as aioredis
from loguru import logger

from api.constants import REDIS_URL
from api.db import db_client
from api.db.models import CampaignModel, QueuedRunModel
from api.enums import RedisChannel
from api.services.campaign.campaign_event_protocol import (
    CampaignCompletedEvent,
    CampaignEventType,
    RetryNeededEvent,
    parse_campaign_event,
)
from api.tasks.arq import enqueue_job
from api.tasks.function_names import FunctionNames

CAMPAIGN_BATCH_SIZE = int(os.getenv("CAMPAIGN_BATCH_SIZE", "50"))

_LOCK_KEY_PREFIX = "campaign_orch:lock:"
_ACTIVITY_KEY_PREFIX = "campaign_orch:activity:"
_BATCH_KEY_PREFIX = "campaign_orch:batch:"
_LOCK_TTL = 10  # seconds
_BATCH_TTL = 600  # 10 minutes — auto-expire stuck batches


class CampaignOrchestrator:
    """Orchestrates campaign processing, retry handling, and completion detection.

    All coordination state is stored in Redis so the service can be scaled
    horizontally (multiple instances share the same keys).
    """

    def __init__(self, redis_client: aioredis.Redis):
        self.redis = redis_client
        self.completion_check_interval = 60
        self.completion_timeout = 3600
        self._running = False
        self._pubsub = None

    async def run(self):
        """Main service with two concurrent tasks."""
        self._running = True
        logger.info("Campaign Orchestrator starting...")

        try:
            # Task 1: Listen for events and react immediately
            event_task = asyncio.create_task(self._listen_for_events())

            # Task 2: Periodically check for stale campaigns
            completion_task = asyncio.create_task(self._monitor_completion())

            # Wait for both tasks
            await asyncio.gather(event_task, completion_task)

        except asyncio.CancelledError:
            logger.info("Campaign Orchestrator cancelled")
            raise
        except Exception as e:
            logger.error(f"Campaign Orchestrator error: {e}")
            raise
        finally:
            await self.shutdown()

    async def _listen_for_events(self):
        """Listen for campaign events and react immediately."""
        self._pubsub = self.redis.pubsub()
        await self._pubsub.subscribe(RedisChannel.CAMPAIGN_EVENTS.value)
        logger.info(f"Subscribed to {RedisChannel.CAMPAIGN_EVENTS.value} channel")

        async for message in self._pubsub.listen():
            if not self._running:
                break

            if message["type"] == "message":
                try:
                    event = parse_campaign_event(message["data"])
                    if event:
                        await self._handle_event(event)
                    else:
                        logger.error(
                            f"Failed to parse campaign event: {message['data']}"
                        )
                except Exception as e:
                    logger.error(f"Error handling campaign event: {e}")

    async def _handle_event(self, event):
        """Handle campaign events including retry events."""
        # Handle RetryNeededEvent
        if isinstance(event, RetryNeededEvent):
            await self._handle_retry_event(event)
            return

        # All events should have campaign_id
        if not hasattr(event, "campaign_id") or not event.campaign_id:
            logger.warning(f"Event missing campaign_id: {type(event).__name__}")
            return

        campaign_id = event.campaign_id
        event_type = event.type

        logger.debug(f"campaign_id: {campaign_id} - Received event: {event_type}")

        if event_type == CampaignEventType.BATCH_COMPLETED:
            await self.redis.delete(f"{_BATCH_KEY_PREFIX}{campaign_id}")
            logger.debug(
                f"campaign_id: {campaign_id} - Batch completed, cleared in-progress flag"
            )

            await self._schedule_next_batch(campaign_id)
            await self.redis.set(
                f"{_ACTIVITY_KEY_PREFIX}{campaign_id}",
                datetime.now(UTC).isoformat(),
                ex=self.completion_timeout + 60,
            )

        elif event_type == CampaignEventType.SYNC_COMPLETED:
            logger.info(
                f"campaign_id: {campaign_id} - Sync completed, starting processing"
            )
            await self._schedule_next_batch(campaign_id)
            await self.redis.set(
                f"{_ACTIVITY_KEY_PREFIX}{campaign_id}",
                datetime.now(UTC).isoformat(),
                ex=self.completion_timeout + 60,
            )

    async def _handle_retry_event(self, event: RetryNeededEvent):
        """Process retry event and schedule if eligible (from campaign_retry_manager)."""

        # Check retry eligibility
        campaign_id = event.campaign_id
        if not campaign_id:
            logger.debug("Skipping non-campaign retry event")
            return

        # Get campaign configuration
        campaign = await db_client.get_campaign_by_id(campaign_id)
        if not campaign:
            logger.error(f"campaign_id: {campaign_id} - Campaign not found")
            return

        retry_config = campaign.retry_config or {}
        if not retry_config.get("enabled", True):
            logger.info(f"campaign_id: {campaign_id} - Retry disabled")
            return

        # Check if this reason should be retried
        reason = event.reason
        if reason == "busy" and not retry_config.get("retry_on_busy", True):
            logger.info(f"campaign_id: {campaign_id} - Skipping retry for busy signal")
            return
        if reason == "no_answer" and not retry_config.get("retry_on_no_answer", True):
            logger.info(f"campaign_id: {campaign_id} - Skipping retry for no-answer")
            return
        if reason == "voicemail" and not retry_config.get("retry_on_voicemail", True):
            logger.info(f"campaign_id: {campaign_id} - Skipping retry for voicemail")
            return

        # Get the original queued run
        queued_run = await db_client.get_queued_run_by_id(event.queued_run_id)
        if not queued_run:
            logger.error(
                f"campaign_id: {campaign_id} - Queued run {event.queued_run_id} not found"
            )
            return

        max_retries = retry_config.get("max_retries", 1)

        if queued_run.retry_count >= max_retries:
            await self._mark_final_failure(queued_run, reason)
            logger.info(
                f"campaign_id: {campaign_id} - Max retries ({max_retries}) reached for queued run {queued_run.id}"
            )
            return

        retry_delay = retry_config.get("retry_delay_seconds", 120)
        await self._schedule_retry(queued_run, reason, retry_delay)

        await self.redis.set(
            f"{_ACTIVITY_KEY_PREFIX}{campaign_id}",
            datetime.now(UTC).isoformat(),
            ex=self.completion_timeout + 60,
        )

    async def _schedule_retry(
        self, original_run: QueuedRunModel, reason: str, delay_seconds: int
    ):
        """Create a new queued run for retry."""

        campaign_id = original_run.campaign_id

        # Create retry context
        retry_context = {
            **original_run.context_variables,
            "is_retry": True,
            "retry_attempt": original_run.retry_count + 1,
            "retry_reason": reason,
        }

        logger.debug(
            f"campaign_id: {campaign_id} - Scheduling retry for {reason} in {delay_seconds}s, "
            f"retry attempt {original_run.retry_count + 1}"
        )

        # Create retry entry with unique source_uuid
        retry_run = await db_client.create_queued_run(
            campaign_id=campaign_id,
            source_uuid=f"{original_run.source_uuid}_retry_{original_run.retry_count + 1}",
            context_variables=retry_context,
            state="queued",
            retry_count=original_run.retry_count + 1,
            parent_queued_run_id=original_run.id,
            scheduled_for=datetime.now(UTC) + timedelta(seconds=delay_seconds),
            retry_reason=reason,
        )

        logger.info(
            f"campaign_id: {campaign_id} - Scheduled retry {retry_run.id} for {reason} in {delay_seconds}s, "
            f"retry attempt {retry_run.retry_count}"
        )

    async def _mark_final_failure(self, queued_run: QueuedRunModel, reason: str):
        """Mark a queued run as finally failed after max retries."""
        campaign_id = queued_run.campaign_id

        # Update the campaign's failed_rows counter
        campaign = await db_client.get_campaign_by_id(campaign_id)
        if campaign:
            await db_client.update_campaign(
                campaign_id=campaign_id, failed_rows=campaign.failed_rows + 1
            )

        logger.info(
            f"campaign_id: {campaign_id} - Queued run {queued_run.id} finally failed after max retries, "
            f"last reason: {reason}"
        )

    async def _schedule_next_batch(self, campaign_id: int):
        """Schedule next batch immediately if work available.

        Uses a Redis key with NX + TTL to prevent duplicate scheduling
        across multiple orchestrator instances.
        """
        lock_key = f"{_LOCK_KEY_PREFIX}{campaign_id}"
        acquired = await self.redis.set(lock_key, "1", nx=True, ex=_LOCK_TTL)
        if not acquired:
            logger.debug(
                f"campaign_id: {campaign_id} - Batch already scheduled recently"
            )
            return

        try:
            campaign = await db_client.get_campaign_by_id(campaign_id)
            if not campaign:
                logger.error(f"campaign_id: {campaign_id} - Campaign not found")
                return

            if campaign.state not in ["running", "syncing"]:
                logger.info(
                    f"campaign_id: {campaign_id} - Campaign not in running state: {campaign.state}"
                )
                return

            has_work = await self._has_pending_work(campaign_id)

            if has_work:
                from api.services.campaign.calling_window import (
                    is_within_calling_window,
                    seconds_until_window_opens,
                )

                defer_by = None
                if not is_within_calling_window(
                    campaign.calling_window_start,
                    campaign.calling_window_end,
                    campaign.calling_window_timezone,
                ):
                    wait_secs = seconds_until_window_opens(
                        campaign.calling_window_start,
                        campaign.calling_window_end,
                        campaign.calling_window_timezone,
                    )
                    if wait_secs and wait_secs > 0:
                        defer_by = timedelta(seconds=wait_secs)
                        logger.info(
                            f"campaign_id: {campaign_id} - Outside calling window, "
                            f"deferring batch by {wait_secs:.0f}s"
                        )

                await enqueue_job(
                    FunctionNames.PROCESS_CAMPAIGN_BATCH,
                    campaign_id,
                    CAMPAIGN_BATCH_SIZE,
                    _defer_by=defer_by,
                )
                logger.info(f"campaign_id: {campaign_id} - Scheduled next batch (size={CAMPAIGN_BATCH_SIZE})")

                await self.redis.set(
                    f"{_BATCH_KEY_PREFIX}{campaign_id}",
                    datetime.now(UTC).isoformat(),
                    ex=_BATCH_TTL,
                )

                await db_client.update_campaign(
                    campaign_id=campaign_id,
                    last_batch_scheduled_at=datetime.now(UTC),
                    last_activity_at=datetime.now(UTC),
                )
            else:
                logger.info(
                    f"campaign_id: {campaign_id} - No pending work to process, "
                    f"campaign may complete or wait for retries"
                )

        except Exception as e:
            logger.error(f"campaign_id: {campaign_id} - Error scheduling batch: {e}")

    async def _monitor_completion(self):
        """Periodically check for campaigns that should be marked complete."""
        while self._running:
            try:
                await self._check_stale_campaigns()
            except Exception as e:
                logger.error(f"Completion monitoring failed: {e}")

            await asyncio.sleep(self.completion_check_interval)

    async def _check_stale_campaigns(self):
        """Check all running campaigns for completion or orphaned work.

        Also recovers campaigns stuck in 'syncing' state (e.g. after a
        server restart mid-sync) by re-enqueuing the sync job.
        """
        logger.debug("Checking for stale campaigns...")

        # Recover campaigns stuck in "syncing" after a server restart.
        syncing_campaigns = await db_client.get_campaigns_by_status(statuses=["syncing"])
        for sc in syncing_campaigns:
            try:
                stuck_since = sc.started_at or sc.created_at
                if stuck_since:
                    elapsed = (datetime.now(UTC) - stuck_since).total_seconds()
                else:
                    elapsed = 999
                if elapsed > 180:
                    # Check if rows were already synced (partial sync before crash).
                    queued_count = await db_client.get_queued_runs_count(
                        campaign_id=sc.id, states=["queued"]
                    )
                    if queued_count > 0:
                        logger.warning(
                            f"campaign_id: {sc.id} - Stuck in 'syncing' for {elapsed:.0f}s "
                            f"but {queued_count} rows already synced — promoting to 'running'"
                        )
                        await db_client.update_campaign(
                            campaign_id=sc.id,
                            state="running",
                            source_sync_status="completed",
                            source_last_synced_at=datetime.now(UTC),
                        )
                        await self._schedule_next_batch(sc.id)
                    else:
                        logger.warning(
                            f"campaign_id: {sc.id} - Stuck in 'syncing' for {elapsed:.0f}s, "
                            f"re-enqueuing sync job"
                        )
                        await enqueue_job(FunctionNames.SYNC_CAMPAIGN_SOURCE, sc.id)
            except Exception as e:
                logger.error(f"campaign_id: {sc.id} - Failed to recover syncing campaign: {e}")

        campaigns = await db_client.get_campaigns_by_status(statuses=["running"])

        for campaign in campaigns:
            try:
                campaign_id = campaign.id

                batch_key = f"{_BATCH_KEY_PREFIX}{campaign_id}"
                batch_val = await self.redis.get(batch_key)
                batch_in_progress = batch_val is not None

                if batch_in_progress:
                    try:
                        batch_start_time = datetime.fromisoformat(batch_val)
                        time_since = (datetime.now(UTC) - batch_start_time).total_seconds()
                        if time_since > 300:
                            logger.warning(
                                f"campaign_id: {campaign_id} - Batch stuck for {time_since:.0f}s, "
                                f"clearing flag and checking for more work"
                            )
                            await self.redis.delete(batch_key)
                            batch_in_progress = False

                            if await self._has_pending_work(campaign_id):
                                logger.info(
                                    f"campaign_id: {campaign_id} - Found pending work after stuck batch, "
                                    f"scheduling new batch"
                                )
                                await self._schedule_next_batch(campaign_id)
                                continue
                    except (ValueError, TypeError):
                        await self.redis.delete(batch_key)
                        batch_in_progress = False

                if not batch_in_progress:
                    has_work = await self._has_pending_work(campaign_id)
                    if has_work:
                        logger.info(
                            f"campaign_id: {campaign_id} - Found orphaned work (likely new retries), "
                            f"scheduling batch to process"
                        )
                        await self._schedule_next_batch(campaign_id)
                        continue

                if await self._should_mark_complete(campaign):
                    await self._complete_campaign(campaign)
            except Exception as e:
                logger.error(
                    f"campaign_id: {campaign.id} - Completion check failed: {e}"
                )

    async def _should_mark_complete(self, campaign: CampaignModel) -> bool:
        """Check if campaign has no activity for 1 hour."""
        campaign_id = campaign.id

        batch_exists = await self.redis.exists(f"{_BATCH_KEY_PREFIX}{campaign_id}")
        if batch_exists:
            logger.debug(
                f"campaign_id: {campaign_id} - Batch in progress, not marking complete"
            )
            return False

        has_work = await self._has_pending_work(campaign_id)
        if has_work:
            return False

        last_activity: Optional[datetime] = None
        activity_str = await self.redis.get(f"{_ACTIVITY_KEY_PREFIX}{campaign_id}")
        if activity_str:
            try:
                last_activity = datetime.fromisoformat(activity_str)
            except (ValueError, TypeError):
                pass

        if not last_activity:
            last_activity = campaign.last_activity_at
        if not last_activity:
            last_activity = campaign.last_batch_scheduled_at
        if not last_activity:
            last_activity = campaign.started_at

        if last_activity:
            time_since = datetime.now(UTC) - last_activity
            if time_since.total_seconds() < self.completion_timeout:
                return False

        logger.info(
            f"campaign_id: {campaign_id} - No activity for {self.completion_timeout}s, "
            f"marking complete"
        )
        return True

    async def _has_pending_work(self, campaign_id: int) -> bool:
        """Check if campaign has any work to do."""
        # Check queued runs
        queued_count = await db_client.get_queued_runs_count(
            campaign_id=campaign_id, states=["queued"]
        )

        if queued_count > 0:
            logger.debug(f"campaign_id: {campaign_id} - Has {queued_count} queued runs")
            return True

        # Check scheduled retries that are due
        scheduled_count = await db_client.get_scheduled_runs_count(
            campaign_id=campaign_id, scheduled_before=datetime.now(UTC)
        )

        if scheduled_count > 0:
            logger.debug(
                f"campaign_id: {campaign_id} - Has {scheduled_count} scheduled retries due"
            )
            return True

        return False

    async def _complete_campaign(self, campaign: CampaignModel):
        """Mark campaign as complete."""
        campaign_id = campaign.id

        try:
            # Double-check no pending work
            if await self._has_pending_work(campaign_id):
                logger.info(
                    f"campaign_id: {campaign_id} - Found pending work, not completing"
                )
                return

            # Update campaign status
            await db_client.update_campaign(
                campaign_id=campaign_id,
                state="completed",
                completed_at=datetime.now(UTC),
            )

            logger.info(f"campaign_id: {campaign_id} - Campaign marked as completed")

            # Publish completion event using typed event
            completion_event = CampaignCompletedEvent(
                campaign_id=campaign_id,
                total_rows=campaign.total_rows or 0,
                processed_rows=campaign.processed_rows,
                failed_rows=campaign.failed_rows,
            )

            # Calculate duration if started_at is available
            if campaign.started_at:
                duration = (datetime.now(UTC) - campaign.started_at).total_seconds()
                completion_event.duration_seconds = duration

            await self.redis.publish(
                RedisChannel.CAMPAIGN_EVENTS.value, completion_event.to_json()
            )

            await self.redis.delete(
                f"{_ACTIVITY_KEY_PREFIX}{campaign_id}",
                f"{_LOCK_KEY_PREFIX}{campaign_id}",
                f"{_BATCH_KEY_PREFIX}{campaign_id}",
            )

        except Exception as e:
            logger.error(
                f"campaign_id: {campaign_id} - Failed to complete campaign: {e}"
            )

    async def shutdown(self):
        """Clean shutdown of the orchestrator."""
        logger.info("Campaign Orchestrator shutting down...")
        self._running = False

        if self._pubsub:
            try:
                await self._pubsub.unsubscribe(RedisChannel.CAMPAIGN_EVENTS.value)
                await self._pubsub.aclose()
            except Exception as e:
                logger.error(f"Error closing pubsub: {e}")

        logger.info("Campaign Orchestrator shutdown complete")


async def main():
    """Main entry point for Campaign Orchestrator service."""

    # Setup Redis connection
    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)

    # Create and run orchestrator
    orchestrator = CampaignOrchestrator(redis)

    # Create a shutdown event for clean coordination
    shutdown_event = asyncio.Event()

    # Setup signal handlers
    loop = asyncio.get_event_loop()

    def signal_handler(signum):
        logger.info(f"Received shutdown signal {signum}")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))

    # Run orchestrator with shutdown monitoring
    orchestrator_task = asyncio.create_task(orchestrator.run())
    shutdown_task = asyncio.create_task(shutdown_event.wait())

    try:
        # Wait for either orchestrator to complete or shutdown signal
        done, _ = await asyncio.wait(
            [orchestrator_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
        )

        # If shutdown was triggered, stop the orchestrator
        if shutdown_task in done:
            logger.info("Shutdown signal received, stopping orchestrator...")
            orchestrator._running = False
            # Cancel the orchestrator task immediately since it may be blocked
            orchestrator_task.cancel()
            try:
                await orchestrator_task
            except asyncio.CancelledError:
                logger.info("Orchestrator task cancelled successfully")

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        # Ensure clean shutdown
        await orchestrator.shutdown()
        await redis.aclose()

        logger.info("Campaign Orchestrator service stopped")


if __name__ == "__main__":
    asyncio.run(main())
