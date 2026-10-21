import os
from typing import TYPE_CHECKING

from loguru import logger

from api.constants import (
    ENABLE_TRACING,
)
from api.services.pipecat.audio_config import AudioConfig
from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.audio.audio_buffer_processor import AudioBuffer
from pipecat.processors.audio.audio_synchronizer import AudioSynchronizer
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.transcript_processor import TranscriptProcessor
from pipecat.utils.context import turn_var


class TranscriptionFrameFilter(FrameProcessor):
    """Consumes TranscriptionFrame/InterimTranscriptionFrame so they don't
    propagate to downstream processors like the LLM context aggregator.

    Used in the realtime pipeline where Deepgram STT runs alongside Gemini Live
    purely for UI transcription. Without this filter, the transcription text
    would be injected into Gemini's context (which already receives the raw
    audio), causing duplicate/conflicting input.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, (TranscriptionFrame, InterimTranscriptionFrame)):
            return
        await self.push_frame(frame, direction)

if TYPE_CHECKING:
    from api.services.workflow.pipecat_engine import PipecatEngine


def create_pipeline_components(audio_config: AudioConfig, engine: "PipecatEngine"):
    """Create and return the main pipeline components with proper audio configuration"""
    logger.info(f"Creating pipeline components with audio config: {audio_config}")

    # Use new split audio buffer for better performance
    audio_buffer = AudioBuffer(
        sample_rate=audio_config.pipeline_sample_rate,
        buffer_size=audio_config.buffer_size_bytes,
        max_recording_bytes=audio_config.max_recording_bytes,
    )

    # Create synchronizer for merged audio (outside pipeline)
    audio_synchronizer = AudioSynchronizer(
        sample_rate=audio_config.pipeline_sample_rate,
        buffer_size=audio_config.buffer_size_bytes,
    )

    transcript = TranscriptProcessor(
        assistant_correct_aggregation_callback=engine.create_aggregation_correction_callback()
    )

    context = LLMContext()

    return audio_buffer, audio_synchronizer, transcript, context


def build_pipeline(
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
    user_interim_broadcaster=None,
    assistant_stream_broadcaster=None,
    input_guardrail=None,
    output_guardrail=None,
    silence_tracker=None,
    memory_service=None,
):
    """Build the main pipeline with all components"""
    logger.info("Registering audio buffer processors with synchronizer")
    audio_synchronizer.register_processors(audio_buffer.input(), audio_buffer.output())

    processors = [
        transport.input(),
        audio_buffer.input(),
        stt,
        stt_mute_filter,
    ]

    if user_interim_broadcaster:
        processors.append(user_interim_broadcaster)

    processors.append(user_idle_disconnect)

    if input_guardrail:
        processors.append(input_guardrail)

    if silence_tracker:
        processors.append(silence_tracker)

    processors.extend([
        transcript.user(),
        user_context_aggregator,
    ])

    # Persistent cross-call memory: recalls relevant past conversations before
    # the LLM and retains new exchanges after each turn. Sits between the user
    # aggregator and the LLM so it can enrich the context frame in-flight.
    if memory_service is not None:
        processors.append(memory_service)

    processors.extend([
        llm,
        pipeline_engine_callback_processor,
    ])

    if assistant_stream_broadcaster:
        processors.append(assistant_stream_broadcaster)

    if output_guardrail:
        processors.append(output_guardrail)

    processors.extend([
        tts,
        transport.output(),
        audio_buffer.output(),
        transcript.assistant(),
        assistant_context_aggregator,
        pipeline_metrics_aggregator,
    ])

    return Pipeline(processors)


def build_realtime_pipeline(
    transport,
    llm,  # GeminiLiveLLMService
    stt,  # Deepgram STT for user transcription (UI display only)
    audio_buffer,
    audio_synchronizer,
    transcript,
    user_context_aggregator,
    assistant_context_aggregator,
    pipeline_engine_callback_processor,
    pipeline_metrics_aggregator,
    user_idle_disconnect,
):
    """Build pipeline for realtime voice mode using Gemini Live API.
    
    In realtime mode, the Gemini Live service handles audio I/O natively.
    A Deepgram STT runs in the pipeline purely for user transcription display
    on the frontend - it does NOT affect Gemini's conversation context.
    
    Audio flow: transport → STT (passthrough) → Gemini Live LLM
    Transcription flow: STT → TranscriptionFrame → transcript.user() → [filtered out]
    
    Args:
        transport: The transport (Twilio, WebRTC, etc.)
        llm: GeminiLiveLLMService for native audio processing
        stt: Deepgram STT service for user transcription (audio passthrough)
        audio_buffer: Audio buffer for recording
        audio_synchronizer: Audio synchronizer for merged audio
        transcript: Transcript processor
        user_context_aggregator: User context aggregator
        assistant_context_aggregator: Assistant context aggregator
        pipeline_engine_callback_processor: Pipeline engine callbacks
        pipeline_metrics_aggregator: Metrics aggregator
        user_idle_disconnect: User idle processor
        
    Returns:
        Pipeline configured for realtime voice mode
    """
    logger.info("Building realtime pipeline with Gemini Live API + Deepgram STT for transcription")
    
    audio_synchronizer.register_processors(audio_buffer.input(), audio_buffer.output())
    
    processors = [
        transport.input(),
        audio_buffer.input(),
        user_idle_disconnect,
    ]
    
    if stt:
        transcription_filter = TranscriptionFrameFilter()
        processors += [
            stt,                      # Deepgram STT: transcribes audio, passes audio through
            transcript.user(),        # Captures TranscriptionFrame for UI broadcast
            transcription_filter,     # Blocks TranscriptionFrame from reaching LLM context
        ]
    
    processors += [
        user_context_aggregator,
        llm,                          # Gemini Live: receives raw audio, handles conversation
        pipeline_engine_callback_processor,
        transport.output(),
        audio_buffer.output(),
        transcript.assistant(),
        assistant_context_aggregator,
        pipeline_metrics_aggregator,
    ]
    
    return Pipeline(processors)


def create_pipeline_task(pipeline, workflow_run_id, audio_config: AudioConfig = None):
    """Create a pipeline task with appropriate parameters"""
    # Set up pipeline params with audio configuration if provided
    pipeline_params = PipelineParams(
        allow_interruptions=True,
        enable_metrics=True,
        enable_usage_metrics=True,
        send_initial_empty_metrics=False,
        enable_heartbeats=True,
        start_metadata={"workflow_run_id": workflow_run_id},
    )

    # If audio_config is provided, set the audio sample rates
    if audio_config:
        pipeline_params.audio_in_sample_rate = audio_config.transport_in_sample_rate
        pipeline_params.audio_out_sample_rate = audio_config.transport_out_sample_rate
        logger.debug(
            f"Setting pipeline audio params - in: {audio_config.transport_in_sample_rate}Hz, "
            f"out: {audio_config.transport_out_sample_rate}Hz"
        )

    task = PipelineTask(
        pipeline,
        params=pipeline_params,
        enable_tracing=ENABLE_TRACING,
        conversation_id=f"{workflow_run_id}",
    )

    # Check if turn logging is enabled
    enable_turn_logging = os.getenv("ENABLE_TURN_LOGGING", "false").lower() == "true"

    if enable_turn_logging:
        # Attach event handlers to propagate turn information into the logging context
        turn_observer = task.turn_tracking_observer

        if turn_observer is not None:
            # Import turn context manager only if needed
            from api.services.pipecat.turn_context import get_turn_context_manager

            async def _on_turn_started(observer, turn_number: int):
                """Set the current turn number into the context variable."""
                # Set in both contextvar and turn context manager
                turn_var.set(turn_number)
                turn_manager = get_turn_context_manager()
                turn_manager.set_turn(turn_number)

            # Register the handlers with the observer
            turn_observer.add_event_handler("on_turn_started", _on_turn_started)

    return task
