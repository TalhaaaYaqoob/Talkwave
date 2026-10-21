#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""Deepgram speech-to-text service implementation."""

import asyncio
from typing import AsyncGenerator, Dict, Optional

from loguru import logger

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.stt_service import STTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601
from pipecat.utils.tracing.service_decorators import traced_stt

try:
    from deepgram import (
        AsyncListenWebSocketClient,
        DeepgramClient,
        DeepgramClientOptions,
        ErrorResponse,
        LiveOptions,
        LiveResultResponse,
        LiveTranscriptionEvents,
    )
except ModuleNotFoundError as e:
    logger.error(f"Exception: {e}")
    logger.error("In order to use Deepgram, you need to `pip install pipecat-ai[deepgram]`.")
    raise Exception(f"Missing module: {e}")


class DeepgramSTTService(STTService):
    """Deepgram speech-to-text service.

    Provides real-time speech recognition using Deepgram's WebSocket API.
    Supports configurable models, languages, VAD events, and various audio
    processing options.
    """

    def __init__(
        self,
        *,
        api_key: str,
        url: str = "",
        base_url: str = "",
        sample_rate: Optional[int] = None,
        live_options: Optional[LiveOptions] = None,
        addons: Optional[Dict] = None,
        **kwargs,
    ):
        """Initialize the Deepgram STT service.

        Args:
            api_key: Deepgram API key for authentication.
            url: Custom Deepgram API base URL.

                .. deprecated:: 0.0.64
                    Parameter `url` is deprecated, use `base_url` instead.

            base_url: Custom Deepgram API base URL.
            sample_rate: Audio sample rate. If None, uses default or live_options value.
            live_options: Deepgram LiveOptions for detailed configuration.
            addons: Additional Deepgram features to enable.
            **kwargs: Additional arguments passed to the parent STTService.
        """
        sample_rate = sample_rate or (live_options.sample_rate if live_options else None)
        super().__init__(sample_rate=sample_rate, **kwargs)

        if url:
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("always")
                warnings.warn(
                    "Parameter 'url' is deprecated, use 'base_url' instead.",
                    DeprecationWarning,
                )
            base_url = url

        default_options = LiveOptions(
            encoding="linear16",
            language=Language.EN,
            model="nova-3-general",
            channels=1,
            interim_results=True,
            smart_format=True,
            punctuate=True,
            profanity_filter=True,
            vad_events=False,
        )

        merged_options = default_options.to_dict()
        if live_options:
            default_model = default_options.model
            # Filter out None values and the string "None" from live_options
            # to prevent overwriting valid defaults (e.g. encoding, channels)
            live_dict = live_options.to_dict()
            filtered_live = {
                k: v for k, v in live_dict.items()
                if v is not None and v != "None"
            }
            merged_options.update(filtered_live)
            # NOTE(aleix): Fixes an issue in deepgram-sdk where `model` is initialized
            # to the string "None" instead of the value `None`.
            if "model" in merged_options and merged_options["model"] == "None":
                merged_options["model"] = default_model

        if "language" in merged_options and isinstance(merged_options["language"], Language):
            merged_options["language"] = merged_options["language"].value

        # Strip None values — the Deepgram SDK may send them as literal "None" in the URL,
        # and certain params (like utterance_end_ms) cause HTTP 400 on some plans.
        merged_options = {k: v for k, v in merged_options.items() if v is not None}

        self.set_model_name(merged_options["model"])
        self._settings = merged_options
        self._addons = addons

        # Reconnection state to prevent infinite reconnect loops
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._reconnecting = False
        self._gave_up = False  # Flag to stop logging after max attempts

        self._client = DeepgramClient(
            api_key,
            config=DeepgramClientOptions(
                url=base_url,
                options={"keepalive": "true"},  # verbose=logging.DEBUG
            ),
        )

        # Initialize connection to None so prewarm/start can check state
        self._connection: Optional[AsyncListenWebSocketClient] = None
        self._connection_lock = asyncio.Lock()

        if self.vad_enabled:
            self._register_event_handler("on_speech_started")
            self._register_event_handler("on_utterance_end")

    @property
    def vad_enabled(self):
        """Check if Deepgram VAD events are enabled.

        Returns:
            True if VAD events are enabled in the current settings.
        """
        return self._settings["vad_events"]

    def can_generate_metrics(self) -> bool:
        """Check if this service can generate processing metrics.

        Returns:
            True, as Deepgram service supports metrics generation.
        """
        return True

    async def set_model(self, model: str):
        """Set the Deepgram model and reconnect.

        Args:
            model: The Deepgram model name to use.
        """
        await super().set_model(model)
        logger.info(f"Switching STT model to: [{model}]")
        self._settings["model"] = model
        await self._disconnect()
        await self._connect()

    async def set_language(self, language: Language):
        """Set the recognition language and reconnect.

        Args:
            language: The language to use for speech recognition.
        """
        logger.info(f"Switching STT language to: [{language}]")
        self._settings["language"] = language
        await self._disconnect()
        await self._connect()

    async def start(self, frame: StartFrame):
        """Start the Deepgram STT service.

        Args:
            frame: The start frame containing initialization parameters.
        """
        await super().start(frame)
        self._settings["sample_rate"] = self.sample_rate
        # Skip connection if prewarm already established a live connection
        try:
            if self._connection is not None and await self._connection.is_connected():
                logger.info("[DEEPGRAM STT] Already connected (pre-warmed), skipping reconnect")
                return
        except Exception:
            pass
        await self._connect()

    async def stop(self, frame: EndFrame):
        """Stop the Deepgram STT service.

        Args:
            frame: The end frame.
        """
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        """Cancel the Deepgram STT service.

        Args:
            frame: The cancel frame.
        """
        await super().cancel(frame)
        await self._disconnect()

    async def _try_reconnect(self, reason: str) -> bool:
        """Attempt to reconnect with limits to prevent infinite loops.

        Args:
            reason: Description of why reconnection is needed.

        Returns:
            True if reconnection succeeded, False if limit reached or failed.
        """
        if self._reconnecting or self._gave_up:
            return False

        if self._reconnect_attempts >= self._max_reconnect_attempts:
            if not self._gave_up:
                # Only log this ONCE, not for every audio frame
                self._gave_up = True
                logger.error(
                    f"[DEEPGRAM STT] Max reconnection attempts ({self._max_reconnect_attempts}) "
                    f"reached. Reason: {reason}. STT is disabled for this session."
                )
            return False

        self._reconnecting = True
        self._reconnect_attempts += 1
        backoff = min(2 ** (self._reconnect_attempts - 1), 8)  # 1s, 2s, 4s, 8s max

        logger.warning(
            f"[DEEPGRAM STT] Reconnecting ({self._reconnect_attempts}/{self._max_reconnect_attempts}), "
            f"reason: {reason}, backoff: {backoff}s"
        )

        try:
            await asyncio.sleep(backoff)
            await self._connect(force_reconnect=True)
            if self._connection is not None and await self._connection.is_connected():
                # Reset on successful connection
                self._reconnect_attempts = 0
                self._reconnecting = False
                self._gave_up = False
                logger.info("[DEEPGRAM STT] Reconnection successful!")
                return True
            else:
                self._reconnecting = False
                return False
        except Exception as e:
            logger.error(f"[DEEPGRAM STT] Reconnection failed: {e}")
            self._reconnecting = False
            return False

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """Send audio data to Deepgram for transcription.

        Args:
            audio: Raw audio bytes to transcribe.

        Yields:
            Frame: None (transcription results come via WebSocket callbacks).
        """
        # If we've given up on reconnection, silently drop audio
        if self._gave_up:
            yield None
            return

        # If connection not yet created (shouldn't happen after start), skip
        if self._connection is None:
            yield None
            return

        try:
            if await self._connection.is_connected():
                await self._connection.send(audio)
                # Reset attempts on successful send
                self._reconnect_attempts = 0
            else:
                if await self._try_reconnect("connection lost while sending audio"):
                    # Retry sending after successful reconnect
                    await self._connection.send(audio)
        except Exception as e:
            if not self._gave_up:
                logger.warning(f"[DEEPGRAM STT] Failed to send audio: {e}")
                await self._try_reconnect(f"send failed: {e}")
        yield None

    async def _connect(self, force_reconnect: bool = False):
        async with self._connection_lock:
            # Guard against duplicate concurrent connects (e.g. prewarm + start).
            if self._connection is not None:
                try:
                    if await self._connection.is_connected() and not force_reconnect:
                        logger.debug("[DEEPGRAM STT] Already connected, skipping reconnect")
                        return
                    if await self._connection.is_connected() and force_reconnect:
                        logger.debug("[DEEPGRAM STT] Forcing Deepgram reconnect")
                        await self._connection.finish()
                except Exception:
                    pass
                self._connection = None

            logger.info("[DEEPGRAM STT] ════════════════════════════════════════")
            logger.info("[DEEPGRAM STT] CONNECTING TO DEEPGRAM")
            logger.info("[DEEPGRAM STT] ════════════════════════════════════════")
            logger.info(f"[DEEPGRAM STT] Model: {self._settings.get('model', 'unknown')}")
            logger.info(f"[DEEPGRAM STT] Language: {self._settings.get('language', 'unknown')}")
            logger.info(f"[DEEPGRAM STT] Encoding: {self._settings.get('encoding', 'NOT SET')}")
            logger.info(f"[DEEPGRAM STT] Channels: {self._settings.get('channels', 'NOT SET')}")
            logger.info(f"[DEEPGRAM STT] Sample Rate: {self._settings.get('sample_rate', 'NOT SET')}")
            logger.info(f"[DEEPGRAM STT] Smart Format: {self._settings.get('smart_format', False)}")
            logger.info(f"[DEEPGRAM STT] Punctuate: {self._settings.get('punctuate', False)}")
            logger.info(f"[DEEPGRAM STT] Numerals: {self._settings.get('numerals', False)}")
            logger.info(f"[DEEPGRAM STT] Interim Results: {self._settings.get('interim_results', False)}")
            logger.info(f"[DEEPGRAM STT] Endpointing: {self._settings.get('endpointing', 'default')}ms")
            logger.info(f"[DEEPGRAM STT] VAD Events: {self._settings.get('vad_events', False)}")
            if self._addons:
                logger.info(f"[DEEPGRAM STT] Addons: {self._addons}")
            logger.info("[DEEPGRAM STT] ════════════════════════════════════════")

            connection: AsyncListenWebSocketClient = self._client.listen.asyncwebsocket.v("1")

            connection.on(
                LiveTranscriptionEvents(LiveTranscriptionEvents.Transcript), self._on_message
            )
            connection.on(LiveTranscriptionEvents(LiveTranscriptionEvents.Error), self._on_error)

            if self.vad_enabled:
                connection.on(
                    LiveTranscriptionEvents(LiveTranscriptionEvents.SpeechStarted),
                    self._on_speech_started,
                )
                connection.on(
                    LiveTranscriptionEvents(LiveTranscriptionEvents.UtteranceEnd),
                    self._on_utterance_end,
                )

            # Log full settings for debugging connection failures
            logger.debug(f"[DEEPGRAM STT] Full settings: {self._settings}")

            if not await connection.start(options=self._settings, addons=self._addons):
                logger.error(
                    f"[DEEPGRAM STT] ✗ Failed to connect to Deepgram! "
                    f"encoding={self._settings.get('encoding')}, "
                    f"channels={self._settings.get('channels')}, "
                    f"model={self._settings.get('model')}"
                )
                self._connection = None
                await self.push_error(error_msg=f"Unable to connect to Deepgram")
            else:
                self._connection = connection
                headers = {
                    k: v
                    for k, v in connection._socket.response.headers.items()
                    if k.startswith("dg-")
                }
                logger.info(f"[DEEPGRAM STT] ✓ Connected successfully!")
                logger.info(f"[DEEPGRAM STT] Headers: {headers}")

    async def _disconnect(self):
        async with self._connection_lock:
            connection = self._connection
            self._connection = None
            if connection is not None and await connection.is_connected():
                logger.debug("Disconnecting from Deepgram")
                # Deepgram swallows asyncio.CancelledError internally which prevents
                # proper cancellation propagation. This issue was found with
                # parallel pipelines where `CancelFrame` was not awaited for to
                # finish in all branches and it was pushed downstream reaching the
                # end of the pipeline, which caused `cleanup()` to be called while
                # Deepgram disconnection was still finishing and therefore
                # preventing the task cancellation that occurs during `cleanup()`.
                # GH issue: https://github.com/deepgram/deepgram-python-sdk/issues/570
                await connection.finish()

    async def start_metrics(self):
        """Start TTFB and processing metrics collection."""
        await self.start_ttfb_metrics()
        await self.start_processing_metrics()

    async def _on_error(self, *args, **kwargs):
        error: ErrorResponse = kwargs["error"]
        logger.warning(f"{self} connection error: {error}")
        await self.push_error(error_msg=f"{error}")
        await self.stop_all_metrics()
        # NOTE(aleix): we don't disconnect (i.e. call finish on the connection)
        # because this triggers more errors internally in the Deepgram SDK. So,
        # we just forget about the previous connection and create a new one.
        await self._try_reconnect(f"connection error: {error}")

    async def _on_speech_started(self, *args, **kwargs):
        await self.start_metrics()
        await self._call_event_handler("on_speech_started", *args, **kwargs)

    async def _on_utterance_end(self, *args, **kwargs):
        await self._call_event_handler("on_utterance_end", *args, **kwargs)

    @traced_stt
    async def _handle_transcription(
        self, transcript: str, is_final: bool, language: Optional[Language] = None
    ):
        """Handle a transcription result with tracing."""
        pass

    async def _on_message(self, *args, **kwargs):
        result: LiveResultResponse = kwargs["result"]
        if len(result.channel.alternatives) == 0:
            return
        is_final = result.is_final
        transcript = result.channel.alternatives[0].transcript
        language = None
        detected_language_code = None
        if result.channel.alternatives[0].languages:
            detected_language_code = result.channel.alternatives[0].languages[0]
            language = Language(detected_language_code)
        if len(transcript) > 0:
            await self.stop_ttfb_metrics()
            if is_final:
                # LOG FINAL TRANSCRIPTION WITH LANGUAGE
                logger.info(f"[DEEPGRAM STT] ════════════════════════════════════════")
                logger.info(f"[DEEPGRAM STT] FINAL TRANSCRIPTION")
                logger.info(f"[DEEPGRAM STT] Language Detected: {detected_language_code or 'unknown'}")
                logger.info(f"[DEEPGRAM STT] Text: {transcript}")
                logger.info(f"[DEEPGRAM STT] Model: {self._settings.get('model', 'unknown')}")
                logger.info(f"[DEEPGRAM STT] Config Language: {self._settings.get('language', 'unknown')}")
                logger.info(f"[DEEPGRAM STT] ════════════════════════════════════════")
                
                await self.push_frame(
                    TranscriptionFrame(
                        transcript,
                        self._user_id,
                        time_now_iso8601(),
                        language,
                        result=result,
                    )
                )
                await self._handle_transcription(transcript, is_final, language)
                await self.stop_processing_metrics()
            else:
                # Log interim transcriptions at debug level
                logger.debug(f"[DEEPGRAM STT] Interim: {transcript} (lang: {detected_language_code or 'detecting...'})")
                # For interim transcriptions, just push the frame without tracing
                await self.push_frame(
                    InterimTranscriptionFrame(
                        transcript,
                        self._user_id,
                        time_now_iso8601(),
                        language,
                        result=result,
                    )
                )

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process frames with Deepgram-specific handling.

        Args:
            frame: The frame to process.
            direction: The direction of frame processing.
        """
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame) and not self.vad_enabled:
            # Start metrics if Deepgram VAD is disabled & pipeline VAD has detected speech
            await self.start_metrics()
        elif isinstance(frame, UserStoppedSpeakingFrame):
            # https://developers.deepgram.com/docs/finalize
            # Check connection state and handle errors gracefully to avoid
            # disrupting the pipeline when the WebSocket is temporarily unavailable
            if self._gave_up or self._connection is None:
                return
            try:
                if await self._connection.is_connected():
                    await self._connection.finalize()
                    logger.trace(f"Triggered finalize event on: {frame.name=}, {direction=}")
                else:
                    await self._try_reconnect("connection not active during finalize")
            except Exception as e:
                if not self._gave_up:
                    logger.warning(f"[DEEPGRAM STT] Finalize failed: {e}")
                    await self._try_reconnect(f"finalize failed: {e}")
