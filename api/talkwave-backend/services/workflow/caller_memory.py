"""
Caller Memory — the agent remembers every caller.

When the same phone number calls (inbound) or is called (outbound) a workflow
that has `caller_memory_enabled` turned on, we look up the last few completed
calls from that number and surface a compact context string that can be used
as a template variable in any prompt:

    "Hi {{caller_name}}! I see you called last Tuesday about reservations —
    did Saturday at 7pm work out?"

Design goals:
  - Zero per-call LLM cost. We use deterministic extraction from the transcript
    and gathered_context. An optional LLM summary can be generated once at
    call-end (separate post-call task) and stored in gathered_context.call_summary
    so subsequent calls read the pre-computed summary for free.
  - Scoped to (workflow_id, organization_id). No cross-tenant memory leaks.
  - Bounded output size (≤1200 chars) so it can't blow up the LLM context.
  - Silent failure. If anything goes wrong, we return an empty string — the
    call continues normally without memory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

MAX_CALLS_IN_MEMORY = 3
MAX_MEMORY_CHARS = 1200
MAX_SUMMARY_SNIPPET_CHARS = 280


def _format_relative_time(dt: Optional[datetime]) -> str:
    """Human-friendly relative time, e.g. 'yesterday', '3 days ago'."""
    if not dt:
        return "previously"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} minute(s) ago"
    if seconds < 86400:
        return f"{seconds // 3600} hour(s) ago"
    days = seconds // 86400
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        return f"{days // 7} week(s) ago"
    if days < 365:
        return f"{days // 30} month(s) ago"
    return f"{days // 365} year(s) ago"


def _extract_last_user_utterance(gathered_context: dict) -> str:
    """Pull a short snippet of what the caller last said."""
    messages = gathered_context.get("transcript_messages") or []
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).lower()
        content = msg.get("content") or ""
        if role in ("user", "caller", "customer") and content.strip():
            snippet = content.strip()
            if len(snippet) > MAX_SUMMARY_SNIPPET_CHARS:
                snippet = snippet[: MAX_SUMMARY_SNIPPET_CHARS - 3] + "..."
            return snippet
    return ""


def _describe_run(run: Any) -> str:
    """Render a single prior call into a compact bullet line."""
    gc = getattr(run, "gathered_context", None) or {}
    usage = getattr(run, "usage_info", None) or {}
    created = getattr(run, "created_at", None)

    when = _format_relative_time(created)
    disposition = gc.get("mapped_call_disposition") or gc.get("call_disposition") or "unknown outcome"
    duration = usage.get("call_duration_seconds") or 0
    duration_str = f"{int(duration)}s" if duration else "?s"

    # Prefer a pre-computed summary if the post-call summarizer has populated
    # it; otherwise fall back to the caller's last utterance (deterministic,
    # zero LLM cost).
    pre_computed = gc.get("call_summary")
    if pre_computed and isinstance(pre_computed, str):
        snippet = pre_computed.strip()[:MAX_SUMMARY_SNIPPET_CHARS]
    else:
        snippet = _extract_last_user_utterance(gc)

    line = f"- {when} | outcome: {disposition} | duration: {duration_str}"
    if snippet:
        line += f' | they said: "{snippet}"'
    return line


def format_caller_memory(runs: list[Any]) -> str:
    """
    Turn a list of prior WorkflowRun rows into a compact memory block
    suitable for injection into an agent prompt as {{caller_history}}.
    Returns an empty string if there's nothing useful to show.
    """
    if not runs:
        return ""

    lines = ["Prior calls from this number (most recent first):"]
    used = len(lines[0])
    for run in runs:
        try:
            desc = _describe_run(run)
        except Exception as e:
            logger.debug(f"[CallerMemory] Failed to describe run: {e}")
            continue
        if not desc:
            continue
        if used + len(desc) + 1 > MAX_MEMORY_CHARS:
            break
        lines.append(desc)
        used += len(desc) + 1

    if len(lines) == 1:
        return ""

    lines.append(
        "Acknowledge this context naturally if relevant, but do NOT re-confirm "
        "facts the caller has already given — use them to personalize."
    )
    return "\n".join(lines)


async def build_caller_history_context(
    db_client: Any,
    phone_number: Optional[str],
    workflow_id: int,
    organization_id: Optional[int],
    current_run_id: Optional[int] = None,
) -> str:
    """
    Main entry point. Fetches recent calls for this number and formats them
    into a string ready to drop into a prompt as a template variable.

    Safe to call unconditionally — returns "" when there's no useful memory
    or when anything fails.
    """
    if not phone_number or not workflow_id:
        return ""

    try:
        runs = await db_client.get_runs_by_phone_number(
            phone_number=phone_number,
            workflow_id=workflow_id,
            organization_id=organization_id,
            limit=MAX_CALLS_IN_MEMORY,
            exclude_run_id=current_run_id,
        )
    except Exception as e:
        logger.warning(
            f"[CallerMemory] DB lookup failed for phone {phone_number[:4]}*** "
            f"workflow {workflow_id}: {e}"
        )
        return ""

    if not runs:
        return ""

    memory = format_caller_memory(runs)
    if memory:
        logger.info(
            f"[CallerMemory] Loaded {len(runs)} prior call(s) for workflow "
            f"{workflow_id} ({len(memory)} chars)"
        )
    return memory
