import asyncio
import os
import time
from datetime import UTC, datetime
from typing import Optional

from loguru import logger

from api.db import db_client
from api.db.models import QueuedRunModel, WorkflowRunModel
from api.enums import OrganizationConfigurationKey, WorkflowRunState
from api.services.campaign.rate_limiter import rate_limiter
from api.services.compliance.pre_call_gate import pre_call_gate
from api.services.telephony.base import TelephonyProvider
from api.services.telephony.factory import get_telephony_provider
from api.utils.tunnel import TunnelURLProvider

CAMPAIGN_BATCH_SIZE = int(os.getenv("CAMPAIGN_BATCH_SIZE", "100"))
DEFAULT_CONCURRENT_CALL_LIMIT = int(os.getenv("DEFAULT_CONCURRENT_CALL_LIMIT", "100"))
MAX_PARALLEL_DISPATCH = 10


class CampaignCallDispatcher:
    """Manages rate-limited and concurrent-limited call dispatching"""

    def __init__(self):
        self.default_concurrent_limit = DEFAULT_CONCURRENT_CALL_LIMIT

    async def get_telephony_provider(self, organization_id: int) -> TelephonyProvider:
        """Get telephony provider instance for specific organization"""
        return await get_telephony_provider(organization_id)

    async def get_org_concurrent_limit(self, organization_id: int) -> int:
        """Get the concurrent call limit for an organization."""
        try:
            config = await db_client.get_configuration(
                organization_id,
                OrganizationConfigurationKey.CONCURRENT_CALL_LIMIT.value,
            )
            if config and config.value:
                return int(config.value["value"])
        except Exception as e:
            logger.warning(
                f"Error getting concurrent limit for org {organization_id}: {e}"
            )
        return self.default_concurrent_limit

    async def process_batch(self, campaign_id: int, batch_size: int = CAMPAIGN_BATCH_SIZE) -> int:
        """
        Processes a batch of queued runs with priority for scheduled retries.
        Dispatches calls in parallel (bounded by MAX_PARALLEL_DISPATCH) for throughput.
        Respects the campaign's calling window configuration.
        Returns: number of processed runs
        """
        from api.services.campaign.calling_window import is_within_calling_window

        campaign = await db_client.get_campaign_by_id(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        if campaign.state != "running":
            logger.info(
                f"Campaign {campaign_id} is not in running state: {campaign.state}"
            )
            return 0

        if not is_within_calling_window(
            campaign.calling_window_start,
            campaign.calling_window_end,
            campaign.calling_window_timezone,
        ):
            logger.info(
                f"Campaign {campaign_id} outside calling window "
                f"({campaign.calling_window_start}-{campaign.calling_window_end} "
                f"{campaign.calling_window_timezone}), skipping batch"
            )
            return 0

        scheduled_runs = await db_client.get_scheduled_queued_runs(
            campaign_id=campaign_id,
            scheduled_before=datetime.now(UTC),
            limit=batch_size,
        )

        remaining_slots = batch_size - len(scheduled_runs)

        regular_runs = []
        if remaining_slots > 0:
            regular_runs = await db_client.get_queued_runs(
                campaign_id=campaign_id,
                state="queued",
                scheduled_for=False,
                limit=remaining_slots,
            )

        queued_runs = scheduled_runs + regular_runs

        if not queued_runs:
            logger.info(f"No more queued runs for campaign {campaign_id}")
            return 0

        semaphore = asyncio.Semaphore(MAX_PARALLEL_DISPATCH)
        processed_count = 0
        count_lock = asyncio.Lock()

        async def _dispatch_one(queued_run: QueuedRunModel) -> None:
            nonlocal processed_count
            async with semaphore:
                try:
                    # Pre-call compliance gate (DNC, consent, calling hours).
                    phone_number = queued_run.context_variables.get("phone_number")
                    if phone_number:
                        compliance = await pre_call_gate.check(
                            organization_id=campaign.organization_id,
                            phone=phone_number,
                            campaign=campaign,
                        )
                        if not compliance.allowed:
                            logger.info(
                                f"Compliance gate blocked queued run {queued_run.id} "
                                f"(reason={compliance.reason})"
                            )
                            await db_client.update_queued_run(
                                queued_run_id=queued_run.id,
                                state="processed",
                                retry_reason=f"compliance_blocked:{compliance.reason}"[
                                    :255
                                ],
                                processed_at=datetime.now(UTC),
                            )
                            return

                    await self.apply_rate_limit(
                        campaign.organization_id, campaign.rate_limit_per_second
                    )

                    workflow_run = await self.dispatch_call(queued_run, campaign)

                    await db_client.update_queued_run(
                        queued_run_id=queued_run.id,
                        state="processed",
                        workflow_run_id=workflow_run.id,
                        processed_at=datetime.now(UTC),
                    )

                    async with count_lock:
                        processed_count += 1

                except Exception as e:
                    logger.warning(f"Error processing queued run {queued_run.id}: {e}")
                    try:
                        await db_client.update_queued_run(
                            queued_run_id=queued_run.id,
                            state="failed",
                            processed_at=datetime.now(UTC),
                        )
                        logger.info(
                            f"Marked queued run {queued_run.id} as failed due to error: {e}"
                        )
                    except Exception as update_error:
                        logger.error(
                            f"Failed to mark queued run {queued_run.id} as failed: {update_error}"
                        )

        await asyncio.gather(*[_dispatch_one(qr) for qr in queued_runs])

        if processed_count > 0:
            await db_client.update_campaign(
                campaign_id=campaign_id,
                processed_rows=campaign.processed_rows + processed_count,
            )

        return processed_count

    async def dispatch_call(
        self, queued_run: QueuedRunModel, campaign: any
    ) -> Optional[WorkflowRunModel]:
        """Creates workflow run and initiates call with concurrent limiting"""
        # Get concurrent limit for organization
        max_concurrent = await self.get_org_concurrent_limit(campaign.organization_id)

        wait_start = time.time()
        slot_id = None
        backoff = 0.1

        while True:
            slot_id = await rate_limiter.try_acquire_concurrent_slot(
                campaign.organization_id, max_concurrent
            )
            if slot_id:
                break

            wait_time = time.time() - wait_start
            if wait_time > 600:
                logger.error(
                    f"Waiting for concurrent slot for {wait_time:.1f}s, "
                    f"org: {campaign.organization_id}, campaign: {campaign.id}"
                )

            logger.debug(
                f"Attempting to get a slot for {campaign.organization_id} {campaign.id}"
            )

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 5.0)

        # Get workflow details
        workflow = await db_client.get_workflow_by_id(campaign.workflow_id)
        if not workflow:
            # Release slot before raising
            await rate_limiter.release_concurrent_slot(
                campaign.organization_id, slot_id
            )
            raise ValueError(f"Workflow {campaign.workflow_id} not found")

        # Merge context variables (queued_run context already includes retry info if applicable)
        initial_context = {
            **workflow.template_context_variables,
            **queued_run.context_variables,
            "campaign_id": campaign.id,
        }

        # Extract phone number
        phone_number = queued_run.context_variables.get("phone_number")

        # Compliance: inject the mandatory AI disclosure into the call context
        # so the pipeline speaks it first (FCC AI ruling / PECR transparency).
        if phone_number and getattr(campaign, "ai_disclosure_enabled", True):
            from api.services.compliance.phone_utils import get_compliance_region
            from api.services.compliance.pre_call_gate import (
                DEFAULT_AI_DISCLOSURE_UK,
                DEFAULT_AI_DISCLOSURE_US,
            )

            _region = get_compliance_region(phone_number)
            _disclosure = campaign.ai_disclosure_text or (
                DEFAULT_AI_DISCLOSURE_UK
                if _region == "gb"
                else DEFAULT_AI_DISCLOSURE_US
            )
            initial_context["_ai_disclosure_enabled"] = True
            initial_context["_ai_disclosure_text"] = _disclosure

        if not phone_number:
            # Release slot before raising
            await rate_limiter.release_concurrent_slot(
                campaign.organization_id, slot_id
            )
            raise ValueError(f"No phone number in queued run {queued_run.id}")

        # Create workflow run with queued_run_id tracking
        workflow_run_name = f"WR-CAMPAIGN-{campaign.id}-{queued_run.id}"

        # Get provider first to determine the mode
        provider = await self.get_telephony_provider(campaign.organization_id)
        workflow_run_mode = provider.PROVIDER_NAME

        try:
            workflow_run = await db_client.create_workflow_run(
                name=workflow_run_name,
                workflow_id=campaign.workflow_id,
                mode=workflow_run_mode,
                user_id=campaign.created_by,
                initial_context=initial_context,
                campaign_id=campaign.id,
                queued_run_id=queued_run.id,  # Link to queued run for retry tracking
            )

            # Store slot_id mapping in Redis for cleanup later
            await rate_limiter.store_workflow_slot_mapping(
                workflow_run.id, campaign.organization_id, slot_id
            )
        except Exception as e:
            # Release slot on error
            await rate_limiter.release_concurrent_slot(
                campaign.organization_id, slot_id
            )
            raise

        # Add "retry" tag if this is a retry call
        if queued_run.context_variables.get("is_retry"):
            retry_reason = queued_run.context_variables.get("retry_reason", "unknown")
            await db_client.update_workflow_run(
                run_id=workflow_run.id,
                gathered_context={
                    "call_tags": ["retry", f"retry_reason_{retry_reason}"]
                },
            )

        # Initiate call via telephony provider
        try:
            from api.routes.telephony import (
                _prebuild_twiml_for_outbound,
            )

            # Write call direction + greeting flag BEFORE initiating.
            # The WebSocket can open as soon as Twilio connects the call,
            # and run_pipeline reads gathered_context at that moment.
            # If this write hasn't completed, the pipeline falls back to
            # "unknown" direction and incorrectly sets greeting_played=True.
            await db_client.update_workflow_run(
                run_id=workflow_run.id,
                gathered_context={
                    "provider": provider.PROVIDER_NAME,
                    "call_direction": "outbound",
                    "greeting_played_by_provider": False,
                },
            )

            backend_endpoint = await TunnelURLProvider.get_tunnel_url()
            be_host = backend_endpoint
            if be_host.startswith("https://"):
                be_host = be_host[8:]
            elif be_host.startswith("http://"):
                be_host = be_host[7:]

            webhook_endpoint = provider.WEBHOOK_ENDPOINT

            webhook_url = (
                f"https://{be_host}/api/v1/telephony/{webhook_endpoint}"
                f"?workflow_id={campaign.workflow_id}"
                f"&user_id={campaign.created_by}"
                f"&workflow_run_id={workflow_run.id}"
                f"&campaign_id={campaign.id}"
                f"&organization_id={campaign.organization_id}"
            )

            try:
                _prebuild_twiml_for_outbound(
                    be_host,
                    campaign.workflow_id,
                    campaign.created_by,
                    workflow_run.id,
                )
            except Exception as e:
                logger.warning(f"Campaign TwiML pre-build failed (non-fatal): {e}")

            call_result = await provider.initiate_call(
                to_number=phone_number,
                webhook_url=webhook_url,
                workflow_run_id=workflow_run.id,
            )

            # Merge provider metadata after the call is placed.
            if call_result.provider_metadata:
                await db_client.update_workflow_run(
                    run_id=workflow_run.id,
                    gathered_context={
                        "provider": provider.PROVIDER_NAME,
                        "call_direction": "outbound",
                        "greeting_played_by_provider": False,
                        **call_result.provider_metadata,
                    },
                )

            logger.info(
                f"Call initiated for workflow run {workflow_run.id}, "
                f"Call ID: {call_result.call_id}, greeting_played=False (stream-only)"
            )

        except Exception as e:
            logger.error(
                f"Failed to initiate call for workflow run {workflow_run.id}: {e}"
            )

            # Update workflow run as failed
            telephony_callback_logs = workflow_run.logs.get(
                "telephony_status_callbacks", []
            )
            telephony_callback_log = {
                "status": "failed",
                "timestamp": datetime.now(UTC).isoformat(),
                "data": {"error": str(e)},
            }
            telephony_callback_logs.append(telephony_callback_log)
            await db_client.update_workflow_run(
                run_id=workflow_run.id,
                is_completed=True,
                state=WorkflowRunState.COMPLETED.value,
                gathered_context={
                    "error": str(e),
                },
                logs={
                    "telephony_status_callbacks": telephony_callback_logs,
                },
            )

            # Release concurrent slot on failure
            mapping = await rate_limiter.get_workflow_slot_mapping(workflow_run.id)
            if mapping:
                org_id, slot_id = mapping
                await rate_limiter.release_concurrent_slot(org_id, slot_id)
                await rate_limiter.delete_workflow_slot_mapping(workflow_run.id)

            raise

        return workflow_run

    async def apply_rate_limit(self, organization_id: int, rate_limit: int) -> None:
        """
        Enforces rate limiting - waits if necessary to comply with rate limit

        Example usage:
        ```
        # This will wait up to 1 second if needed to respect rate limit
        await self.apply_rate_limit(org_id, 1)  # 1 call per second
        await twilio.initiate_call(...)  # Now safe to call
        ```
        """
        max_wait = 1.0  # Maximum time to wait for a slot
        start_time = time.time()

        while True:
            # Try to acquire token
            if await rate_limiter.acquire_token(organization_id, rate_limit):
                return  # Got permission to proceed

            # Check how long to wait
            wait_time = await rate_limiter.get_next_available_slot(
                organization_id, rate_limit
            )

            # Don't wait forever
            if time.time() - start_time + wait_time > max_wait:
                raise TimeoutError("Rate limit timeout - try again later")

            # Wait for next available slot
            await asyncio.sleep(wait_time)

    async def release_call_slot(self, workflow_run_id: int) -> bool:
        """
        Release concurrent slot when a call completes.
        Called by Twilio webhooks or workflow completion handlers.
        """
        mapping = await rate_limiter.get_workflow_slot_mapping(workflow_run_id)
        if mapping:
            org_id, slot_id = mapping
            success = await rate_limiter.release_concurrent_slot(org_id, slot_id)
            if success:
                await rate_limiter.delete_workflow_slot_mapping(workflow_run_id)
                logger.info(
                    f"Released concurrent slot for workflow run {workflow_run_id}"
                )
            return success
        return False


# Global instance
campaign_call_dispatcher = CampaignCallDispatcher()
