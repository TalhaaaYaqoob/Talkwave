"""Voice-output text sanitizer for streaming TTS.

Sits between the LLM stream and the TTS engine to remove artefacts that
would otherwise be read aloud. Pipecat invokes ``filter()`` on each text
chunk produced by the sentence aggregator, so the filter has to be cheap
and must not depend on cross-chunk state beyond a single "are we inside a
``<thinking>`` block" boolean.

The design rule for this file is: **detect structural signals, never
maintain a dictionary of named entities.** We do not enumerate tool
names, model names, or verbs to look for. Every detector here keys off a
property that is intrinsically wrong for spoken text:

* Identifiers in ``snake_case`` or ``camelCase`` — humans don't speak
  them; if one appears in a TTS payload it is a leaked code symbol.
* Tag-shaped tokens (``<|...|>``, ``<think>...</think>``) — these are
  model wire-format artefacts that always indicate leakage of internal
  channels or scratchpads.
* Narrator-mode openers (``We need to``, ``Let's``, ``The user is``) —
  the first-person-plural reasoning voice that reasoning models slip
  into when the analysis channel bleeds into the final answer. We match
  the *shape* of the sentence opener, not the specific words after it.
* Punctuation pathologies (ellipses, lone periods, repeated punctuation)
  that TTS engines verbalise as "dot" or hold long pauses on.

When any structural signal fires we truncate at the start of the
offending sentence so the audible response stays clean. The hard cap on
runaway generation lives at the LLM layer (``max_completion_tokens``,
``reasoning_effort=low``) — this filter is a last line of defence.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from pydantic import BaseModel

from pipecat.utils.text.base_text_filter import BaseTextFilter


# ---------------------------------------------------------------------------
# Wire-format / scratchpad artefacts
# ---------------------------------------------------------------------------

# OpenAI "harmony" channel/role markers, e.g. ``<|channel|>analysis``,
# ``<|message|>``. Matches any ``<|...|>`` shape so we don't have to
# enumerate the role names.
_HARMONY_TOKEN_RE = re.compile(r"<\|[^|>]{0,40}(?:\|[^|>]{0,40})?\|>")

# A full ``analysis`` channel block. When the harmony envelope leaks
# entirely we want to keep only the ``final`` channel content.
_HARMONY_ANALYSIS_BLOCK_RE = re.compile(
    r"<\|channel\|>\s*analysis.*?"
    r"(?:<\|channel\|>\s*final\s*<\|message\|>|<\|end\|>|$)",
    flags=re.IGNORECASE | re.DOTALL,
)

# ``<think>...</think>``, ``<analysis>...</analysis>``, ``<scratchpad>...``.
# We match the *shape* — a tag whose name signals reasoning/scratch
# content — not a specific tag list. Any tag whose lowercase name
# contains "think", "analy", "scratch", "reason", or "reflect" qualifies.
_REASONING_TAG_NAME = r"[a-zA-Z_:.-]*?(?:think|analy|scratch|reason|reflect)[a-zA-Z_:.-]*?"
_PAIRED_REASONING_TAG_RE = re.compile(
    rf"<\s*({_REASONING_TAG_NAME})\s*>.*?<\s*/\s*\1\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
_OPEN_REASONING_TAG_RE = re.compile(
    rf"<\s*{_REASONING_TAG_NAME}\s*>", flags=re.IGNORECASE
)
_CLOSE_REASONING_TAG_RE = re.compile(
    rf"<\s*/\s*{_REASONING_TAG_NAME}\s*>", flags=re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Leaked code symbols
# ---------------------------------------------------------------------------

# Programming identifiers that no human would actually speak:
#   * snake_case:  ``task_complete``, ``send_email``, ``foo_bar_baz``
#   * camelCase:   ``taskComplete`` (two-word minimum to avoid catching
#                  legitimate words like "iPad")
# Two-segment minimum keeps the false-positive rate near zero — common
# words such as "to" / "data" / "email" do not match.
_LEAKED_IDENTIFIER_RE = re.compile(
    r"\b("
    r"[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}"
    r"|[a-z][a-z0-9]+(?:[A-Z][a-z0-9]+){1,}"
    r")\b"
)


# ---------------------------------------------------------------------------
# Narrator-voice openers
# ---------------------------------------------------------------------------

# Sentence-opener patterns that are characteristic of chain-of-thought
# narration but vanishingly rare in natural assistant replies. We match
# the *opener shape* only — we do not enumerate the action words that
# follow (e.g. "call", "invoke", "trigger"). One opener match means the
# model has slipped into talk-about-itself mode and everything from that
# point onward is dropped.
_COT_OPENER_RE = re.compile(
    r"(?:^|(?<=[\.\!\?]))\s*"
    r"(?:"
    r"(?:we|i|let'?s)\s+(?:need|should|must|will|have|are|gotta|got)\b"
    r"|the\s+user\s+(?:hasn'?t|has\s+not|is\s+not|just|seems|wants|might|will)\b"
    r"|since\s+they\s+(?:haven'?t|have\s+not|did\s+not)\b"
    r"|perhaps\s+the\s+user\b"
    r"|maybe\s+(?:we|i)\s+(?:should|need|could|might)\b"
    r"|we'?re\s+stuck\b"
    r"|but\s+we\s+(?:cannot|can'?t|must|need|should)\b"
    r")",
    flags=re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Punctuation pathologies
# ---------------------------------------------------------------------------

# Ellipses ("..." or "…") TTS engines often verbalise as "dot dot dot"
# or hold an awkwardly long pause.
_ELLIPSIS_RE = re.compile(r"\u2026|\.{2,}")
_REPEATED_PUNCT_RE = re.compile(r"([?!,;:])\1+")
# A bare period surrounded by whitespace (so not part of "U.S." or
# "1.5") — streaming TTS will read it as the word "dot".
_LONE_PERIOD_RE = re.compile(r"(?<![\w?!.])\.(?![\w?!.])")
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


def _truncate_at_sentence_containing(text: str, idx: int) -> str:
    """Truncate ``text`` at the start of the sentence containing ``idx``.

    A "sentence" here is any run of text ending in ``. ! ?`` followed by
    whitespace, or the start of the chunk. This keeps the cleaned chunk
    valid prose rather than slicing through a word.
    """
    if idx <= 0:
        return ""
    boundary = 0
    # Walk back from idx looking for the nearest sentence terminator
    # followed by whitespace. Bounded scan keeps worst-case cost linear.
    for i in range(idx - 1, -1, -1):
        if text[i] in ".!?" and (i + 1 == len(text) or text[i + 1].isspace()):
            boundary = i + 1
            break
    return text[:boundary].rstrip()


class VoiceTextFilter(BaseTextFilter):
    """Sanitize streaming LLM text for voice playback.

    The filter is deliberately stateless across chunks. The only piece of
    state we keep is whether we are currently inside an unterminated
    reasoning-tag block (e.g. ``<think>`` opened in one chunk and closed
    in the next).
    """

    class InputParams(BaseModel):
        enable: Optional[bool] = True

    def __init__(
        self,
        params: Optional["VoiceTextFilter.InputParams"] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._settings = params or VoiceTextFilter.InputParams()
        self._inside_reasoning_block: bool = False

    async def update_settings(self, settings: Mapping[str, Any]):
        for key, value in settings.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, value)

    async def filter(self, text: str) -> str:
        if not self._settings.enable or not text:
            return text

        cleaned = text

        # ---- 1. Reasoning / scratchpad tag handling ------------------
        if self._inside_reasoning_block:
            close_match = _CLOSE_REASONING_TAG_RE.search(cleaned)
            if close_match:
                self._inside_reasoning_block = False
                cleaned = cleaned[close_match.end():]
            else:
                return ""

        cleaned = _PAIRED_REASONING_TAG_RE.sub(" ", cleaned)

        open_match = _OPEN_REASONING_TAG_RE.search(cleaned)
        if open_match:
            self._inside_reasoning_block = True
            cleaned = cleaned[: open_match.start()]

        # ---- 2. Harmony wire-format leakage --------------------------
        cleaned = _HARMONY_ANALYSIS_BLOCK_RE.sub(" ", cleaned)
        cleaned = _HARMONY_TOKEN_RE.sub(" ", cleaned)

        # ---- 3. Structural leak signals (truncate at sentence) -------
        # Whichever of these matches earliest decides the cut point.
        candidates = []
        m = _COT_OPENER_RE.search(cleaned)
        if m:
            candidates.append(m.start())
        m = _LEAKED_IDENTIFIER_RE.search(cleaned)
        if m:
            candidates.append(m.start())
        if candidates:
            cleaned = _truncate_at_sentence_containing(cleaned, min(candidates))

        # ---- 4. Punctuation hygiene ---------------------------------
        cleaned = _ELLIPSIS_RE.sub(", ", cleaned)
        cleaned = _REPEATED_PUNCT_RE.sub(r"\1", cleaned)
        cleaned = _LONE_PERIOD_RE.sub(" ", cleaned)
        cleaned = _MULTISPACE_RE.sub(" ", cleaned)

        return cleaned

    async def handle_interruption(self):
        self._inside_reasoning_block = False

    async def reset_interruption(self):
        # Intentional no-op: pipecat calls this before every chunk, but
        # our cross-chunk state is the open-reasoning-block flag, which
        # must NOT be reset between chunks of the same response.
        pass
