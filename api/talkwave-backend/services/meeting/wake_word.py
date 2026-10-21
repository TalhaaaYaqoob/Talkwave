"""Wake word detection for meeting agents.

Scans real-time STT transcript for trigger phrases (e.g. "Hey Jarvis")
and extracts the user's query that follows the wake word.

Supports:
  - Name-based triggers with fuzzy matching for STT errors
  - Configurable cooldown to prevent double-triggers
  - Query extraction from the text following the trigger
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


@dataclass
class WakeWordMatch:
    """Result of a successful wake word detection."""
    trigger_phrase: str
    query_text: str
    speaker_id: Optional[str] = None
    timestamp: float = 0.0
    confidence: float = 1.0


class WakeWordDetector:
    """Detects wake words in streaming transcript text.

    The detector maintains a sliding window of recent transcript
    text and checks for the presence of configured trigger phrases.
    """

    COMMON_STT_VARIANTS = {
        "jarvis": ["jarvis", "jarvas", "jervis", "jarves", "javis"],
        "talkwave": ["talkwave", "talk wave", "talkwaves", "talk waves"],
        "assistant": ["assistant", "assistent", "asistant"],
        "agent": ["agent", "agnet"],
    }

    def __init__(
        self,
        wake_words: list[str],
        cooldown_seconds: float = 2.0,
        fuzzy_match: bool = True,
        query_wait_seconds: float = 0.8,
    ):
        """
        Args:
            wake_words: List of trigger phrases (e.g. ["hey jarvis", "jarvis"]).
            cooldown_seconds: Minimum seconds between consecutive triggers.
            fuzzy_match: If True, match common STT misrecognitions.
            query_wait_seconds: How long to wait for a follow-up query after
                a bare wake word (no inline query).
        """
        self.wake_words = [w.lower().strip() for w in wake_words]
        self.cooldown_seconds = cooldown_seconds
        self.fuzzy_match = fuzzy_match
        self.query_wait_seconds = query_wait_seconds
        self._last_trigger_time: float = 0.0
        self._patterns: list[re.Pattern] = self._build_patterns()
        self._pending_trigger: Optional[dict] = None

    def _build_patterns(self) -> list[re.Pattern]:
        """Build regex patterns for each wake word including fuzzy variants."""
        patterns = []
        for wake_word in self.wake_words:
            variants = [re.escape(wake_word)]

            if self.fuzzy_match:
                for base, alts in self.COMMON_STT_VARIANTS.items():
                    if base in wake_word:
                        for alt in alts:
                            variant = wake_word.replace(base, alt)
                            if variant != wake_word:
                                variants.append(re.escape(variant))

                if wake_word not in self.COMMON_STT_VARIANTS:
                    self._add_phonetic_variants(wake_word, variants)

            pattern_str = "|".join(variants)
            pattern = re.compile(
                rf"(?:^|\s)({pattern_str})(?:\s*[,.]?\s*)(.*)",
                re.IGNORECASE | re.DOTALL,
            )
            patterns.append(pattern)

        return patterns

    @staticmethod
    def _add_phonetic_variants(word: str, variants: list[str]):
        """Generate common STT misrecognition variants for a word."""
        w = word.lower()
        if len(w) < 3:
            return
        subs = [
            ("i", "ee"), ("i", "y"), ("y", "i"), ("y", "ie"),
            ("k", "c"), ("c", "k"), ("ey", "y"), ("ey", "ie"),
            ("ie", "ey"), ("ie", "y"), ("ee", "i"),
        ]
        for old_ch, new_ch in subs:
            if old_ch in w:
                v = w.replace(old_ch, new_ch, 1)
                if v != w:
                    variants.append(re.escape(v))

    def detect(
        self,
        transcript_text: str,
        speaker_id: Optional[str] = None,
        is_final: bool = True,
    ) -> Optional[WakeWordMatch]:
        """Check transcript text for a wake word trigger.

        Handles two scenarios:
          1. "Hey TalkWave, what's the agenda?" → immediate trigger with query
          2. "Hey TalkWave" [pause] "What's the agenda?" → buffered trigger,
             the next utterance becomes the query
        """
        if not is_final:
            return None

        now = time.time()
        text_lower = transcript_text.lower().strip()
        text_clean = re.sub(r"^[;,.\s]+|[;,.\s]+$", "", text_lower)
        if not text_clean:
            return None

        if self._pending_trigger:
            elapsed = now - self._pending_trigger["time"]
            same_speaker = (
                speaker_id is not None
                and speaker_id == self._pending_trigger.get("speaker_id")
            )
            if elapsed <= self.query_wait_seconds and same_speaker:
                query = text_clean
                trigger = self._pending_trigger["trigger"]
                self._pending_trigger = None
                self._last_trigger_time = now
                result = WakeWordMatch(
                    trigger_phrase=trigger,
                    query_text=query,
                    speaker_id=speaker_id,
                    timestamp=now,
                )
                logger.info(
                    f"[WakeWord] Triggered (follow-up): '{trigger}' → "
                    f"query: '{query[:80]}' (speaker={speaker_id})"
                )
                return result
            elif elapsed > self.query_wait_seconds:
                self._pending_trigger = None

        if now - self._last_trigger_time < self.cooldown_seconds:
            return None

        for pattern in self._patterns:
            match = pattern.search(text_lower)
            if match:
                trigger = match.group(1)
                query = match.group(2).strip() if match.group(2) else ""
                query = re.sub(r"^[;,.\s]+|[;,.\s]+$", "", query)

                if not query:
                    self._pending_trigger = {
                        "trigger": trigger,
                        "speaker_id": speaker_id,
                        "time": now,
                    }
                    logger.info(
                        f"[WakeWord] Wake word detected, waiting "
                        f"{self.query_wait_seconds}s for follow-up query: "
                        f"'{trigger}' (speaker={speaker_id})"
                    )
                    return None

                self._last_trigger_time = now
                result = WakeWordMatch(
                    trigger_phrase=trigger,
                    query_text=query,
                    speaker_id=speaker_id,
                    timestamp=now,
                )
                logger.info(
                    f"[WakeWord] Triggered: '{trigger}' → query: '{query[:80]}' "
                    f"(speaker={speaker_id})"
                )
                return result

        return None

    def add_wake_word(self, wake_word: str):
        """Add a new wake word at runtime."""
        normalized = wake_word.lower().strip()
        if normalized not in self.wake_words:
            self.wake_words.append(normalized)
            self._patterns = self._build_patterns()

    def remove_wake_word(self, wake_word: str):
        """Remove a wake word at runtime."""
        normalized = wake_word.lower().strip()
        if normalized in self.wake_words:
            self.wake_words.remove(normalized)
            self._patterns = self._build_patterns()
