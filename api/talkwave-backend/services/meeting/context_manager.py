"""Meeting context manager for multi-speaker, long-running meeting sessions.

Unlike phone calls (1:1, short), meetings have multiple speakers and can
last hours. This manager:
  - Tracks speakers and their contributions
  - Maintains a rolling transcript with speaker labels
  - Generates periodic summaries to keep LLM context within token limits
  - Provides relevant context when the agent is triggered
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


@dataclass
class SpeakerInfo:
    """Information about a meeting participant."""
    speaker_id: str
    display_name: str = ""
    utterance_count: int = 0
    total_words: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


@dataclass
class TranscriptEntry:
    """A single transcript entry with speaker and timing."""
    text: str
    speaker_id: str
    speaker_name: str = ""
    timestamp: float = field(default_factory=time.time)
    is_agent: bool = False
    is_final: bool = True


@dataclass
class ActionItem:
    """An action item extracted from the meeting."""
    description: str
    assignee: Optional[str] = None
    mentioned_at: float = field(default_factory=time.time)
    source_text: str = ""


class MeetingContextManager:
    """Manages conversation context for a meeting agent session.

    Maintains a rolling window of transcript entries, speaker tracking,
    and periodic summaries for efficient LLM context building.
    """

    def __init__(
        self,
        max_transcript_entries: int = 500,
        summary_interval_entries: int = 50,
        max_context_tokens: int = 4000,
    ):
        """
        Args:
            max_transcript_entries: Max entries before oldest are dropped.
            summary_interval_entries: Generate a summary every N entries.
            max_context_tokens: Approximate token limit for LLM context.
        """
        self.max_transcript_entries = max_transcript_entries
        self.summary_interval_entries = summary_interval_entries
        self.max_context_tokens = max_context_tokens

        self._transcript: list[TranscriptEntry] = []
        self._speakers: dict[str, SpeakerInfo] = {}
        self._summaries: list[str] = []
        self._action_items: list[ActionItem] = []
        self._entries_since_summary: int = 0
        self._meeting_start_time: float = time.time()
        self._topics_discussed: list[str] = []

    @property
    def transcript(self) -> list[TranscriptEntry]:
        return list(self._transcript)

    @property
    def speakers(self) -> dict[str, SpeakerInfo]:
        return dict(self._speakers)

    @property
    def action_items(self) -> list[ActionItem]:
        return list(self._action_items)

    @property
    def duration_minutes(self) -> float:
        return (time.time() - self._meeting_start_time) / 60

    def add_utterance(
        self,
        text: str,
        speaker_id: str,
        speaker_name: str = "",
        is_agent: bool = False,
        is_final: bool = True,
    ) -> TranscriptEntry:
        """Add a new utterance to the meeting transcript.

        Args:
            text: The transcribed text.
            speaker_id: Unique identifier for the speaker.
            speaker_name: Display name of the speaker.
            is_agent: True if the agent produced this utterance.
            is_final: Whether this transcript is finalized.
        """
        entry = TranscriptEntry(
            text=text,
            speaker_id=speaker_id,
            speaker_name=speaker_name or speaker_id,
            is_agent=is_agent,
            is_final=is_final,
        )

        self._transcript.append(entry)
        self._entries_since_summary += 1

        if speaker_id not in self._speakers:
            self._speakers[speaker_id] = SpeakerInfo(
                speaker_id=speaker_id,
                display_name=speaker_name or speaker_id,
            )

        speaker = self._speakers[speaker_id]
        speaker.utterance_count += 1
        speaker.total_words += len(text.split())
        speaker.last_seen = time.time()
        if speaker_name and not speaker.display_name:
            speaker.display_name = speaker_name

        if len(self._transcript) > self.max_transcript_entries:
            overflow = len(self._transcript) - self.max_transcript_entries
            self._transcript = self._transcript[overflow:]

        return entry

    def add_action_item(
        self,
        description: str,
        assignee: Optional[str] = None,
        source_text: str = "",
    ):
        """Record an action item from the meeting."""
        self._action_items.append(ActionItem(
            description=description,
            assignee=assignee,
            source_text=source_text,
        ))

    def build_llm_context(
        self,
        query: str,
        recent_entries: int = 20,
        include_summary: bool = True,
        include_speakers: bool = True,
    ) -> str:
        """Build an LLM-ready context string for responding to a query.

        Combines recent transcript, summaries, speaker info, and the
        user's query into a structured prompt context.

        Args:
            query: The user's question/request to the agent.
            recent_entries: Number of recent transcript entries to include.
            include_summary: Whether to include accumulated summaries.
            include_speakers: Whether to include speaker information.
        """
        parts: list[str] = []

        parts.append(
            f"Meeting duration: {self.duration_minutes:.0f} minutes. "
            f"{len(self._speakers)} participants."
        )

        if include_speakers and self._speakers:
            speaker_lines = []
            for sid, info in self._speakers.items():
                speaker_lines.append(
                    f"  - {info.display_name} ({info.utterance_count} utterances)"
                )
            parts.append("Participants:\n" + "\n".join(speaker_lines))

        if include_summary and self._summaries:
            parts.append(
                "Meeting summary so far:\n" + "\n".join(self._summaries[-3:])
            )

        recent = self._transcript[-recent_entries:]
        if recent:
            transcript_lines = []
            for e in recent:
                name = e.speaker_name or e.speaker_id
                prefix = "[Agent]" if e.is_agent else f"[{name}]"
                transcript_lines.append(f"{prefix}: {e.text}")
            parts.append("Recent conversation:\n" + "\n".join(transcript_lines))

        if self._action_items:
            items = [f"  - {ai.description}" for ai in self._action_items[-5:]]
            parts.append("Action items noted:\n" + "\n".join(items))

        parts.append(f"User's question: {query}")

        return "\n\n".join(parts)

    def add_summary(self, summary: str):
        """Add a periodic summary of the meeting so far."""
        self._summaries.append(summary)
        self._entries_since_summary = 0
        logger.debug(f"[MeetingContext] Summary added ({len(self._summaries)} total)")

    def should_generate_summary(self) -> bool:
        """Check if enough new entries have accumulated to warrant a summary."""
        return self._entries_since_summary >= self.summary_interval_entries

    def get_recent_text(self, max_chars: int = 200) -> str:
        """Return a short string of the most recent non-agent transcript."""
        parts: list[str] = []
        total = 0
        for entry in reversed(self._transcript):
            if entry.is_agent:
                continue
            if total + len(entry.text) > max_chars:
                break
            parts.append(entry.text)
            total += len(entry.text)
        parts.reverse()
        return " ".join(parts)

    def get_full_transcript(self) -> list[dict]:
        """Return the complete transcript as a list of dicts for storage."""
        return [
            {
                "text": e.text,
                "speaker_id": e.speaker_id,
                "speaker_name": e.speaker_name,
                "timestamp": e.timestamp,
                "is_agent": e.is_agent,
            }
            for e in self._transcript
        ]

    def get_speaker_stats(self) -> dict[str, dict]:
        """Return speaker participation statistics."""
        return {
            sid: {
                "display_name": info.display_name,
                "utterance_count": info.utterance_count,
                "total_words": info.total_words,
                "talk_time_estimate_seconds": info.total_words * 0.4,
            }
            for sid, info in self._speakers.items()
        }

    def reset(self):
        """Clear all meeting context."""
        self._transcript.clear()
        self._speakers.clear()
        self._summaries.clear()
        self._action_items.clear()
        self._entries_since_summary = 0
        self._meeting_start_time = time.time()
