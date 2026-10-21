import asyncio
from typing import Optional, Set

from fastapi import HTTPException, WebSocket
from loguru import logger

from api.db import db_client
from api.db.models import WorkflowModel
from api.enums import WorkflowRunMode


class ActiveCallTracker:
    """Track active pipeline tasks for graceful shutdown."""

    def __init__(self):
        self._tasks: Set[asyncio.Task] = set()
        self._lock = asyncio.Lock()

    async def register(self, task: asyncio.Task) -> None:
        async with self._lock:
            self._tasks.add(task)
            task.add_done_callback(lambda t: self._tasks.discard(t))

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    async def wait_for_all(self, timeout: float = 30.0) -> None:
        """Wait for all active calls to finish, with a timeout."""
        async with self._lock:
            tasks = list(self._tasks)
        if not tasks:
            return
        logger.info(f"Waiting for {len(tasks)} active call(s) to finish (timeout={timeout}s)...")
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        if pending:
            logger.warning(f"{len(pending)} call(s) still running after {timeout}s, cancelling...")
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)


active_call_tracker = ActiveCallTracker()

from api.services.pipecat.audio_config import AudioConfig, create_audio_config
from api.services.pipecat.event_handlers import (
    register_audio_data_handler,
    register_task_event_handler,
    register_transcript_handler,
    register_transport_event_handlers,
)
from api.services.pipecat.pipeline_builder import (
    build_pipeline,
    build_realtime_pipeline,
    create_pipeline_components,
    create_pipeline_task,
)
from api.services.pipecat.pipeline_engine_callbacks_processor import (
    PipelineEngineCallbacksProcessor,
)
from api.services.pipecat.pipeline_metrics_aggregator import PipelineMetricsAggregator
from api.services.pipecat.service_factory import (
    create_cartesia_tts_from_workflow,
    create_deepgram_stt_from_workflow,
    create_gemini_live_service,
    create_gemini_tts_from_workflow,
    create_llm_service,
    create_openai_llm_from_env,
    create_tts_from_workflow,
    create_stt_service,
    create_tts_service,
)
from api.services.pipecat.tracing_config import setup_pipeline_tracing
from api.services.pipecat.transport_setup import (
    create_livekit_transport,
    create_stasis_transport,
    create_twilio_transport,
    create_vobiz_transport,
    create_vonage_transport,
    create_webrtc_transport,
)
from api.services.telephony.stasis_rtp_connection import StasisRTPConnection
from api.services.workflow.dto import ReactFlowDTO
from api.services.workflow.pipecat_engine import PipecatEngine
from api.services.workflow.workflow import WorkflowGraph
from pipecat.pipeline.base_task import PipelineTaskParams
from pipecat.processors.aggregators.llm_response import LLMAssistantAggregatorParams
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.filters.stt_mute_filter import (
    STTMuteConfig,
    STTMuteFilter,
    STTMuteStrategy,
)
from pipecat.processors.user_idle_processor import UserIdleProcessor
from pipecat.services.deepgram.stt import DeepgramSTTService, LiveOptions
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.utils.context import set_current_run_id
from pipecat.utils.tracing.context_registry import ContextProviderRegistry

# Smart Turn Detection imports
from api.constants import ENABLE_SMART_TURN
try:
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
    from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
    from pipecat.turns.user_turn_strategies import UserTurnStrategies
    SMART_TURN_AVAILABLE = True
except ImportError:
    SMART_TURN_AVAILABLE = False

try:
    from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (
        SpeechTimeoutUserTurnStopStrategy,
    )
    SPEECH_TIMEOUT_STRATEGY_AVAILABLE = True
except ImportError:
    SPEECH_TIMEOUT_STRATEGY_AVAILABLE = False
    logger.warning("Smart Turn not available - install with: pip install 'pipecat-ai[local-smart-turn-v3]'")

# Setup tracing if enabled
setup_pipeline_tracing()



def _should_use_flux_stt(workflow) -> bool:
    """Determine if Flux STT should be used based on the workflow language.

    MUST mirror the model-selection logic in service_factory.create_stt_service:
    Flux is used for English (flux-general-en) AND for every language supported
    by flux-general-multi (es/fr/de/hi/ru/pt/ja/it/nl). Flux does native turn
    detection, so transport-level Silero VAD must be OFF for those languages —
    running both produces duplicate speech events and choppy barge-in.
    Nova-3 languages (Arabic, Chinese, ...) still need Silero VAD.

    Gemini Live / realtime mode always needs transport-level VAD because
    there is no separate STT; the pipeline relies on Silero VAD for
    UserStartedSpeaking / UserStoppedSpeaking events.
    """
    from api.services.pipecat.service_factory import (
        FLUX_MULTI_BASE_LANGUAGES,
        LANGUAGE_TO_DEEPGRAM_CODE,
    )

    if not workflow or not workflow.workflow_configurations:
        return True  # Default language is English
    if workflow.workflow_configurations.get("voice_mode") == "realtime":
        return False
    wf_lang = workflow.workflow_configurations.get("workflow_language", "English")
    lang_code = LANGUAGE_TO_DEEPGRAM_CODE.get(wf_lang)
    if lang_code is None:
        return False  # unknown language → nova-3 + Silero VAD
    base_lang = lang_code.split("-")[0]
    return base_lang in FLUX_MULTI_BASE_LANGUAGES






async def run_pipeline_twilio(
    websocket_client: WebSocket,
    stream_sid: str,
    call_sid: str,
    workflow_id: int,
    workflow_run_id: int,
    user_id: int,
    workflow=None,
    workflow_run=None,
    telephony_config: dict = None,
    user_config=None,
) -> None:
    """Run pipeline for Twilio connections"""
    import time as _time
    _rpt_t0 = _time.perf_counter()

    set_current_run_id(workflow_run_id)
    asyncio.create_task(db_client.update_workflow_run(workflow_run_id, cost_info={"call_id": call_sid}))

    if not workflow:
        workflow = await db_client.get_workflow(workflow_id, user_id)

    vad_config = None
    ambient_noise_config = None
    if workflow and workflow.workflow_configurations:
        if "vad_configuration" in workflow.workflow_configurations:
            vad_config = workflow.workflow_configurations["vad_configuration"]
        if "ambient_noise_configuration" in workflow.workflow_configurations:
            ambient_noise_config = workflow.workflow_configurations[
                "ambient_noise_configuration"
            ]

    audio_config = create_audio_config(WorkflowRunMode.TWILIO.value)
    use_flux = _should_use_flux_stt(workflow)
    voice_mode_twilio = (workflow.workflow_configurations or {}).get("voice_mode", "standard") if workflow else "standard"

    transport = await create_twilio_transport(
        websocket_client,
        stream_sid,
        call_sid,
        workflow_run_id,
        audio_config,
        workflow.organization_id,
        vad_config,
        ambient_noise_config,
        telephony_config=telephony_config,
        use_flux_stt=use_flux,
        disable_turn_analyzer=(voice_mode_twilio == "realtime"),
    )
    _rpt_t_transport = _time.perf_counter()
    logger.info(
        f"⏱ [LATENCY] Twilio transport created (flux={use_flux}) | run_id={workflow_run_id} | "
        f"elapsed={(_rpt_t_transport - _rpt_t0)*1000:.0f}ms"
    )

    # Determine if Twilio played a greeting via <Play>.
    # For outbound: check the flag stored by initiate_call.
    # For inbound: greeting is always handled by the pipeline via TTS (no <Play>).
    _call_dir = "unknown"
    greeting_played = False
    if workflow_run and hasattr(workflow_run, "gathered_context") and workflow_run.gathered_context:
        _call_dir = workflow_run.gathered_context.get("call_direction", "unknown")
        if workflow_run.gathered_context.get("greeting_played_by_provider", False):
            greeting_played = True

    logger.info(
        f"[TWILIO] greeting_played_by_provider={greeting_played}, "
        f"call_direction={_call_dir} | run_id={workflow_run_id}"
    )

    await _run_pipeline(
        transport,
        workflow_id,
        workflow_run_id,
        user_id,
        audio_config=audio_config,
        workflow=workflow,
        workflow_run=workflow_run,
        user_config=user_config,
        greeting_played_by_provider=greeting_played,
    )


async def run_pipeline_vonage(
    websocket_client,
    call_uuid: str,
    workflow: WorkflowModel,
    organization_id: int,
    workflow_id: int,
    workflow_run_id: int,
    user_id: int,
    user_config=None,
):
    """Run pipeline for Vonage WebSocket connections.

    Vonage uses raw PCM audio over WebSocket instead of base64-encoded μ-law.
    The audio is transmitted as binary frames at 16kHz by default.
    """
    logger.info(f"Starting Vonage pipeline for workflow run {workflow_run_id}")
    set_current_run_id(workflow_run_id)

    # Store call ID in cost_info (fire-and-forget style, non-blocking)
    cost_info = {"call_id": call_uuid}
    asyncio.create_task(db_client.update_workflow_run(workflow_run_id, cost_info=cost_info))

    # Extract VAD and ambient noise config from workflow
    vad_config = None
    ambient_noise_config = None
    if workflow and workflow.workflow_configurations:
        if "vad_configuration" in workflow.workflow_configurations:
            vad_config = workflow.workflow_configurations["vad_configuration"]
        if "ambient_noise_configuration" in workflow.workflow_configurations:
            ambient_noise_config = workflow.workflow_configurations[
                "ambient_noise_configuration"
            ]

    try:
        # Setup audio config for Vonage using the centralized config
        audio_config = create_audio_config(WorkflowRunMode.VONAGE.value)
        use_flux = _should_use_flux_stt(workflow)

        # Create Vonage transport
        transport = await create_vonage_transport(
            websocket_client,
            call_uuid,
            workflow_run_id,
            audio_config,
            organization_id,
            vad_config,
            ambient_noise_config,
            use_flux_stt=use_flux,
        )

        # Run the pipeline (same as Twilio/WebRTC) — pass workflow to skip re-fetch
        await _run_pipeline(
            transport,
            workflow_id,
            workflow_run_id,
            user_id,
            call_context_vars={},
            audio_config=audio_config,
            workflow=workflow,
            user_config=user_config,
        )

    except Exception as e:
        logger.error(f"Error in Vonage pipeline: {e}")
        raise


async def run_pipeline_vobiz(
    websocket_client: WebSocket,
    stream_id: str,
    call_id: str,
    workflow_id: int,
    workflow_run_id: int,
    user_id: int,
    workflow=None,
    workflow_run=None,
    user_config=None,
) -> None:
    """Run pipeline for Vobiz using Plivo-compatible WebSocket protocol."""
    logger.info(
        f"[run {workflow_run_id}] Starting Vobiz pipeline - "
        f"stream_id={stream_id}, call_id={call_id}, workflow_id={workflow_id}"
    )
    set_current_run_id(workflow_run_id)

    # OPTIMIZATION: Store call ID in background, use pre-fetched workflow if available
    cost_info = {"call_id": call_id}
    asyncio.create_task(db_client.update_workflow_run(workflow_run_id, cost_info=cost_info))

    if not workflow:
        workflow = await db_client.get_workflow(workflow_id, user_id)

    vad_config = None
    ambient_noise_config = None
    if workflow and workflow.workflow_configurations:
        if "vad_configuration" in workflow.workflow_configurations:
            vad_config = workflow.workflow_configurations["vad_configuration"]
        if "ambient_noise_configuration" in workflow.workflow_configurations:
            ambient_noise_config = workflow.workflow_configurations[
                "ambient_noise_configuration"
            ]

    try:
        audio_config = create_audio_config(WorkflowRunMode.VOBIZ.value)
        use_flux = _should_use_flux_stt(workflow)
        logger.info(
            f"[run {workflow_run_id}] Vobiz audio config: "
            f"sample_rate={audio_config.transport_in_sample_rate}Hz, format=MULAW, flux={use_flux}"
        )

        transport = await create_vobiz_transport(
            websocket_client,
            stream_id,
            call_id,
            workflow_run_id,
            audio_config,
            workflow.organization_id,
            vad_config,
            ambient_noise_config,
            use_flux_stt=use_flux,
        )

        logger.info(f"[run {workflow_run_id}] Starting Vobiz pipeline execution")
        await _run_pipeline(
            transport,
            workflow_id,
            workflow_run_id,
            user_id,
            audio_config=audio_config,
            workflow=workflow,
            workflow_run=workflow_run,
            user_config=user_config,
        )
        logger.info(f"[run {workflow_run_id}] Vobiz pipeline completed successfully")

    except Exception as e:
        logger.error(
            f"[run {workflow_run_id}] Error in Vobiz pipeline: {e}", exc_info=True
        )
        raise


async def run_pipeline_smallwebrtc(
    webrtc_connection: SmallWebRTCConnection,
    workflow_id: int,
    workflow_run_id: int,
    user_id: int,
    call_context_vars: dict = {},
    workflow=None,
    workflow_run=None,
    user_config=None,
) -> None:
    """Run pipeline for WebRTC connections"""
    logger.debug(
        f"Running pipeline for WebRTC connection with workflow_id: {workflow_id} and workflow_run_id: {workflow_run_id}"
    )
    set_current_run_id(workflow_run_id)

    # Use pre-fetched workflow if available, otherwise fetch
    if not workflow:
        workflow = await db_client.get_workflow(workflow_id, user_id)
    vad_config = None
    ambient_noise_config = None
    if workflow and workflow.workflow_configurations:
        if "vad_configuration" in workflow.workflow_configurations:
            vad_config = workflow.workflow_configurations["vad_configuration"]
        if "ambient_noise_configuration" in workflow.workflow_configurations:
            ambient_noise_config = workflow.workflow_configurations[
                "ambient_noise_configuration"
            ]

    # Create audio configuration for WebRTC
    audio_config = create_audio_config(WorkflowRunMode.SMALLWEBRTC.value)
    use_flux = _should_use_flux_stt(workflow)
    voice_mode = (workflow.workflow_configurations or {}).get("voice_mode", "standard") if workflow else "standard"

    transport = create_webrtc_transport(
        webrtc_connection,
        workflow_run_id,
        audio_config,
        vad_config,
        ambient_noise_config,
        use_flux_stt=use_flux,
        disable_turn_analyzer=(voice_mode == "realtime"),
    )
    await _run_pipeline(
        transport,
        workflow_id,
        workflow_run_id,
        user_id,
        call_context_vars=call_context_vars,
        audio_config=audio_config,
        workflow=workflow,
        workflow_run=workflow_run,
        user_config=user_config,
    )


async def run_pipeline_livekit(
    livekit_url: str,
    livekit_token: str,
    room_name: str,
    workflow_id: int,
    workflow_run_id: int,
    user_id: int,
    call_context_vars: dict = {},
    workflow=None,
    workflow_run=None,
    user_config=None,
) -> None:
    """Run pipeline using LiveKit Cloud transport instead of aiortc.

    The agent joins a LiveKit room as a participant. The browser user joins
    the same room via the LiveKit JS SDK. Media flows through LiveKit's SFU,
    eliminating the aiortc bottleneck and enabling 1000+ concurrent calls.
    """
    logger.info(
        f"[LiveKit] Starting pipeline for room={room_name}, "
        f"workflow_id={workflow_id}, run_id={workflow_run_id}"
    )
    set_current_run_id(workflow_run_id)

    if not workflow:
        workflow = await db_client.get_workflow(workflow_id, user_id)

    vad_config = None
    ambient_noise_config = None
    if workflow and workflow.workflow_configurations:
        if "vad_configuration" in workflow.workflow_configurations:
            vad_config = workflow.workflow_configurations["vad_configuration"]
        if "ambient_noise_configuration" in workflow.workflow_configurations:
            ambient_noise_config = workflow.workflow_configurations[
                "ambient_noise_configuration"
            ]

    audio_config = create_audio_config(WorkflowRunMode.SMALLWEBRTC.value)
    use_flux = _should_use_flux_stt(workflow)
    voice_mode = (workflow.workflow_configurations or {}).get("voice_mode", "standard") if workflow else "standard"

    transport = create_livekit_transport(
        livekit_url=livekit_url,
        livekit_token=livekit_token,
        room_name=room_name,
        workflow_run_id=workflow_run_id,
        audio_config=audio_config,
        vad_config=vad_config,
        ambient_noise_config=ambient_noise_config,
        use_flux_stt=use_flux,
        disable_turn_analyzer=(voice_mode == "realtime"),
    )

    await _run_pipeline(
        transport,
        workflow_id,
        workflow_run_id,
        user_id,
        call_context_vars=call_context_vars,
        audio_config=audio_config,
        workflow=workflow,
        workflow_run=workflow_run,
        user_config=user_config,
        # LiveKit: greet only once the browser participant has joined the room,
        # so the first utterance isn't clipped by the still-connecting transport.
        greeting_on_participant_join=True,
    )


async def run_pipeline_ari_stasis(
    stasis_connection: StasisRTPConnection,
    workflow_id: int,
    workflow_run_id: int,
    user_id: int,
    call_context_vars: dict,
) -> None:
    """Run pipeline for ARI connections"""
    logger.debug(
        f"Running pipeline for ARI connection with workflow_id: {workflow_id} and workflow_run_id: {workflow_run_id}"
    )
    set_current_run_id(workflow_run_id)

    # Get workflow to extract all pipeline configurations
    workflow = await db_client.get_workflow(workflow_id, user_id)
    vad_config = None
    ambient_noise_config = None
    if workflow and workflow.workflow_configurations:
        if "vad_configuration" in workflow.workflow_configurations:
            vad_config = workflow.workflow_configurations["vad_configuration"]
        if "ambient_noise_configuration" in workflow.workflow_configurations:
            ambient_noise_config = workflow.workflow_configurations[
                "ambient_noise_configuration"
            ]

    # Create audio configuration for Stasis
    audio_config = create_audio_config(WorkflowRunMode.STASIS.value)
    use_flux = _should_use_flux_stt(workflow)

    transport = create_stasis_transport(
        stasis_connection,
        workflow_run_id,
        audio_config,
        vad_config,
        ambient_noise_config,
        use_flux_stt=use_flux,
    )
    await _run_pipeline(
        transport,
        workflow_id,
        workflow_run_id,
        user_id,
        call_context_vars=call_context_vars,
        audio_config=audio_config,
        stasis_connection=stasis_connection,  # Pass connection for immediate transfers
        workflow=workflow,
    )


async def _run_pipeline(
    transport,
    workflow_id: int,
    workflow_run_id: int,
    user_id: int,
    call_context_vars: dict = {},
    audio_config: AudioConfig = None,
    stasis_connection: Optional[StasisRTPConnection] = None,
    workflow=None,
    workflow_run=None,
    user_config=None,
    greeting_played_by_provider: bool = False,
    greeting_on_participant_join: bool = False,
) -> None:
    """Run the pipeline with the given transport and configuration.

    ``greeting_on_participant_join``: when True, the engine greeting is triggered
    by the transport's participant-join event instead of the pipeline
    ``StartFrame``. This is required for LiveKit, where the pipeline starts as
    soon as the agent joins the room — before the browser has subscribed to the
    agent's audio track — so firing the greeting on ``StartFrame`` clips the
    start of the first utterance ("the first voice is breaking").
    """
    import time as _time
    _pipe_t0 = _time.perf_counter()

    # OPTIMIZATION: Only fetch what we don't already have, run all in parallel
    _fetch_coros = []
    _fetch_keys = []

    if not workflow_run:
        _fetch_coros.append(db_client.get_workflow_run(workflow_run_id, user_id))
        _fetch_keys.append('workflow_run')

    if not user_config:
        _fetch_coros.append(db_client.get_user_configurations(user_id))
        _fetch_keys.append('user_config')

    if not workflow:
        _fetch_coros.append(db_client.get_workflow(workflow_id, user_id))
        _fetch_keys.append('workflow')

    # Only fetch subscription when needed for Gemini S2S gating (realtime mode).
    # For standard mode this was adding ~4s of unnecessary DB latency.
    _org_id_for_sub = None
    if workflow and hasattr(workflow, 'organization_id'):
        _org_id_for_sub = workflow.organization_id
    _early_voice_mode = "standard"
    if workflow and workflow.workflow_configurations:
        _early_voice_mode = workflow.workflow_configurations.get("voice_mode", "standard")
    if _early_voice_mode == "realtime" and _org_id_for_sub:
        from api.services.subscription import shared_subscription_service
        _fetch_coros.append(shared_subscription_service.get_or_create_subscription(_org_id_for_sub))
        _fetch_keys.append('subscription')

    if _fetch_coros:
        _results = await asyncio.gather(*_fetch_coros)
        _result_map = dict(zip(_fetch_keys, _results))

        if 'workflow_run' in _result_map:
            workflow_run = _result_map['workflow_run']
        if 'user_config' in _result_map:
            user_config = _result_map['user_config']
    else:
        _result_map = {}

    # user_config must always be set by this point
    if not user_config:
        user_config = await db_client.get_user_configurations(user_id)
    if 'workflow' in _result_map:
        workflow = _result_map['workflow']

    # If the workflow run is already completed, we don't need to run it again
    if workflow_run.is_completed:
        raise HTTPException(status_code=400, detail="Workflow run already completed")

    merged_call_context_vars = workflow_run.initial_context
    if call_context_vars:
        merged_call_context_vars = {**merged_call_context_vars, **call_context_vars}
        asyncio.create_task(db_client.update_workflow_run(
            workflow_run_id, initial_context=merged_call_context_vars
        ))

    # ------------------------------------------------------------------
    # Caller Memory: inject a compact summary of recent calls from this
    # number as a template variable so prompts can reference it via
    # `{{caller_history}}`. Enabled per-workflow via
    # `workflow_configurations.caller_memory_enabled`. Zero LLM cost,
    # bounded output size, silent failure.
    # ------------------------------------------------------------------
    try:
        _wf_configs = (workflow.workflow_configurations or {}) if workflow else {}
        if _wf_configs.get("caller_memory_enabled"):
            from api.services.workflow.caller_memory import (
                build_caller_history_context,
            )

            _phone = (
                (merged_call_context_vars or {}).get("phone_number")
                or (merged_call_context_vars or {}).get("phone")
                or ((workflow_run.gathered_context or {}).get("caller_number"))
            )
            _org_id = getattr(workflow, "organization_id", None)
            _history = await build_caller_history_context(
                db_client=db_client,
                phone_number=_phone,
                workflow_id=workflow_id,
                organization_id=_org_id,
                current_run_id=workflow_run_id,
            )
            _base = merged_call_context_vars or {}
            if _history:
                merged_call_context_vars = {
                    **_base,
                    "caller_history": _history,
                    "caller_has_history": True,
                }
            else:
                merged_call_context_vars = {
                    **_base,
                    "caller_history": "",
                    "caller_has_history": False,
                }
    except Exception as _mem_err:
        logger.warning(f"[CallerMemory] Skipped (non-fatal): {_mem_err}")

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    _pipe_t_prefetch = _time.perf_counter()
    logger.info(
        f"⏱ [LATENCY] _run_pipeline prefetch done | run_id={workflow_run_id} | "
        f"elapsed={(_pipe_t_prefetch - _pipe_t0)*1000:.0f}ms | "
        f"had_user_config={'user_config' not in _fetch_keys}"
    )

    # ── Subscription gate for realtime (Gemini S2S) ──
    _subscription = _result_map.get('subscription')
    if _early_voice_mode == "realtime":
        if not _subscription and not _org_id_for_sub:
            _org_id_for_sub = getattr(workflow, 'organization_id', None)
        if not _subscription and _org_id_for_sub:
            from api.services.subscription import shared_subscription_service
            _subscription = await shared_subscription_service.get_or_create_subscription(_org_id_for_sub)

    _sub_plan = _subscription.plan if _subscription else "skipped"
    _gemini_s2s_allowed = _subscription.gemini_s2s_enabled if _subscription else False
    logger.info(
        f"🔑 [SUBSCRIPTION] org_id={_org_id_for_sub} | plan={_sub_plan} | "
        f"gemini_s2s_enabled={_gemini_s2s_allowed} | "
        f"run_id={workflow_run_id}"
    )

    # Check voice mode from workflow configurations
    voice_mode = "standard"  # Default to standard mode
    gemini_voice = "Charon"  # Default Gemini voice
    workflow_language = "English"  # Default language
    tts_voice_id = "Kore"  # Default Gemini TTS voice
    tts_accent = None  # Accent ID; None resolves to the language's default accent
    workflow_timezone = "UTC"  # Default timezone
    
    if workflow.workflow_configurations:
        voice_mode = workflow.workflow_configurations.get("voice_mode", "standard")
        gemini_voice = workflow.workflow_configurations.get("gemini_voice", "Charon")
        workflow_language = workflow.workflow_configurations.get("workflow_language", "English")
        tts_voice_id = workflow.workflow_configurations.get("tts_voice_id") or tts_voice_id
        tts_accent = workflow.workflow_configurations.get("tts_accent") or None
        workflow_timezone = workflow.workflow_configurations.get("timezone", "UTC") or "UTC"

    if voice_mode == "realtime" and not _gemini_s2s_allowed:
        logger.warning(
            f"⛔ [SUBSCRIPTION] Gemini S2S requested but NOT allowed on plan '{_sub_plan}' — "
            f"falling back to standard mode | org_id={_org_id_for_sub} | run_id={workflow_run_id}"
        )
        voice_mode = "standard"
    
    logger.info(f"Voice mode for workflow {workflow_id}: {voice_mode}, language: {workflow_language}")

    initial_greeting = None
    global_prompt = None
    use_case = workflow.name if workflow.name else ""  # Use workflow name as use case hint
    
    if workflow.workflow_definition_with_fallback:
        workflow_def = workflow.workflow_definition_with_fallback
        nodes = workflow_def.get("nodes", [])
        
        # Find global node for system context
        for node in nodes:
            if node.get("type") == "globalNode":
                global_prompt = node.get("data", {}).get("prompt", "")
                break
        
        # Find start node for initial greeting
        for node in nodes:
            node_data = node.get("data", {})
            if node_data.get("is_start") or node.get("type") == "startCall":
                initial_greeting = node_data.get("prompt", "")
                if voice_mode == "realtime":
                    logger.info(f"Found initial greeting for realtime mode: {initial_greeting[:100]}...")
                break

    # Create services based on voice mode and user configuration
    if voice_mode == "realtime":
        llm = create_gemini_live_service(
            user_config,
            voice_id=gemini_voice,
            workflow_language=workflow_language,
        )
        import os as _os
        from api.services.pipecat.service_factory import LANGUAGE_TO_DEEPGRAM_CODE
        _dg_key = _os.getenv("DEEPGRAM_API_KEY")
        if _dg_key:
            _lang_code = LANGUAGE_TO_DEEPGRAM_CODE.get(workflow_language, "multi")
            _stt_sr = audio_config.pipeline_sample_rate if audio_config else 16000
            stt = DeepgramSTTService(
                api_key=_dg_key,
                live_options=LiveOptions(
                    model="nova-3",
                    language=_lang_code,
                    encoding="linear16",
                    sample_rate=_stt_sr,
                    channels=1,
                    interim_results=True,
                    smart_format=True,
                    punctuate=True,
                ),
                audio_passthrough=True,
            )
            logger.info(
                f"Deepgram Nova-3 STT created for realtime transcription "
                f"(language={_lang_code}, sample_rate={_stt_sr})"
            )
        else:
            stt = None
            logger.warning("DEEPGRAM_API_KEY not set - user transcription disabled for realtime mode")
        tts = None
        logger.info(f"Using Gemini Live API for realtime voice processing with voice: {gemini_voice}, language: {workflow_language}")
    else:
        logger.info(f"[PIPELINE] Workflow ID: {workflow_id}, Language: {workflow_language}, TTS Voice: {tts_voice_id}")

        if tts_voice_id:
            # TTS router: Gemini for every language (it renders the selected
            # regional accent), with Cartesia Sonic-3.5 as the fallback.
            tts = create_tts_from_workflow(
                voice_id=tts_voice_id,
                workflow_language=workflow_language,
                accent_id=tts_accent,
                user_config=user_config,
                audio_config=audio_config,
            )
            stt = create_deepgram_stt_from_workflow(
                workflow_language=workflow_language,
                workflow_name=use_case,
                use_case=use_case,
                global_prompt=global_prompt or "",
                audio_config=audio_config,
            )
            llm = create_openai_llm_from_env(user_config)
            logger.info(
                f"[PIPELINE] ✓ Using workflow config - "
                f"Language: {workflow_language}, TTS voice: {tts_voice_id}, "
                f"TTS accent: {tts_accent or 'language default'}, "
                f"STT: Intelligent Deepgram (use-case optimized), "
                f"STT sample_rate: {audio_config.pipeline_sample_rate if audio_config else 16000}"
            )
        else:
            import os
            deepgram_key = os.getenv("DEEPGRAM_API_KEY")
            cartesia_key = os.getenv("CARTESIA_API_KEY")

            if deepgram_key:
                logger.info("[PIPELINE] Using DEEPGRAM_API_KEY from environment for STT")
                stt = create_deepgram_stt_from_workflow(
                    workflow_language=workflow_language,
                    workflow_name=use_case,
                    use_case=use_case,
                    global_prompt=global_prompt or "",
                    audio_config=audio_config,
                )
            else:
                logger.info("[PIPELINE] No env DEEPGRAM_API_KEY - falling back to user service configuration for STT")
                stt = create_stt_service(
                    user_config,
                    workflow_language=workflow_language,
                    workflow_name=use_case,
                    use_case=use_case,
                    global_prompt=global_prompt or "",
                    audio_config=audio_config,
                )

            tts = None
            try:
                tts = create_tts_service(
                    user_config,
                    audio_config,
                    workflow_language=workflow_language,
                    accent_id=tts_accent,
                )
                logger.info(f"[PIPELINE] ✓ TTS from user service config: {user_config.tts.provider if user_config.tts else 'unknown'}")
            except Exception as tts_err:
                logger.warning(f"[PIPELINE] TTS from user config failed: {tts_err}")

            # TTS fallback order:
            #   1. Gemini TTS for every language (renders the selected accent).
            #   2. Cartesia Sonic-3.5 when Gemini credentials are missing.
            #   3. Deepgram Aura-2 as the last resort.
            if tts is None:
                try:
                    tts = create_gemini_tts_from_workflow(
                        voice_id=tts_voice_id,
                        accent_id=tts_accent,
                        workflow_language=workflow_language,
                        user_config=user_config,
                        audio_config=audio_config,
                    )
                    logger.info("[PIPELINE] Using Gemini TTS from Google Cloud credentials in environment")
                except Exception as gemini_err:
                    logger.warning(f"[PIPELINE] Gemini TTS unavailable: {gemini_err}")

            if tts is None and cartesia_key:
                logger.info("[PIPELINE] Falling back to Cartesia Sonic-3.5 TTS from CARTESIA_API_KEY environment")
                tts = create_cartesia_tts_from_workflow(
                    workflow_language=workflow_language,
                    user_config=user_config,
                    audio_config=audio_config,
                )

            if tts is None and deepgram_key:
                from api.pipecat.src.pipecat.services.deepgram.tts import DeepgramTTSService
                logger.warning("[PIPELINE] Falling back to Deepgram TTS (last resort)")
                tts_sample_rate = audio_config.pipeline_sample_rate if audio_config else 16000
                tts = DeepgramTTSService(
                    api_key=deepgram_key,
                    voice="aura-asteria-en",
                    sample_rate=tts_sample_rate,
                )

            if tts is None:
                raise HTTPException(
                    status_code=400,
                    detail="No TTS service available. Configure TTS in Settings or set Google Cloud TTS credentials (preferred), CARTESIA_API_KEY, or DEEPGRAM_API_KEY."
                )

            llm = create_llm_service(user_config) if user_config.llm else create_openai_llm_from_env(user_config)
            logger.info(f"[PIPELINE] ✓ Services configured with language: {workflow_language}")

    _pipe_t_services = _time.perf_counter()
    logger.info(
        f"⏱ [LATENCY] Services created | run_id={workflow_run_id} | "
        f"elapsed={(_pipe_t_services - _pipe_t0)*1000:.0f}ms | "
        f"services_time={(_pipe_t_services - _pipe_t_prefetch)*1000:.0f}ms | "
        f"stt={type(stt).__name__ if stt else 'None'}, "
        f"tts={type(tts).__name__ if tts else 'None'}, "
        f"llm={type(llm).__name__ if llm else 'None'}"
    )

    # Extract configurations from workflow configurations
    max_call_duration_seconds = 600  # Default 10 minutes — was 5 (too short for real conversations)
    # Real callers routinely pause 8–12 seconds to think, look up info, or
    # confer with someone else. A 7s timeout fires constantly mid-conversation
    # and makes the call feel like it's "stuck" every few turns. 18s gives
    # users room to think while still catching genuinely abandoned calls.
    max_user_idle_timeout = 18.0

    if workflow.workflow_configurations:
        if "max_call_duration" in workflow.workflow_configurations:
            max_call_duration_seconds = workflow.workflow_configurations["max_call_duration"]
        if "max_user_idle_timeout" in workflow.workflow_configurations:
            max_user_idle_timeout = workflow.workflow_configurations["max_user_idle_timeout"]
    
    # Apply performance tuning from workflow configurations
    perf = (workflow.workflow_configurations or {}).get("performance", {})
    if perf:
        # Apply LLM performance params
        llm_temp = perf.get("llm_temperature", 0.1)
        llm_max_tokens = perf.get("max_response_tokens", 300)
        llm_freq_penalty = perf.get("frequency_penalty", 0.3)
        
        if hasattr(llm, '_settings') and hasattr(llm._settings, 'params'):
            llm._settings.params.temperature = llm_temp
            llm._settings.params.max_tokens = llm_max_tokens
            llm._settings.params.frequency_penalty = llm_freq_penalty
        elif hasattr(llm, '_params'):
            llm._params.temperature = llm_temp
            llm._params.max_tokens = llm_max_tokens
            llm._params.frequency_penalty = llm_freq_penalty
        
        logger.info(f"[PIPELINE] ⚡ Performance: temp={llm_temp}, max_tokens={llm_max_tokens}, freq_penalty={llm_freq_penalty}")

    workflow_graph = WorkflowGraph(
        ReactFlowDTO.model_validate(workflow.workflow_definition_with_fallback)
    )

    # Determine call direction from the workflow run's gathered context.
    _call_direction = "unknown"
    if workflow_run and hasattr(workflow_run, "gathered_context") and workflow_run.gathered_context:
        _call_direction = workflow_run.gathered_context.get("call_direction", "unknown")

    _wf_call_type = (workflow.workflow_configurations or {}).get("call_type", "") if workflow else ""
    _is_meeting = _wf_call_type.upper() == "MEETING"

    engine = PipecatEngine(
        llm=llm,
        tts=tts,
        workflow=workflow_graph,
        call_context_vars=merged_call_context_vars,
        workflow_run_id=workflow_run_id,
        llm_api_key=user_config.llm.api_key if user_config.llm else None,
        workflow_language=workflow_language,
        workflow_timezone=workflow_timezone,
        greeting_played_by_provider=greeting_played_by_provider,
        is_outbound=(_call_direction == "outbound"),
        is_inbound=(_call_direction == "inbound"),
        is_meeting=_is_meeting,
    )

    # Create pipeline components with audio configuration and engine
    audio_buffer, audio_synchronizer, transcript, context = create_pipeline_components(
        audio_config, engine
    )

    # Set the context and audio_buffer after creation
    engine.set_context(context)
    engine.set_audio_buffer(audio_buffer)

    # Set Stasis connection for immediate transfers (if available)
    if stasis_connection:
        engine.set_stasis_connection(stasis_connection)

    assistant_params = LLMAssistantAggregatorParams(
        expect_stripped_words=True,
        correct_aggregation_callback=engine.create_aggregation_correction_callback(),
    )
    
    # Configure turn detection: Smart Turn > Speech Timeout fallback > default
    user_params = None
    if ENABLE_SMART_TURN and SMART_TURN_AVAILABLE:
        logger.info("🎯 [SMART TURN] Enabling Smart Turn Detection (ML-based)")
        user_params = LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                stop=[TurnAnalyzerUserTurnStopStrategy(
                    turn_analyzer=LocalSmartTurnAnalyzerV3()
                )]
            ),
        )
    elif SPEECH_TIMEOUT_STRATEGY_AVAILABLE:
        logger.info("🎯 [TURN] Using SpeechTimeout strategy (0.7s after speech stops)")
        user_params = LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                stop=[SpeechTimeoutUserTurnStopStrategy(
                    user_speech_timeout=0.7,
                )]
            ),
        )
    else:
        logger.info("🎯 [TURN] Using default aggregator with aggregation timeout (0.5s)")
        user_params = LLMUserAggregatorParams(
            aggregation_timeout=0.5,
        )
    
    context_aggregator = LLMContextAggregatorPair(
        context, 
        assistant_params=assistant_params,
        user_params=user_params,
    )

    # Create usage metrics aggregator with engine's callback
    # OPTIMIZATION: Added pipeline_ready_callback to trigger engine initialization early
    # This reduces the delay between call connection and agent first speaking.
    #
    # For LiveKit (greeting_on_participant_join=True) we must NOT initialize on
    # the StartFrame: the pipeline starts before the browser has subscribed to
    # the agent's audio track, so the greeting's first audio would be clipped.
    # In that case the greeting is triggered from the participant-join transport
    # event instead (see register_transport_event_handlers).
    pipeline_engine_callback_processor = PipelineEngineCallbacksProcessor(
        max_call_duration_seconds=max_call_duration_seconds,
        max_duration_end_task_callback=engine.create_max_duration_callback(),
        generation_started_callback=engine.create_generation_started_callback(),
        llm_text_frame_callback=engine.handle_llm_text_frame,
        pipeline_ready_callback=(
            None if greeting_on_participant_join else engine.initialize
        ),
        user_started_speaking_callback=engine.handle_user_started_speaking,
        # Note: speaking event callbacks are now handled by pre-aggregator processor
    )

    pipeline_metrics_aggregator = PipelineMetricsAggregator()

    # Use engine's user idle callback with configured timeout
    user_idle_disconnect = UserIdleProcessor(
        callback=engine.create_user_idle_callback(), timeout=max_user_idle_timeout
    )

    user_context_aggregator = context_aggregator.user()
    assistant_context_aggregator = context_aggregator.assistant()

    # Build the appropriate pipeline based on voice mode
    if voice_mode == "realtime":
        # Realtime mode: Gemini Live handles audio natively
        # Deepgram STT runs in pipeline for user transcription display only
        pipeline = build_realtime_pipeline(
            transport,
            llm,  # GeminiLiveLLMService
            stt,  # Deepgram STT for transcription
            audio_buffer,
            audio_synchronizer,
            transcript,
            user_context_aggregator,
            assistant_context_aggregator,
            pipeline_engine_callback_processor,
            pipeline_metrics_aggregator,
            user_idle_disconnect,
        )
    else:
        # Standard mode: use separate STT → LLM → TTS pipeline
        # Create STT mute filter using the selected strategies and the engine's callback
        # LATENCY FIX: Removed MUTE_UNTIL_FIRST_BOT_COMPLETE — it blocks user
        # input until the bot finishes its entire greeting, adding perceived lag.
        # CUSTOM strategy alone lets users interrupt the greeting immediately.
        stt_mute_filter = STTMuteFilter(
            config=STTMuteConfig(
                strategies={
                    STTMuteStrategy.CUSTOM,
                },
                should_mute_callback=engine.create_should_mute_callback(),
            )
        )
        
        from api.services.pipecat.streaming_transcript import (
            AssistantStreamBroadcaster,
            UserInterimBroadcaster,
        )
        user_interim_broadcaster = UserInterimBroadcaster(workflow_run_id=workflow_run_id)
        assistant_stream_broadcaster = AssistantStreamBroadcaster(workflow_run_id=workflow_run_id)

        from api.services.pipecat.guardrails import (
            InputGuardrailProcessor,
            OutputGuardrailProcessor,
            SilenceTracker,
        )

        wf_config = workflow.workflow_configurations or {}
        guardrails_enabled = wf_config.get("guardrails_enabled", True)
        redact_pii = wf_config.get("redact_pii", True)

        input_guardrail = None
        output_guardrail = None
        if guardrails_enabled:
            input_guardrail = InputGuardrailProcessor(
                on_blocked=engine.create_guardrail_blocked_callback(),
                redact_pii=redact_pii,
            )
            output_guardrail = OutputGuardrailProcessor()
            logger.info("[GUARDRAILS] Input + output guardrails enabled")
        else:
            logger.info("[GUARDRAILS] Guardrails disabled by workflow config")

        max_silence = wf_config.get("max_cumulative_silence", 45.0)
        silence_tracker = SilenceTracker(
            max_silence_seconds=max_silence,
            end_call_callback=engine.create_silence_end_callback(),
        )

        # ── Persistent cross-call memory (opt-in per workflow) ──
        # Recalls relevant memories from this caller's past calls before the LLM
        # and retains new exchanges after each turn. Backend: self-hosted Mem0
        # (Qdrant vector store + OpenAI embedder/extraction). Scoped per
        # (organization, caller phone number). Fails open: any misconfiguration
        # returns None and the call proceeds without memory.
        memory_service = None
        if wf_config.get("memory_enabled"):
            try:
                from api.services.pipecat.memory_service import (
                    create_workflow_memory_service,
                )

                _mem_phone = (
                    (merged_call_context_vars or {}).get("phone_number")
                    or (merged_call_context_vars or {}).get("phone")
                    or ((workflow_run.gathered_context or {}).get("caller_number") if workflow_run else None)
                )
                memory_service = create_workflow_memory_service(
                    organization_id=getattr(workflow, "organization_id", None),
                    phone_number=_mem_phone,
                    enable_recall=wf_config.get("memory_recall_enabled", True),
                    enable_retain=wf_config.get("memory_retain_enabled", True),
                    recall_timeout=float(wf_config.get("memory_recall_timeout", 1.5)),
                    search_limit=int(wf_config.get("memory_search_limit", 6)),
                )
            except Exception as _mem_init_err:
                logger.warning(
                    f"[Memory] Failed to set up persistent memory (non-fatal): {_mem_init_err}"
                )
                memory_service = None

        pipeline = build_pipeline(
            transport,
            stt,
            transcript,
            audio_buffer,
            audio_synchronizer,
            llm,
            tts,
            user_context_aggregator,
            assistant_context_aggregator,
            pipeline_engine_callback_processor,
            stt_mute_filter,
            pipeline_metrics_aggregator,
            user_idle_disconnect,
            user_interim_broadcaster=user_interim_broadcaster,
            assistant_stream_broadcaster=assistant_stream_broadcaster,
            input_guardrail=input_guardrail,
            output_guardrail=output_guardrail,
            silence_tracker=silence_tracker,
            memory_service=memory_service,
        )

    # Create pipeline task with audio configuration
    task = create_pipeline_task(pipeline, workflow_run_id, audio_config)

    # Now set the task on the engine
    engine.set_task(task)

    # Register event handlers. LiveKit fires participant lifecycle events under
    # different names than the websocket/aiortc transports, so map the
    # connect/disconnect hooks accordingly; otherwise the greeting + recording
    # setup (normally gated on "on_client_connected") never runs for LiveKit.
    in_memory_audio_buffer, in_memory_transcript_buffer = (
        register_transport_event_handlers(
            task,
            transport,
            workflow_run_id,
            engine=engine,
            audio_buffer=audio_buffer,
            audio_synchronizer=audio_synchronizer,
            audio_config=audio_config,
            connect_event=(
                "on_first_participant_joined"
                if greeting_on_participant_join
                else "on_client_connected"
            ),
            disconnect_event=(
                "on_participant_disconnected"
                if greeting_on_participant_join
                else "on_client_disconnected"
            ),
        )
    )

    register_task_event_handler(
        workflow_run_id,
        engine,
        task,
        transport,
        audio_buffer,
        audio_synchronizer,
        in_memory_audio_buffer,
        in_memory_transcript_buffer,
        pipeline_metrics_aggregator,
    )

    register_audio_data_handler(
        audio_synchronizer, workflow_run_id, in_memory_audio_buffer
    )
    register_transcript_handler(
        transcript, workflow_run_id, in_memory_transcript_buffer
    )

    _pipe_t_built = _time.perf_counter()
    logger.info(
        f"⏱ [LATENCY] Pipeline built + handlers registered | run_id={workflow_run_id} | "
        f"elapsed={(_pipe_t_built - _pipe_t0)*1000:.0f}ms | "
        f"build_time={(_pipe_t_built - _pipe_t_services)*1000:.0f}ms"
    )

    try:
        loop = asyncio.get_running_loop()
        params = PipelineTaskParams(loop=loop)

        pipeline_task = asyncio.current_task()
        if pipeline_task:
            await active_call_tracker.register(pipeline_task)

        await task.run(params)
        logger.info(f"Task completed for run {workflow_run_id}")
    except asyncio.CancelledError:
        logger.warning("Received CancelledError in _run_pipeline")
    finally:
        ContextProviderRegistry.remove_providers(str(workflow_run_id))
        logger.debug(f"Cleaned up context providers for workflow run {workflow_run_id}")
