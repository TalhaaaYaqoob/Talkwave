"""Post-meeting processing -- summary, action items, and transcript generation.

After a meeting session ends, this processor analyzes the full transcript
to generate structured output including:
  - Executive summary
  - Key discussion points
  - Action items with assignees
  - Decisions made
  - Follow-up suggestions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


@dataclass
class MeetingSummary:
    """Structured output from post-meeting analysis."""
    executive_summary: str = ""
    key_points: list[str] = field(default_factory=list)
    action_items: list[dict] = field(default_factory=list)
    decisions_made: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    duration_minutes: float = 0.0
    participant_count: int = 0
    speaker_stats: dict = field(default_factory=dict)


SUMMARY_SYSTEM_PROMPT = """You are a meeting analyst. Given a meeting transcript with speaker labels, produce a structured summary.

Output format (JSON):
{
  "executive_summary": "2-3 sentence overview of the meeting",
  "key_points": ["point 1", "point 2", ...],
  "action_items": [{"description": "task", "assignee": "person or null", "priority": "high/medium/low"}],
  "decisions_made": ["decision 1", "decision 2", ...],
  "follow_ups": ["suggested follow-up 1", ...]
}

Be concise. Focus on actionable information. Use participant names when available."""


class PostMeetingProcessor:
    """Processes completed meeting sessions to generate summaries and action items."""

    def __init__(self, llm_api_key: Optional[str] = None, llm_model: str = "gpt-4o"):
        self.llm_api_key = llm_api_key
        self.llm_model = llm_model

    async def process(
        self,
        transcript: list[dict],
        speaker_stats: dict,
        duration_minutes: float,
        meeting_context: Optional[str] = None,
    ) -> MeetingSummary:
        """Generate a comprehensive post-meeting summary.

        Args:
            transcript: List of transcript entries with speaker labels.
            speaker_stats: Speaker participation statistics.
            duration_minutes: Total meeting duration.
            meeting_context: Optional context about the meeting purpose.
        """
        summary = MeetingSummary(
            duration_minutes=duration_minutes,
            participant_count=len(speaker_stats),
            speaker_stats=speaker_stats,
        )

        if not transcript:
            summary.executive_summary = "No transcript available for this meeting."
            return summary

        transcript_text = self._format_transcript(transcript)

        if self.llm_api_key:
            try:
                llm_summary = await self._generate_llm_summary(
                    transcript_text, meeting_context
                )
                summary.executive_summary = llm_summary.get("executive_summary", "")
                summary.key_points = llm_summary.get("key_points", [])
                summary.action_items = llm_summary.get("action_items", [])
                summary.decisions_made = llm_summary.get("decisions_made", [])
                summary.follow_ups = llm_summary.get("follow_ups", [])
                return summary
            except Exception as e:
                logger.error(f"[PostMeeting] LLM summary failed: {e}")

        summary.executive_summary = self._generate_basic_summary(
            transcript, speaker_stats, duration_minutes
        )
        return summary

    def _format_transcript(self, transcript: list[dict], max_chars: int = 30000) -> str:
        """Format transcript entries into a readable string, truncated if needed."""
        lines = []
        total = 0
        for entry in transcript:
            name = entry.get("speaker_name", entry.get("speaker_id", "Unknown"))
            prefix = "[Agent]" if entry.get("is_agent") else f"[{name}]"
            line = f"{prefix}: {entry['text']}"
            total += len(line)
            if total > max_chars:
                lines.append("... [transcript truncated for length] ...")
                break
            lines.append(line)
        return "\n".join(lines)

    async def _generate_llm_summary(
        self, transcript_text: str, meeting_context: Optional[str]
    ) -> dict:
        """Use an LLM to generate a structured meeting summary."""
        import json
        import httpx

        user_prompt = f"Meeting transcript:\n\n{transcript_text}"
        if meeting_context:
            user_prompt = f"Meeting context: {meeting_context}\n\n{user_prompt}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.llm_api_key}"},
                json={
                    "model": self.llm_model,
                    "messages": [
                        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.3,
                    "max_tokens": 2000,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)

    def _generate_basic_summary(
        self,
        transcript: list[dict],
        speaker_stats: dict,
        duration_minutes: float,
    ) -> str:
        """Generate a basic summary without LLM (fallback)."""
        speaker_names = [
            s.get("display_name", sid)
            for sid, s in speaker_stats.items()
        ]
        total_utterances = sum(s.get("utterance_count", 0) for s in speaker_stats.values())

        return (
            f"Meeting lasted {duration_minutes:.0f} minutes with "
            f"{len(speaker_names)} participants ({', '.join(speaker_names[:5])}). "
            f"Total of {total_utterances} utterances recorded. "
            f"Full transcript with speaker labels is available for review."
        )

    def format_summary_markdown(self, summary: MeetingSummary) -> str:
        """Format a MeetingSummary as markdown for display."""
        parts = [f"# Meeting Summary\n"]
        parts.append(f"**Duration:** {summary.duration_minutes:.0f} minutes")
        parts.append(f"**Participants:** {summary.participant_count}\n")

        if summary.executive_summary:
            parts.append(f"## Overview\n{summary.executive_summary}\n")

        if summary.key_points:
            parts.append("## Key Points")
            for point in summary.key_points:
                parts.append(f"- {point}")
            parts.append("")

        if summary.action_items:
            parts.append("## Action Items")
            for item in summary.action_items:
                assignee = item.get("assignee", "Unassigned")
                priority = item.get("priority", "medium")
                parts.append(f"- [{priority.upper()}] {item['description']} → {assignee}")
            parts.append("")

        if summary.decisions_made:
            parts.append("## Decisions Made")
            for d in summary.decisions_made:
                parts.append(f"- {d}")
            parts.append("")

        if summary.follow_ups:
            parts.append("## Follow-ups")
            for f in summary.follow_ups:
                parts.append(f"- {f}")

        return "\n".join(parts)
