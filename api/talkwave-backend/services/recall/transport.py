"""Recall.ai real-time audio transport for meeting agents.

Manages the WebSocket connection for streaming meeting audio
from Recall.ai to our pipeline, and sending TTS audio back.

Uses Recall's Output Media API — we host a lightweight WebSocket
endpoint that Recall streams meeting audio into, and we push
generated TTS audio back through the Output Audio endpoint.
"""

from __future__ import annotations

import asyncio
import io
import struct
from typing import Callable, Optional

from loguru import logger


class RecallAudioTransport:
    """Bidirectional audio transport between Recall.ai and TalkWave pipeline.

    Receives raw PCM audio from the meeting (via webhook/websocket) and
    provides it to STT. Accepts TTS output audio and routes it back to
    Recall for playback in the meeting.
    """

    def __init__(
        self,
        bot_id: str,
        recall_client,
        sample_rate: int = 16000,
        channels: int = 1,
        sample_width: int = 2,
    ):
        self.bot_id = bot_id
        self.recall_client = recall_client
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width

        self._audio_in_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=500)
        self._audio_out_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=500)
        self._running = False
        self._output_task: Optional[asyncio.Task] = None

        self._on_audio_callback: Optional[Callable[[bytes], None]] = None
        self._accumulated_tts_buffer = bytearray()
        self._tts_flush_interval = 0.5

    def on_audio_received(self, callback: Callable[[bytes], None]):
        """Register callback for incoming meeting audio frames."""
        self._on_audio_callback = callback

    async def start(self):
        """Start the transport — begins processing audio queues."""
        self._running = True
        self._output_task = asyncio.create_task(self._process_output_queue())
        logger.info(f"[RecallTransport] Started for bot {self.bot_id}")

    async def stop(self):
        """Stop the transport and flush remaining audio."""
        self._running = False
        if self._output_task:
            self._output_task.cancel()
            try:
                await self._output_task
            except asyncio.CancelledError:
                pass

        if self._accumulated_tts_buffer:
            await self._flush_tts_buffer()

        logger.info(f"[RecallTransport] Stopped for bot {self.bot_id}")

    async def push_meeting_audio(self, audio_data: bytes):
        """Push audio received from the meeting into the pipeline.

        Called by the webhook/websocket handler when Recall sends
        meeting audio to our server.
        """
        try:
            self._audio_in_queue.put_nowait(audio_data)
            if self._on_audio_callback:
                self._on_audio_callback(audio_data)
        except asyncio.QueueFull:
            pass

    async def push_tts_audio(self, audio_data: bytes):
        """Queue TTS audio to be sent back to the meeting."""
        try:
            self._audio_out_queue.put_nowait(audio_data)
        except asyncio.QueueFull:
            logger.warning("[RecallTransport] TTS output queue full, dropping frame")

    async def read_audio_frame(self, num_frames: int = 480) -> Optional[bytes]:
        """Read a chunk of meeting audio for STT processing.

        Args:
            num_frames: Number of audio frames to read (default 480 = 30ms at 16kHz).
        """
        try:
            return await asyncio.wait_for(self._audio_in_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None

    async def _process_output_queue(self):
        """Background task that batches TTS audio and sends to Recall."""
        while self._running:
            try:
                try:
                    audio = await asyncio.wait_for(
                        self._audio_out_queue.get(), timeout=self._tts_flush_interval
                    )
                    self._accumulated_tts_buffer.extend(audio)
                except asyncio.TimeoutError:
                    pass

                if len(self._accumulated_tts_buffer) > self.sample_rate * self.sample_width:
                    await self._flush_tts_buffer()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[RecallTransport] Output queue error: {e}")
                await asyncio.sleep(0.5)

    async def _flush_tts_buffer(self):
        """Convert accumulated PCM to MP3 and send to Recall."""
        if not self._accumulated_tts_buffer:
            return

        pcm_data = bytes(self._accumulated_tts_buffer)
        self._accumulated_tts_buffer.clear()

        mp3_data = self._pcm_to_mp3(pcm_data)
        if mp3_data:
            await self.recall_client.send_audio(self.bot_id, mp3_data)

    def _pcm_to_mp3(self, pcm_data: bytes) -> Optional[bytes]:
        """Convert raw PCM audio to MP3 format for Recall's Output Audio endpoint."""
        try:
            wav_buffer = io.BytesIO()
            num_samples = len(pcm_data) // self.sample_width
            data_size = len(pcm_data)
            wav_header = struct.pack(
                "<4sI4s4sIHHIIHH4sI",
                b"RIFF",
                36 + data_size,
                b"WAVE",
                b"fmt ",
                16,
                1,  # PCM
                self.channels,
                self.sample_rate,
                self.sample_rate * self.channels * self.sample_width,
                self.channels * self.sample_width,
                self.sample_width * 8,
                b"data",
                data_size,
            )
            wav_buffer.write(wav_header)
            wav_buffer.write(pcm_data)
            return wav_buffer.getvalue()
        except Exception as e:
            logger.error(f"[RecallTransport] PCM conversion failed: {e}")
            return None
