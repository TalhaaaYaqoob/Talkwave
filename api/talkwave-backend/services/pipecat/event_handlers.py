import asyncio
from loguru import logger

from api.db import db_client
from api.enums import WorkflowRunState
from api.services.campaign.call_dispatcher import campaign_call_dispatcher
from api.services.pipecat.audio_config import AudioConfig
from api.services.pipecat.audio_transcript_buffers import (
    InMemoryAudioBuffer,
    InMemoryTranscriptBuffer,
)
from api.services.pipecat.pipeline_metrics_aggregator import PipelineMetricsAggregator
from api.services.pipecat.websocket_broadcaster import websocket_broadcaster
from api.services.workflow.disposition_mapper import (
    apply_disposition_mapping,
    get_organization_id_from_workflow_run,
)
from api.services.workflow.pipecat_engine import PipecatEngine
from api.tasks.arq import enqueue_job
from api.tasks.function_names import FunctionNames
from pipecat.frames.frames import Frame
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.audio.audio_buffer_processor import AudioBuffer
from pipecat.processors.audio.audio_synchronizer import AudioSynchronizer


def register_transport_event_handlers(
    task: PipelineTask,
    transport,
    workflow_run_id,
    engine: PipecatEngine,
    audio_buffer: AudioBuffer,
    audio_synchronizer: AudioSynchronizer,
    audio_config=AudioConfig,
    connect_event: str = "on_client_connected",
    disconnect_event: str = "on_client_disconnected",
):
    """Register event handlers for transport events.

    ``connect_event`` / ``disconnect_event`` select which transport event marks
    the remote peer joining/leaving. Websocket & aiortc transports emit
    ``on_client_connected`` / ``on_client_disconnected``; LiveKit emits
    ``on_first_participant_joined`` / ``on_participant_disconnected``. Gating the
    greeting + recording start on the correct join event (rather than the
    pipeline StartFrame) prevents the first greeting audio from being clipped
    before the browser has subscribed.
    """

    # Initialize in-memory buffers with proper audio configuration
    sample_rate = audio_config.pipeline_sample_rate if audio_config else 16000
    num_channels = 1  # Pipeline audio is always mono

    logger.debug(
        f"Initializing audio buffer for workflow {workflow_run_id} "
        f"with sample_rate={sample_rate}Hz, channels={num_channels}"
    )

    in_memory_audio_buffer = InMemoryAudioBuffer(
        workflow_run_id=workflow_run_id,
        sample_rate=sample_rate,
        num_channels=num_channels,
    )
    in_memory_transcript_buffer = InMemoryTranscriptBuffer(workflow_run_id)

    @transport.event_handler(connect_event)
    async def on_client_connected(transport, participant):
        import time as _cc_time
        _cc_t0 = _cc_time.perf_counter()
        logger.info(
            f"⏱ [LATENCY] on_client_connected fired | run_id={workflow_run_id}"
        )

        asyncio.create_task(
            websocket_broadcaster.send_activity(
                workflow_run_id,
                activity_type="success",
                message="Call connected"
            )
        )

        await audio_buffer.start_recording()
        if audio_synchronizer:
            await audio_synchronizer.start_recording()

        asyncio.create_task(engine.initialize())

        logger.info(
            f"⏱ [LATENCY] on_client_connected done (engine.initialize scheduled) | "
            f"run_id={workflow_run_id} | handler_time={(_cc_time.perf_counter() - _cc_t0)*1000:.0f}ms"
        )

        asyncio.create_task(
            websocket_broadcaster.send_activity(
                workflow_run_id,
                activity_type="info",
                message="Agent is ready"
            )
        )

    @transport.event_handler(disconnect_event)
    async def on_client_disconnected(transport, participant):
        call_disposed = engine.is_call_disposed()

        logger.debug(
            f"In on_client_disconnected callback handler. Call disposed: {call_disposed}"
        )
        
        # Send activity log to WebSocket client
        asyncio.create_task(
            websocket_broadcaster.send_activity(
                workflow_run_id,
                activity_type="connection",
                message="Call ended"
            )
        )
        
        engine.handle_client_disconnected()

        # Stop recordings
        await audio_buffer.stop_recording()
        if audio_synchronizer:
            await audio_synchronizer.stop_recording()

        # Only cancel the task if the call is not already disposed by the engine
        if not call_disposed:
            await task.cancel()

    # Return the buffers so they can be passed to other handlers
    return in_memory_audio_buffer, in_memory_transcript_buffer


def register_task_event_handler(
    workflow_run_id: int,
    engine: PipecatEngine,
    task: PipelineTask,
    transport,
    audio_buffer: AudioBuffer,
    audio_synchronizer: AudioSynchronizer,
    in_memory_audio_buffer: InMemoryAudioBuffer,
    in_memory_transcript_buffer: InMemoryTranscriptBuffer,
    pipeline_metrics_aggregator: PipelineMetricsAggregator,
):
    @task.event_handler("on_pipeline_finished")
    async def on_pipeline_finished(
        task: PipelineTask,
        frame: Frame,
    ):
        logger.info(f"on_pipeline_finished triggered for run_id={workflow_run_id}")

        try:
            await _handle_pipeline_finished()
        except Exception as exc:
            logger.critical(
                f"on_pipeline_finished FAILED for run_id={workflow_run_id}: {exc}",
                exc_info=True,
            )
            try:
                await db_client.update_workflow_run(
                    run_id=workflow_run_id,
                    is_completed=True,
                    state=WorkflowRunState.COMPLETED.value,
                )
            except Exception:
                pass

    async def _handle_pipeline_finished():
        workflow_run = await db_client.get_workflow_run_by_id(workflow_run_id)

        # Stop recordings
        await audio_buffer.stop_recording()
        if audio_synchronizer:
            await audio_synchronizer.stop_recording()

        call_disposition = await engine.get_call_disposition()
        logger.debug(f"call disposition in on_pipeline_finished: {call_disposition}")

        gathered_context = await engine.get_gathered_context()

        # also consider existing gathered context in workflow_run
        gathered_context = {**gathered_context, **workflow_run.gathered_context}

        organization_id = await get_organization_id_from_workflow_run(workflow_run_id)
        mapped_call_disposition = await apply_disposition_mapping(
            call_disposition, organization_id
        )

        gathered_context.update({"mapped_call_disposition": mapped_call_disposition})

        # Set user_speech call tag
        if in_memory_transcript_buffer:
            call_tags = gathered_context.get("call_tags", [])

            try:
                has_user_speech = in_memory_transcript_buffer.contains_user_speech()
            except Exception:
                has_user_speech = False

            if has_user_speech and "user_speech" not in call_tags:
                call_tags.append("user_speech")

            # Append any keys from gathered_context that start with 'tag_' to call_tags
            for key in gathered_context:
                if key.startswith("tag_") and key not in call_tags:
                    call_tags.append(gathered_context[key])

            gathered_context["call_tags"] = call_tags

        # Clean up engine resources (including voicemail detector)
        await engine.cleanup()

        # ------------------------------------------------------------------
        # Close Smart-Turn WebSocket if the transport's analyzer supports it
        # ------------------------------------------------------------------
        try:
            turn_analyzer = None

            # Most transports store their params (with turn_analyzer) directly.
            if hasattr(transport, "_params") and transport._params:
                turn_analyzer = getattr(transport._params, "turn_analyzer", None)

            # Fallback: some transports expose params through input() instance.
            if turn_analyzer is None and hasattr(transport, "input"):
                try:
                    input_transport = transport.input()
                    if input_transport and hasattr(input_transport, "_params"):
                        turn_analyzer = getattr(
                            input_transport._params, "turn_analyzer", None
                        )
                except Exception:
                    pass

            if turn_analyzer and hasattr(turn_analyzer, "close"):
                await turn_analyzer.close()
                logger.debug("Closed turn analyzer websocket")
        except Exception as exc:
            logger.warning(f"Failed to close Smart-Turn analyzer gracefully: {exc}")

        usage_info = pipeline_metrics_aggregator.get_all_usage_metrics_serialized()

        # Enrich usage_info with identifiers so downstream analytics (PostHog,
        # cost reports, dashboards) can correctly attribute every call. Prior
        # to this, `usage_info.get("workflow_id", 0)` was always 0 — silently
        # breaking per-workflow analytics at scale.
        if workflow_run:
            if workflow_run.workflow_id:
                usage_info.setdefault("workflow_id", workflow_run.workflow_id)
            if workflow_run.mode:
                usage_info.setdefault("call_type", workflow_run.mode)
            if workflow_run.campaign_id:
                usage_info.setdefault("campaign_id", workflow_run.campaign_id)

        logger.debug(f"Usage metrics: {usage_info}")

        for _attempt in range(3):
            try:
                await db_client.update_workflow_run(
                    run_id=workflow_run_id,
                    usage_info=usage_info,
                    gathered_context=gathered_context,
                    is_completed=True,
                    state=WorkflowRunState.COMPLETED.value,
                )
                break
            except Exception as e:
                logger.error(
                    f"Attempt {_attempt + 1}/3 failed to save run data for "
                    f"run_id={workflow_run_id}: {e}",
                    exc_info=_attempt == 2,
                )
                if _attempt < 2:
                    await asyncio.sleep(0.5 * (_attempt + 1))
                else:
                    logger.critical(
                        f"All 3 attempts to save run data FAILED for "
                        f"run_id={workflow_run_id} — report data will be missing"
                    )

        # Release concurrent slot for campaign calls
        if workflow_run and workflow_run.campaign_id:
            await campaign_call_dispatcher.release_call_slot(workflow_run_id)

        # Save transcript directly to database (skip S3 upload for speed)
        try:
            if not in_memory_transcript_buffer.is_empty:
                # Get the transcript content as a list of messages
                transcript_content = in_memory_transcript_buffer.get_content()
                
                # Parse the transcript into structured messages
                transcript_messages = []
                for line in transcript_content.split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Parse lines like "[timestamp] role: content" or "role: content"
                    if ': ' in line:
                        # Check if there's a timestamp
                        if line.startswith('['):
                            try:
                                timestamp_end = line.index(']')
                                timestamp = line[1:timestamp_end]
                                rest = line[timestamp_end + 1:].strip()
                            except ValueError:
                                timestamp = None
                                rest = line
                        else:
                            timestamp = None
                            rest = line
                        
                        if ': ' in rest:
                            role, content = rest.split(': ', 1)
                            transcript_messages.append({
                                'role': role.lower(),
                                'content': content,
                                'timestamp': timestamp
                            })
                
                # Save transcript to gathered_context for fast access
                await db_client.update_workflow_run(
                    run_id=workflow_run_id,
                    gathered_context={
                        **gathered_context,
                        'transcript_messages': transcript_messages,
                        'transcript_text': transcript_content,
                    }
                )
                logger.info(f"Saved {len(transcript_messages)} transcript messages to database")
            else:
                logger.debug("Transcript buffer is empty, skipping save")

            # Skip audio upload for faster post-call processing
            # Audio recording is optional and can be re-enabled if needed
            logger.debug("Skipping audio upload for faster processing")

        except Exception as e:
            logger.error(f"Error saving transcript to database: {e}", exc_info=True)

        # Record subscription usage inline (doesn't depend on ARQ worker)
        try:
            duration_seconds = usage_info.get("call_duration_seconds", 0)
            if duration_seconds > 0 and organization_id:
                from api.services.subscription import shared_subscription_service
                await shared_subscription_service.record_usage(organization_id, duration_seconds)
                logger.info(
                    f"📊 [USAGE] Recorded {duration_seconds}s ({duration_seconds/60:.1f}min) "
                    f"for org {organization_id} | run_id={workflow_run_id}"
                )
                from api.services.analytics import posthog_service as analytics
                analytics.track_call_ended(
                    user_id=str(organization_id),
                    org_id=organization_id,
                    workflow_id=usage_info.get("workflow_id", 0),
                    run_id=workflow_run_id or 0,
                    duration_seconds=duration_seconds,
                    call_type=usage_info.get("call_type", "unknown"),
                )
            elif duration_seconds <= 0:
                logger.warning(
                    f"📊 [USAGE] Skipped — call_duration_seconds={duration_seconds} | "
                    f"run_id={workflow_run_id}"
                )
            elif not organization_id:
                logger.warning(
                    f"📊 [USAGE] Skipped — no organization_id resolved | "
                    f"run_id={workflow_run_id}"
                )
        except Exception as e:
            logger.error(f"📊 [USAGE] Failed to record subscription usage: {e} | run_id={workflow_run_id}")

        await enqueue_job(FunctionNames.CALCULATE_WORKFLOW_RUN_COST, workflow_run_id)
        await enqueue_job(
            FunctionNames.RUN_INTEGRATIONS_POST_WORKFLOW_RUN, workflow_run_id
        )

        # Self-improving agent: check if enough calls have accumulated for analysis.
        # Idempotency key: dedupes the threshold check per workflow per 60s bucket,
        # so 1000 simultaneous call-end events don't spawn 1000 duplicate checks.
        if organization_id and workflow_run and workflow_run.workflow_id:
            import time as _time
            _bucket = int(_time.time() // 60)
            await enqueue_job(
                FunctionNames.CHECK_IMPROVEMENT_THRESHOLD,
                workflow_run.workflow_id,
                organization_id,
                _job_id=f"improve_check:{workflow_run.workflow_id}:{_bucket}",
            )


def register_audio_data_handler(
    audio_synchronizer, workflow_run_id, in_memory_buffer: InMemoryAudioBuffer
):
    """Register event handler for audio data"""
    logger.info(f"Registering audio data handler for workflow run {workflow_run_id}")

    @audio_synchronizer.event_handler("on_merged_audio")
    async def on_merged_audio(_, pcm, sample_rate, num_channels):
        if not pcm:
            return

        # Use in-memory buffer
        try:
            await in_memory_buffer.append(pcm)
        except MemoryError as e:
            logger.error(f"Memory buffer full: {e}")
            # Could implement overflow to disk here if needed


def register_transcript_handler(
    transcript, workflow_run_id, in_memory_buffer: InMemoryTranscriptBuffer
):
    """Register event handler for transcript updates"""
    
    logger.info(f"Registering transcript handler for workflow run {workflow_run_id}")
    
    # Track sent messages by content hash to avoid duplicates
    # Pipecat's transcript processor doesn't accumulate - each update has current turn only
    sent_content_hashes = set()

    @transcript.event_handler("on_transcript_update")
    async def on_transcript_update(processor, frame):
        logger.debug(f"Transcript update received for run {workflow_run_id}: {len(frame.messages)} messages in frame")
        
        transcript_text = ""
        
        # Process all messages and build transcript text
        for msg in frame.messages:
            timestamp = f"[{msg.timestamp}] " if msg.timestamp else ""
            line = f"{timestamp}{msg.role}: {msg.content}\n"
            transcript_text += line

        # Use in-memory buffer for storage
        await in_memory_buffer.append(transcript_text)
        
        # Broadcast messages to WebSocket clients.
        # Track by content hash since pipecat doesn't accumulate messages across turns.
        # NOTE: Assistant transcripts are deliberately NOT broadcast here.
        # `AssistantStreamBroadcaster` already emits a final `transcript` event
        # on LLMFullResponseEndFrame / TTSSpeakFrame (i.e. before TTS plays).
        # Re-broadcasting from this post-TTS hook would either duplicate the
        # message in the UI or — if the user interrupted mid-utterance —
        # overwrite the full LLM intent with a truncated spoken string.
        # We still append to `in_memory_buffer` above so the DB transcript
        # reflects what the agent actually said.
        for msg in frame.messages:
            role = "user" if msg.role.lower() in ["user", "human"] else "assistant"
            if role == "assistant":
                continue

            content_hash = hash(f"{msg.role}:{msg.content}")

            if content_hash in sent_content_hashes:
                logger.debug(f"Skipping already-sent message: [{msg.role}] {msg.content[:30]}...")
                continue

            sent_content_hashes.add(content_hash)

            logger.info(f"Broadcasting NEW transcript: [{role}] {msg.content[:50]}...")

            asyncio.create_task(
                websocket_broadcaster.send_transcript(
                    workflow_run_id,
                    role=role,
                    content=msg.content
                )
            )
