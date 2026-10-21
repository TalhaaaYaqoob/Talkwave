import os

from fastapi import WebSocket
from loguru import logger

from api.constants import APP_ROOT_DIR, ENABLE_RNNOISE, ENABLE_SMART_TURN
from api.db import db_client
from api.enums import OrganizationConfigurationKey
from api.services.looptalk.internal_transport import InternalTransport
from api.services.pipecat.ambient_audio import get_office_ambience_path
from api.services.pipecat.audio_config import AudioConfig
from api.services.telephony.stasis_rtp_connection import StasisRTPConnection
from api.services.telephony.stasis_rtp_serializer import StasisRTPFrameSerializer
from api.services.telephony.stasis_rtp_transport import (
    StasisRTPTransport,
    StasisRTPTransportParams,
)
from pipecat.audio.filters.rnnoise_filter import RNNoiseFilter
from pipecat.audio.mixers.silence_mixer import SilenceAudioMixer
from pipecat.audio.mixers.soundfile_mixer import SoundfileMixer
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from pipecat.serializers.plivo import PlivoFrameSerializer

# Preload Silero VAD model at module load time to avoid ~150ms delay per call
# The model is loaded once and cached by the SileroVADAnalyzer class
_preloaded_vad = SileroVADAnalyzer()
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.serializers.vobiz import VobizFrameSerializer
from pipecat.serializers.vonage import VonageFrameSerializer
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

try:
    from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport
    LIVEKIT_TRANSPORT_AVAILABLE = True
except ImportError:
    LIVEKIT_TRANSPORT_AVAILABLE = False

librnnoise_path = os.path.normpath(
    str(APP_ROOT_DIR / "native" / "rnnoise" / "librnnoise.so")
)


def create_turn_analyzer(workflow_run_id: int, audio_config: AudioConfig):
    """Create a turn analyzer backed by the local Smart Turn HTTP service.

    Args:
        workflow_run_id: ID of the workflow run for turn analyzer context
        audio_config: Audio configuration containing pipeline sample rate
    """
    if ENABLE_SMART_TURN:
        return LocalSmartTurnAnalyzerV3(params=SmartTurnParams())

    return None


def _build_vad_analyzer(vad_config: dict | None, use_flux_stt: bool = False):
    """Build a Silero VAD analyzer, or None when Flux STT handles turn detection.

    When use_flux_stt is True, Deepgram Flux provides model-integrated turn
    detection (StartOfTurn / EndOfTurn / EagerEndOfTurn) so the transport-level
    Silero VAD is unnecessary and would emit duplicate speech frames.
    """
    if use_flux_stt:
        logger.info("[TRANSPORT] VAD disabled — Flux STT handles turn detection natively")
        return None

    default_stop_secs = 0.3 if ENABLE_SMART_TURN else 0.6

    if vad_config:
        return SileroVADAnalyzer(
            params=VADParams(
                confidence=vad_config.get("confidence", 0.6),
                start_secs=vad_config.get("start_seconds", 0.2),
                stop_secs=vad_config.get("stop_seconds", default_stop_secs),
                min_volume=vad_config.get("minimum_volume", 0.5),
            )
        )

    return SileroVADAnalyzer(
        params=VADParams(
            confidence=0.6,
            start_secs=0.2,
            stop_secs=default_stop_secs,
            min_volume=0.5,
        )
    )


def _build_audio_out_mixer(
    ambient_noise_config: dict | None, sample_rate: int
):
    """Return the outgoing-audio mixer to install on a transport.

    When the workflow enables ambient noise, mix a soft office-ambience
    loop under the agent's speech. The asset is resolved from
    ``api/assets/`` when present, or synthesized on demand. When ambient
    noise is disabled (or the config is absent), return a silent mixer
    so the transport audio pipeline stays bit-for-bit identical to the
    pre-ambient-noise path.
    """
    if not ambient_noise_config or not ambient_noise_config.get("enabled", False):
        return SilenceAudioMixer()

    return SoundfileMixer(
        sound_files={"office": get_office_ambience_path(sample_rate)},
        default_sound="office",
        volume=ambient_noise_config.get("volume", 0.3),
    )


async def create_twilio_transport(
    websocket_client: WebSocket,
    stream_sid: str,
    call_sid: str,
    workflow_run_id: int,
    audio_config: AudioConfig,
    organization_id: int,
    vad_config: dict | None = None,
    ambient_noise_config: dict | None = None,
    telephony_config: dict | None = None,
    use_flux_stt: bool = False,
    disable_turn_analyzer: bool = False,
):
    """Create a transport for Twilio connections"""

    # OPTIMIZATION: Use pre-fetched telephony config if available, otherwise fetch from DB
    if telephony_config:
        account_sid = telephony_config.get("account_sid")
        auth_token = telephony_config.get("auth_token")
    else:
        config = await db_client.get_configuration(
            organization_id, OrganizationConfigurationKey.TELEPHONY_CONFIGURATION.value
        )
        if not config or not config.value:
            raise ValueError(
                f"Twilio credentials not configured for organization {organization_id}"
            )
        account_sid = config.value.get("account_sid")
        auth_token = config.value.get("auth_token")

    if not account_sid or not auth_token:
        raise ValueError(
            f"Incomplete Twilio configuration for organization {organization_id}"
        )

    turn_analyzer = None if (use_flux_stt or disable_turn_analyzer) else create_turn_analyzer(workflow_run_id, audio_config)

    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=account_sid,
        auth_token=auth_token,
    )

    return FastAPIWebsocketTransport(
        websocket=websocket_client,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            audio_in_sample_rate=audio_config.transport_in_sample_rate,
            audio_out_sample_rate=audio_config.transport_out_sample_rate,
            vad_analyzer=_build_vad_analyzer(vad_config, use_flux_stt),
            audio_out_mixer=_build_audio_out_mixer(
                ambient_noise_config, audio_config.transport_out_sample_rate
            ),
            turn_analyzer=turn_analyzer,
            serializer=serializer,
            audio_in_filter=RNNoiseFilter(library_path=librnnoise_path)
            if ENABLE_RNNOISE
            else None,
        ),
    )


async def create_vonage_transport(
    websocket_client,
    call_uuid: str,
    workflow_run_id: int,
    audio_config: AudioConfig,
    organization_id: int,
    vad_config: dict | None = None,
    ambient_noise_config: dict | None = None,
    use_flux_stt: bool = False,
):
    """Create a transport for Vonage connections"""

    # Use the factory to load config from database
    from api.services.telephony.factory import load_telephony_config

    config = await load_telephony_config(organization_id)

    if config.get("provider") != "vonage":
        raise ValueError(f"Expected Vonage provider, got {config.get('provider')}")

    application_id = config.get("application_id")
    private_key = config.get("private_key")

    if not application_id or not private_key:
        raise ValueError(
            f"Incomplete Vonage configuration for organization {organization_id}"
        )

    turn_analyzer = None if use_flux_stt else create_turn_analyzer(workflow_run_id, audio_config)

    serializer = VonageFrameSerializer(
        call_uuid=call_uuid,
        application_id=application_id,
        private_key=private_key,
        params=VonageFrameSerializer.InputParams(
            vonage_sample_rate=audio_config.transport_in_sample_rate,
            sample_rate=audio_config.pipeline_sample_rate,
        ),
    )

    return FastAPIWebsocketTransport(
        websocket=websocket_client,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            audio_in_sample_rate=audio_config.transport_in_sample_rate,
            audio_out_sample_rate=audio_config.transport_out_sample_rate,
            vad_analyzer=_build_vad_analyzer(vad_config, use_flux_stt),
            audio_out_mixer=_build_audio_out_mixer(
                ambient_noise_config, audio_config.transport_out_sample_rate
            ),
            turn_analyzer=turn_analyzer,
            serializer=serializer,
            audio_in_filter=RNNoiseFilter(library_path=librnnoise_path)
            if ENABLE_RNNOISE
            else None,
        ),
    )


async def create_vobiz_transport(
    websocket_client: WebSocket,
    stream_id: str,
    call_id: str,
    workflow_run_id: int,
    audio_config: AudioConfig,
    organization_id: int,
    vad_config: dict | None = None,
    ambient_noise_config: dict | None = None,
    use_flux_stt: bool = False,
):
    """Create a transport for Vobiz connections.

    Vobiz uses Plivo-compatible WebSocket protocol:
    - MULAW audio at 8kHz (same as Twilio)
    - Base64-encoded audio in JSON messages
    - PlivoFrameSerializer handles the protocol
    """
    logger.info(
        f"[run {workflow_run_id}] Creating Vobiz transport - "
        f"stream_id={stream_id}, call_id={call_id}"
    )

    # Load Vobiz configuration from database
    from api.services.telephony.factory import load_telephony_config

    config = await load_telephony_config(organization_id)

    if config.get("provider") != "vobiz":
        raise ValueError(f"Expected Vobiz provider, got {config.get('provider')}")

    auth_id = config.get("auth_id")
    auth_token = config.get("auth_token")

    if not auth_id or not auth_token:
        raise ValueError(
            f"Incomplete Vobiz configuration for organization {organization_id}"
        )

    logger.debug(
        f"[run {workflow_run_id}] Vobiz config loaded - auth_id={auth_id}, "
        f"from_numbers={len(config.get('from_numbers', []))} numbers"
    )

    turn_analyzer = None if use_flux_stt else create_turn_analyzer(workflow_run_id, audio_config)

    # Use VobizFrameSerializer for Vobiz WebSocket protocol
    serializer = VobizFrameSerializer(
        stream_id=stream_id,
        call_id=call_id,
        auth_id=auth_id,
        auth_token=auth_token,
        params=VobizFrameSerializer.InputParams(
            vobiz_sample_rate=8000,  # Vobiz uses MULAW at 8kHz
            sample_rate=audio_config.pipeline_sample_rate,
        ),
    )

    logger.debug(
        f"[run {workflow_run_id}] VobizFrameSerializer created for Vobiz - "
        f"transport_rate=8000Hz, pipeline_rate={audio_config.pipeline_sample_rate}Hz"
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket_client,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            audio_in_sample_rate=audio_config.transport_in_sample_rate,
            audio_out_sample_rate=audio_config.transport_out_sample_rate,
            vad_analyzer=_build_vad_analyzer(vad_config, use_flux_stt),
            audio_out_mixer=_build_audio_out_mixer(
                ambient_noise_config, audio_config.transport_out_sample_rate
            ),
            turn_analyzer=turn_analyzer,
            serializer=serializer,
            audio_in_filter=RNNoiseFilter(library_path=librnnoise_path)
            if ENABLE_RNNOISE
            else None,
        ),
    )

    vad_status = "Flux native" if use_flux_stt else "Silero VAD"
    logger.info(
        f"[run {workflow_run_id}] Vobiz transport created successfully (turn detection: {vad_status})"
    )
    return transport


def create_webrtc_transport(
    webrtc_connection: SmallWebRTCConnection,
    workflow_run_id: int,
    audio_config: AudioConfig,
    vad_config: dict | None = None,
    ambient_noise_config: dict | None = None,
    use_flux_stt: bool = False,
    disable_turn_analyzer: bool = False,
):
    """Create a transport for WebRTC connections"""
    turn_analyzer = None if (use_flux_stt or disable_turn_analyzer) else create_turn_analyzer(workflow_run_id, audio_config)

    return SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=audio_config.transport_in_sample_rate,
            audio_out_sample_rate=audio_config.transport_out_sample_rate,
            vad_analyzer=_build_vad_analyzer(vad_config, use_flux_stt),
            audio_out_mixer=_build_audio_out_mixer(
                ambient_noise_config, audio_config.transport_out_sample_rate
            ),
            turn_analyzer=turn_analyzer,
            audio_in_filter=RNNoiseFilter(library_path=librnnoise_path)
            if ENABLE_RNNOISE
            else None,
        ),
    )


def create_stasis_transport(
    stasis_connection: StasisRTPConnection,
    workflow_run_id: int,
    audio_config: AudioConfig,
    vad_config: dict | None = None,
    ambient_noise_config: dict | None = None,
    use_flux_stt: bool = False,
):
    """Create a transport for ARI connections"""
    turn_analyzer = None if use_flux_stt else create_turn_analyzer(workflow_run_id, audio_config)

    serializer = StasisRTPFrameSerializer(
        StasisRTPFrameSerializer.InputParams(
            sample_rate=audio_config.transport_in_sample_rate
        )
    )

    return StasisRTPTransport(
        stasis_connection,
        params=StasisRTPTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_out_sample_rate=audio_config.transport_out_sample_rate,
            audio_in_sample_rate=audio_config.transport_in_sample_rate,
            audio_out_10ms_chunks=2,  # Send 20ms packets
            vad_analyzer=_build_vad_analyzer(vad_config, use_flux_stt),
            audio_out_mixer=_build_audio_out_mixer(
                ambient_noise_config, audio_config.transport_out_sample_rate
            ),
            turn_analyzer=turn_analyzer,
            serializer=serializer,
            audio_in_filter=RNNoiseFilter(library_path=librnnoise_path)
            if ENABLE_RNNOISE
            else None,
        ),
    )


def create_livekit_transport(
    livekit_url: str,
    livekit_token: str,
    room_name: str,
    workflow_run_id: int,
    audio_config: AudioConfig,
    vad_config: dict | None = None,
    ambient_noise_config: dict | None = None,
    use_flux_stt: bool = False,
    disable_turn_analyzer: bool = False,
):
    """Create a transport that connects to a LiveKit Cloud room as an agent participant."""
    if not LIVEKIT_TRANSPORT_AVAILABLE:
        raise RuntimeError(
            "LiveKit transport not available. Install with: pip install livekit"
        )

    turn_analyzer = None if (use_flux_stt or disable_turn_analyzer) else create_turn_analyzer(workflow_run_id, audio_config)

    params = LiveKitParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        audio_in_sample_rate=audio_config.transport_in_sample_rate,
        audio_out_sample_rate=audio_config.transport_out_sample_rate,
        vad_analyzer=_build_vad_analyzer(vad_config, use_flux_stt),
        audio_out_mixer=_build_audio_out_mixer(
            ambient_noise_config, audio_config.transport_out_sample_rate
        ),
        turn_analyzer=turn_analyzer,
        audio_in_filter=RNNoiseFilter(library_path=librnnoise_path)
        if ENABLE_RNNOISE
        else None,
    )

    return LiveKitTransport(
        url=livekit_url,
        token=livekit_token,
        room_name=room_name,
        params=params,
    )


def create_internal_transport(
    workflow_run_id: int,
    audio_config: AudioConfig,
    latency_seconds: float = 0.0,
    vad_config: dict | None = None,
    ambient_noise_config: dict | None = None,
    use_flux_stt: bool = False,
):
    """Create an internal transport for agent-to-agent connections (LoopTalk).

    Args:
        workflow_run_id: ID of the workflow run for turn analyzer context
        audio_config: Audio configuration for the transport
        latency_seconds: Network latency to simulate
        use_flux_stt: When True, skip VAD/turn analyzer (Flux handles natively)

    Returns:
        InternalTransport instance configured with turn analyzer
    """
    turn_analyzer = None if use_flux_stt else create_turn_analyzer(workflow_run_id, audio_config)

    return InternalTransport(
        params=TransportParams(
            audio_out_enabled=True,
            audio_out_sample_rate=audio_config.transport_out_sample_rate,
            audio_out_channels=1,
            audio_in_enabled=True,
            audio_in_sample_rate=audio_config.transport_in_sample_rate,
            audio_in_channels=1,
            vad_analyzer=_build_vad_analyzer(vad_config, use_flux_stt),
            audio_out_mixer=_build_audio_out_mixer(
                ambient_noise_config, audio_config.transport_out_sample_rate
            ),
            turn_analyzer=turn_analyzer,
            audio_in_filter=RNNoiseFilter(library_path=librnnoise_path)
            if ENABLE_RNNOISE
            else None,
        ),
        latency_seconds=latency_seconds,
    )
