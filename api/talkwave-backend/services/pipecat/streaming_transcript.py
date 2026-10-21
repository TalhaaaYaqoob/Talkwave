"""Streaming transcript broadcaster for real-time transcript updates.

Intercepts interim STT frames and LLM text frames to broadcast
partial transcription to the frontend in real-time, rather than
waiting for the speaker to finish.
"""

import asyncio

from loguru import logger

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TextFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from api.services.pipecat.websocket_broadcaster import websocket_broadcaster


class UserInterimBroadcaster(FrameProcessor):
    """Broadcasts interim user transcription frames to the frontend.

    Placed after STT in the pipeline to intercept InterimTranscriptionFrame
    and send partial speech-to-text results in real-time.
    """

    def __init__(self, workflow_run_id: int, **kwargs):
        super().__init__(**kwargs)
        self._workflow_run_id = workflow_run_id

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterimTranscriptionFrame) and frame.text and frame.text.strip():
            asyncio.create_task(
                websocket_broadcaster.send_transcript_interim(
                    self._workflow_run_id,
                    role="user",
                    content=frame.text.strip(),
                    is_final=False,
                )
            )

        await self.push_frame(frame, direction)


class AssistantStreamBroadcaster(FrameProcessor):
    """Broadcasts assistant text to the frontend BEFORE TTS audio plays.

    Sits between the LLM callbacks and TTS so it can intercept text the moment
    the agent decides what to say. Two paths feed into it:

      1. LLM-driven turns:   LLMFullResponseStartFrame → LLMTextFrame×N
                              → LLMFullResponseEndFrame. We stream interim
                              updates as tokens arrive and commit a final
                              `transcript` event when the LLM is done — so
                              the UI shows the complete text even if TTS is
                              later interrupted mid-sentence.

      2. Static-TTS turns:   `_queue_tts_response` emits an empty
                              LLMFullResponseStartFrame, a TTSSpeakFrame
                              containing the full text (greeting, transfer
                              message, end-call goodbye), and an empty
                              LLMFullResponseEndFrame. We forward that
                              text as a final `transcript` immediately so
                              the live transcript shows the message before
                              audio synthesis even begins.

    Both paths previously relied on `transcript.assistant()` to broadcast the
    line, which fires only after TTS has finished — so the UI lagged behind
    the audio and, for the static-TTS greeting, never showed an interim at
    all. Broadcasting here fixes both symptoms.
    """

    def __init__(self, workflow_run_id: int, **kwargs):
        super().__init__(**kwargs)
        self._workflow_run_id = workflow_run_id
        self._accumulator = ""
        self._streaming = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._accumulator = ""
            self._streaming = True

        elif isinstance(frame, LLMFullResponseEndFrame):
            self._streaming = False
            text = self._accumulator.strip()
            if text:
                # Commit the final assistant message immediately. The frontend
                # treats `transcript` as authoritative — it clears the interim
                # bubble and appends a permanent row — so we capture the
                # complete LLM output here rather than waiting for the
                # post-TTS `transcript.assistant()` event which may carry a
                # truncated string if the speaker was interrupted.
                asyncio.create_task(
                    websocket_broadcaster.send_transcript(
                        self._workflow_run_id,
                        role="assistant",
                        content=text,
                    )
                )
            self._accumulator = ""

        elif isinstance(frame, TTSSpeakFrame):
            # Static-TTS path used by greetings, transfer announcements,
            # end-of-call goodbyes, and a few quick-reply branches. These
            # bypass the LLM entirely so no LLMTextFrames flow through and
            # the LLM-streaming branch above sees an empty accumulator.
            text = (frame.text or "").strip()
            if text:
                asyncio.create_task(
                    websocket_broadcaster.send_transcript(
                        self._workflow_run_id,
                        role="assistant",
                        content=text,
                    )
                )

        elif self._streaming and isinstance(frame, (LLMTextFrame, TextFrame)):
            if frame.text:
                self._accumulator += frame.text
                text = self._accumulator.strip()
                if text:
                    asyncio.create_task(
                        websocket_broadcaster.send_transcript_interim(
                            self._workflow_run_id,
                            role="assistant",
                            content=text,
                            is_final=False,
                        )
                    )

        await self.push_frame(frame, direction)
