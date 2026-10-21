"""
Style pattern extraction from call recordings.

Pipeline:
1. Transcribe uploaded audio via Deepgram (speaker-diarized).
2. Run a single LLM pass over the combined transcripts to distill a
   concise "agent style profile" — tone, pacing, empathy patterns,
   objection handling, closing techniques, unique phrases.

The resulting profile is a plain-text block that can be appended to
any prompt-engineering pipeline (workflow_generator, industry_crew, etc.)
so the generated agent mimics the human's conversational patterns
without rebuilding the entire workflow structure from the recordings.

This is a lightweight cousin of voice_clone_crew — it only extracts the
STYLE layer, leaving the STRUCTURE/CONTENT to the primary generator
(description / website / industry template).
"""

from __future__ import annotations

import os
from typing import Optional

from loguru import logger

from api.services.workflow.audio_transcriber import transcribe_multiple

_SECTION_HEADER = "AGENT STYLE & CONVERSATION PATTERNS (extracted from real call recordings)"

_PROFILE_SYSTEM_PROMPT = (
    "You are an expert conversation analyst who reverse-engineers exactly how a "
    "specific human agent talks on calls, so a voice AI can faithfully imitate "
    "them on the phone. You work ONLY from diarized transcripts.\n\n"
    "Hard rules:\n"
    "1. First identify which diarized speaker is the AGENT — the person "
    "representing the business who greets the caller, asks qualifying "
    "questions, and drives the call toward an outcome. Profile ONLY that "
    "speaker. Treat the other speaker(s) as the caller and ignore their style "
    "except where the agent reacts to or mirrors it.\n"
    "2. Extract ONLY patterns that actually appear in the transcripts. NEVER "
    "invent phrases, traits, or techniques. If something is not observable, "
    "say so explicitly — do not guess or pad.\n"
    "3. Prefer VERBATIM quotes over paraphrase: a real phrase the agent said is "
    "worth more than a description of it.\n"
    "4. Capture HOW they speak (tone, phrasing, structure, pacing, recovery "
    "moves) — never WHAT the business sells. Style, not content.\n"
    "5. Everything you output must be directly usable as instructions in a "
    "voice-agent prompt."
)

_PROFILE_USER_TEMPLATE = """Analyze these diarized call transcripts of a real human agent and produce a STYLE PROFILE
that captures HOW the AGENT speaks — not WHAT their business does.

TRANSCRIPTS:
{transcripts}

Step 1 (think silently): decide which diarized speaker is the AGENT vs the CALLER, using who
greets, who asks the qualifying questions, and who drives the call. Profile ONLY the agent.

Step 2: produce a plain-text profile (no markdown fences, no JSON) using these EXACT headings.
Keep the total under 650 words. Be specific and quote the agent's real words wherever possible.

Agent Identification:
<one line: which speaker label is the agent and the single clue that gave it away>

Tone & Personality:
<1-2 sentences on formality, warmth, energy, confidence, and overall pace>

Greeting Style:
<how they open calls — quote the actual opening line/pattern verbatim>

Sentence & Phrasing Style:
<typical sentence length, simple vs complex, contractions, casual vs formal register, any recurring sentence shapes>

Question-Asking Pattern:
<how they gather info — one question at a time or batched? open vs closed? do they read details back to confirm?>

Active Listening & Acknowledgement:
<verbal acknowledgements and backchannels they use: "mm-hmm", "gotcha", "makes sense", "got it" — quote the real ones>

Empathy & De-escalation Moves:
<exact phrases they use when the caller is frustrated, confused, or upset>

Objection / Pushback Handling:
<how they respond when the caller hesitates, disagrees, or pushes back — quote the move>

Handling Corrections & Changes:
<what the agent does when the caller changes their mind or corrects something mid-call — do they re-confirm the updated detail, recap the full state, stay patient? quote it if visible>

Closing / Next-Steps Style:
<how they summarize, confirm commitments/next steps, and say goodbye — quote the closing line>

Signature Phrases:
- <exact phrase 1, verbatim>
- <exact phrase 2, verbatim>
- <exact phrase 3, verbatim>

Filler Words & Verbal Tics:
<recurring fillers/tics the agent uses ("you know", "basically", "so…") — note which feel natural to mirror vs which to use sparingly>

Tempo & Delivery Notes:
<pacing, pauses/silences, where they slow down or speed up, energy shifts across the call>

Rules for this profile:
- If a section has nothing observable in the transcripts, write exactly "Not observable" — do not guess.
- Do NOT include any business facts (prices, hours, services, names) — those come from elsewhere.
- Quotes must be things the AGENT actually said in the transcripts above; never fabricate a phrase.
"""


def _truncate_transcripts(transcripts: list[str], max_total_chars: int = 18000) -> str:
    """Join transcripts, truncating per-file so the total stays under the LLM's
    comfortable context window. The analyst doesn't need every word — even a
    sample from each recording is plenty to distill the style."""
    if not transcripts:
        return ""

    per_file_budget = max(1500, max_total_chars // max(len(transcripts), 1))
    blocks: list[str] = []
    for i, t in enumerate(transcripts, 1):
        snippet = t.strip()
        if len(snippet) > per_file_budget:
            snippet = snippet[:per_file_budget] + "\n... [truncated]"
        blocks.append(f"--- Recording #{i} ---\n{snippet}")
    return "\n\n".join(blocks)


async def _call_style_llm(transcripts_block: str, user_id: Optional[int]) -> Optional[str]:
    """Single-shot LLM call that returns the free-form style profile."""
    try:
        from openai import AsyncOpenAI

        from api.db.db_client import db_client
    except ImportError as e:
        logger.error(f"[StyleExtractor] Import error: {e}")
        return None

    api_key: Optional[str] = None
    provider_name = "openai"
    model = "gpt-4.1-mini"
    base_url: Optional[str] = None

    if user_id is not None:
        try:
            user_config = await db_client.get_user_configurations(user_id)
            if user_config and user_config.llm and user_config.llm.api_key:
                api_key = user_config.llm.api_key
                provider = user_config.llm.provider
                provider_name = (
                    provider.value if hasattr(provider, "value") else str(provider)
                ) or "openai"
                if hasattr(user_config.llm, "base_url") and user_config.llm.base_url:
                    base_url = user_config.llm.base_url
        except Exception as e:
            logger.warning(f"[StyleExtractor] Could not read user config: {e}")

    if not api_key:
        api_key = (
            os.getenv("OPENAI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("GROQ_API_KEY")
        )
        if os.getenv("GROQ_API_KEY") and not os.getenv("OPENAI_API_KEY"):
            provider_name = "groq"

    if not api_key:
        logger.warning(
            "[StyleExtractor] No LLM API key available — skipping style extraction"
        )
        return None

    client_kwargs: dict = {"api_key": api_key}
    if provider_name.lower() == "groq":
        client_kwargs["base_url"] = "https://api.groq.com/openai/v1"
        model = "llama-3.3-70b-versatile"
    elif base_url:
        client_kwargs["base_url"] = base_url

    client = AsyncOpenAI(**client_kwargs)
    user_prompt = _PROFILE_USER_TEMPLATE.format(transcripts=transcripts_block)

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _PROFILE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1500,
        )
        content = response.choices[0].message.content
        if not content:
            return None
        return content.strip()
    except Exception as e:
        logger.error(f"[StyleExtractor] LLM call failed: {e}")
        return None


async def extract_style_from_recordings(
    audio_files: list[tuple[str, bytes, str]],
    user_id: Optional[int] = None,
) -> Optional[str]:
    """Transcribe recordings and produce an agent style profile.

    Args:
        audio_files: list of (filename, bytes, content_type) tuples.
        user_id: optional — used to pick up the user's LLM API key.

    Returns:
        A block of plain text wrapped with a header, ready to concatenate
        into another prompt. Returns ``None`` if nothing useful could be
        extracted (no valid transcripts, no API key, or LLM error). The
        caller should treat ``None`` as "no style context available" and
        continue without it — never fail the workflow generation just
        because style extraction didn't work.
    """
    if not audio_files:
        return None

    logger.info(
        f"[StyleExtractor] Transcribing {len(audio_files)} recording(s) for style profile"
    )
    transcripts = await transcribe_multiple(audio_files)
    valid = [t for t in transcripts if t and len(t.strip()) > 50]
    if not valid:
        logger.warning("[StyleExtractor] No usable transcripts — skipping style profile")
        return None

    logger.info(
        f"[StyleExtractor] {len(valid)}/{len(audio_files)} transcripts usable, "
        f"total {sum(len(t) for t in valid)} chars"
    )

    transcripts_block = _truncate_transcripts(valid)
    profile_body = await _call_style_llm(transcripts_block, user_id)
    if not profile_body:
        return None

    wrapped = (
        f"\n\n{_SECTION_HEADER}\n"
        f"{'=' * len(_SECTION_HEADER)}\n"
        f"{profile_body}\n"
        f"\nIMPORTANT: Mirror the tone, pacing, signature phrases, and conversation "
        f"moves above in every agent prompt you write. This is how the user wants "
        f"the voice agent to sound. Do NOT invent new signature phrases or patterns "
        f"beyond those listed above.\n"
    )
    logger.info(
        f"[StyleExtractor] Style profile ready ({len(wrapped)} chars)"
    )
    return wrapped
