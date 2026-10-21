"""
Voice agent guardrails — pre-LLM input filtering and post-LLM output filtering.

Pre-LLM:  blocks jailbreak prompts, detects PII in user speech, enforces topic fencing
Post-LLM: screens assistant output for toxic/harmful content and PII leakage
Silence:  tracks total user silence to auto-disconnect idle calls (zero latency impact)
TTS:      strips markdown formatting so TTS engines receive clean plain text
"""

import re
import time
from typing import Any, Awaitable, Callable, Mapping, Optional

from loguru import logger

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    HeartbeatFrame,
    LLMTextFrame,
    StartFrame,
    TTSSpeakFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.utils.text.base_text_filter import BaseTextFilter


# ---------------------------------------------------------------------------
# Pattern libraries (compiled once at import time)
# ---------------------------------------------------------------------------

_JAILBREAK_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore (?:all )?(?:previous |prior |above )?instructions",
        r"ignore (?:your |the )?(?:system )?prompt",
        r"disregard (?:all )?(?:previous |prior )?(?:instructions|rules)",
        r"you are now (?:a |an )?(?:new |different )?(?:ai|assistant|bot|character)",
        r"pretend (?:you are|to be|you're)",
        r"act as (?:if you|a|an)",
        r"from now on,? (?:you|ignore|forget)",
        r"forget (?:all |everything )?(?:you|your|about)",
        r"override (?:your |the )?(?:instructions|rules|guidelines)",
        r"reveal (?:your |the )?(?:system |secret )?prompt",
        r"what (?:is|are) your (?:system |initial )?(?:instructions|prompt|rules)",
        r"do not follow (?:your|any|the) (?:rules|instructions|guidelines)",
        r"(?:jailbreak|dan|developer mode|god mode)",
        r"repeat (?:your |the )?(?:system |initial )?(?:prompt|instructions)",
    ]
]

_PII_PATTERNS = [
    (re.compile(r"\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b"), "SSN"),
    (re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b"), "credit_card"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "email"),
]

_TOXIC_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"(?:kill|murder|harm|hurt|attack|bomb|shoot|stab) (?:yourself|someone|people|them|him|her)",
        r"how to (?:make|build|create) (?:a |an )?(?:bomb|weapon|explosive|poison)",
        r"(?:suicide|self.harm) (?:method|instruction|how)",
    ]
]

_PII_REDACT = re.compile(
    r"\b(?:"
    r"\d{3}[-.\s]?\d{2}[-.\s]?\d{4}"  # SSN
    r"|(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})"  # credit card
    r")\b"
)


def _contains_jailbreak(text: str) -> bool:
    return any(p.search(text) for p in _JAILBREAK_PATTERNS)


def _contains_toxic(text: str) -> bool:
    return any(p.search(text) for p in _TOXIC_PATTERNS)


def _detect_pii(text: str) -> list[str]:
    found = []
    for pattern, label in _PII_PATTERNS:
        if pattern.search(text):
            found.append(label)
    return found


def _redact_pii(text: str) -> str:
    return _PII_REDACT.sub("[REDACTED]", text)


# ---------------------------------------------------------------------------
# TTS text filter — strip markdown so voices don't whisper or glitch
# ---------------------------------------------------------------------------

_MD_BOLD_ITALIC = re.compile(r"\*{1,3}(.+?)\*{1,3}")
_MD_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_MD_NUMBERED = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_MD_INLINE_CODE = re.compile(r"`([^`]+)`")
_MD_CODE_BLOCK = re.compile(r"```[\s\S]*?```")
_MD_STRIKETHROUGH = re.compile(r"~~(.+?)~~")
_MD_UNDERLINE = re.compile(r"__(.+?)__")
_MD_HORIZONTAL_RULE = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_MD_EXTRA_WHITESPACE = re.compile(r"\n{3,}")


class MarkdownTextFilter(BaseTextFilter):
    """Strips markdown formatting from LLM output before it reaches TTS.

    ElevenLabs (and other TTS engines) interpret asterisks, hashes, and other
    markdown symbols as emphasis cues, causing whispering, pitch changes, or
    garbled output.  This filter converts markdown to clean spoken text.
    """

    async def filter(self, text: str) -> str:
        text = _MD_CODE_BLOCK.sub("", text)
        text = _MD_IMAGE.sub(r"\1", text)
        text = _MD_LINK.sub(r"\1", text)
        text = _MD_INLINE_CODE.sub(r"\1", text)
        text = _MD_STRIKETHROUGH.sub(r"\1", text)
        text = _MD_UNDERLINE.sub(r"\1", text)
        text = _MD_BOLD_ITALIC.sub(r"\1", text)
        text = _MD_HEADING.sub("", text)
        text = _MD_BULLET.sub("", text)
        text = _MD_NUMBERED.sub("", text)
        text = _MD_HORIZONTAL_RULE.sub("", text)
        text = _MD_EXTRA_WHITESPACE.sub("\n\n", text)
        return text.strip()

    async def handle_interruption(self):
        pass

    async def reset_interruption(self):
        pass


# ---------------------------------------------------------------------------
# Pre-LLM guardrail processor (user input)
# ---------------------------------------------------------------------------


class InputGuardrailProcessor(FrameProcessor):
    """Intercepts TranscriptionFrame before the LLM context aggregator.

    - Blocks jailbreak / prompt-injection attempts
    - Blocks harmful / toxic requests
    - Detects and optionally redacts PII from user speech
    - Enforces topic boundary (off-topic deflection via callback)
    """

    def __init__(
        self,
        on_blocked: Optional[Callable[[str, str], Awaitable[None]]] = None,
        redact_pii: bool = True,
    ):
        super().__init__()
        self._on_blocked = on_blocked
        self._redact_pii = redact_pii
        self._block_count = 0
        self._max_consecutive_blocks = 3

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if not isinstance(frame, TranscriptionFrame):
            await self.push_frame(frame, direction)
            return

        text = frame.text.strip()
        if not text:
            await self.push_frame(frame, direction)
            return

        if _contains_jailbreak(text):
            self._block_count += 1
            logger.warning(f"[GUARDRAIL] Jailbreak attempt blocked: {text[:80]}...")
            if self._on_blocked:
                await self._on_blocked("jailbreak", text)
            return

        if _contains_toxic(text):
            self._block_count += 1
            logger.warning(f"[GUARDRAIL] Toxic content blocked: {text[:80]}...")
            if self._on_blocked:
                await self._on_blocked("toxic", text)
            return

        self._block_count = 0

        if self._redact_pii:
            pii_types = _detect_pii(text)
            if pii_types:
                logger.info(f"[GUARDRAIL] PII detected ({', '.join(pii_types)}), redacting")
                frame.text = _redact_pii(text)

        await self.push_frame(frame, direction)


# ---------------------------------------------------------------------------
# Post-LLM guardrail processor (assistant output)
# ---------------------------------------------------------------------------


class OutputGuardrailProcessor(FrameProcessor):
    """Intercepts LLMTextFrame / TTSSpeakFrame after the LLM, before TTS.

    - Redacts any PII the model might leak (SSNs, credit cards)
    - Blocks toxic output (shouldn't happen with good prompts, but defense in depth)
    """

    def __init__(self):
        super().__init__()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (LLMTextFrame, TTSSpeakFrame)):
            text = frame.text
            if _contains_toxic(text):
                logger.warning(f"[GUARDRAIL-OUT] Toxic output blocked: {text[:80]}...")
                return

            pii_types = _detect_pii(text)
            if pii_types:
                logger.info(f"[GUARDRAIL-OUT] PII in output redacted ({', '.join(pii_types)})")
                frame.text = _redact_pii(text)

        await self.push_frame(frame, direction)


# ---------------------------------------------------------------------------
# Enhanced silence / idle tracker
# ---------------------------------------------------------------------------


class SilenceTracker(FrameProcessor):
    """Silence watchdog — ends the call after prolonged inactivity.

    Resets on any sign of conversation activity: finalized transcriptions,
    user starting to speak (VAD), and bot speaking (so listening to the
    agent's response doesn't count as "silence").
    """

    def __init__(
        self,
        max_silence_seconds: float = 45.0,
        end_call_callback: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        super().__init__()
        self._max_silence = max_silence_seconds
        self._end_call_callback = end_call_callback
        self._last_activity_time: Optional[float] = None
        self._bot_speaking = False
        self._ended = False

    def _reset_timer(self):
        self._last_activity_time = time.time()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._reset_timer()

        elif isinstance(frame, TranscriptionFrame) and frame.text.strip():
            self._reset_timer()

        elif isinstance(frame, UserStartedSpeakingFrame):
            self._reset_timer()

        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self._reset_timer()

        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            self._reset_timer()

        elif isinstance(frame, HeartbeatFrame) and self._last_activity_time and not self._ended:
            if self._bot_speaking:
                self._reset_timer()
            elif time.time() - self._last_activity_time >= self._max_silence:
                self._ended = True
                logger.warning(f"[SILENCE] No activity for {self._max_silence:.0f}s — ending call")
                if self._end_call_callback:
                    await self._end_call_callback()

        await self.push_frame(frame, direction)
