from __future__ import annotations

from typing import Any, Dict, List

from loguru import logger

from api.utils.template_renderer import render_template
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.aggregators.llm_context import LLMContext

__all__ = [
    "get_function_schema",
    "update_llm_context",
    "render_template",
]

# ---------------------------------------------------------------------------
# Long-call history compaction
# ---------------------------------------------------------------------------
# On long calls the conversation history grows without bound: every LLM turn
# re-sends the whole transcript, which steadily increases latency and
# eventually degrades response quality. When the history exceeds
# _MAX_HISTORY_MESSAGES we keep the most recent _KEEP_RECENT_MESSAGES verbatim
# and compress everything older into a single compact system note (oldest
# first, per-turn truncated). Extracted variables live in the engine's
# _gathered_context and are re-injected via prompt templates, so hard facts
# collected earlier are never lost by this compaction.
_MAX_HISTORY_MESSAGES = 40
_KEEP_RECENT_MESSAGES = 24
_SUMMARY_TURN_CHAR_LIMIT = 200
_SUMMARY_BLOCK_CHAR_LIMIT = 4000

# Marker prefix identifying our compaction note so it survives the
# "strip old system messages" filter on subsequent node transitions.
_SUMMARY_MARKER = "[CALL HISTORY SUMMARY]"


def is_history_summary_message(msg: Dict[str, Any]) -> bool:
    """True when *msg* is the compaction note produced by _compact_history."""
    return (
        msg.get("role") == "system"
        and isinstance(msg.get("content"), str)
        and msg["content"].startswith(_SUMMARY_MARKER)
    )


def _compact_history(
    conversation: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compress old turns into one system note, keeping recent turns verbatim.

    A pre-existing summary note (from an earlier compaction) is merged into the
    new one so no earlier-call information is ever dropped outright.
    """
    # Pull out any prior compaction note first.
    prior_lines: List[str] = []
    cleaned: List[Dict[str, Any]] = []
    for msg in conversation:
        if is_history_summary_message(msg):
            body = msg["content"][len(_SUMMARY_MARKER):]
            prior_lines.extend(
                ln for ln in body.splitlines() if ln.strip().startswith("-")
            )
        else:
            cleaned.append(msg)
    conversation = cleaned

    if len(conversation) <= _MAX_HISTORY_MESSAGES and not prior_lines:
        return conversation

    if len(conversation) <= _MAX_HISTORY_MESSAGES:
        older: List[Dict[str, Any]] = []
        recent = conversation
    else:
        split = len(conversation) - _KEEP_RECENT_MESSAGES
        # Never split a tool-call/result pair: extend the verbatim window
        # backwards while the boundary message is a tool result.
        while split > 0 and (
            conversation[split].get("role") == "tool"
            or conversation[split].get("tool_call_id") is not None
        ):
            split -= 1
        older, recent = conversation[:split], conversation[split:]

    lines: List[str] = list(prior_lines)
    for msg in older:
        role = msg.get("role")
        content = msg.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue  # skip tool calls/results and non-text content
        text = content.strip()
        if not text:
            continue
        if len(text) > _SUMMARY_TURN_CHAR_LIMIT:
            text = text[: _SUMMARY_TURN_CHAR_LIMIT - 1].rstrip() + "…"
        lines.append(f"- {'Caller' if role == 'user' else 'Agent'}: {text}")

    # If even the compressed form is too large, drop the oldest lines first —
    # recent compressed turns are more likely to still matter.
    total = sum(len(ln) for ln in lines)
    while lines and total > _SUMMARY_BLOCK_CHAR_LIMIT:
        total -= len(lines[0])
        lines.pop(0)

    if not lines:
        return recent

    summary_message = {
        "role": "system",
        "content": (
            f"{_SUMMARY_MARKER} Earlier in this call (compacted transcript, "
            "oldest first — treat as accurate history; do not re-ask anything "
            "answered here):\n" + "\n".join(lines)
        ),
    }
    if older:
        logger.info(
            f"🧠 [CONTEXT] Compacted {len(older)} old messages into a "
            f"{total}-char summary; keeping {len(recent)} recent messages verbatim"
        )
    return [summary_message] + recent


def get_function_schema(
    function_name: str,
    description: str,
    *,
    properties: Dict[str, Any] | None = None,
    required: List[str] | None = None,
) -> FunctionSchema:
    """Create a FunctionSchema definition that can later be transformed into
    the provider-specific format (OpenAI, Gemini, etc.).

    The helper keeps the public signature backward-compatible – callers that
    only pass ``function_name`` and ``description`` continue to work and will
    define a parameter-less function.
    """

    return FunctionSchema(
        name=function_name,
        description=description,
        properties=properties or {},
        required=required or [],
    )


def update_llm_context(
    context: LLMContext,
    system_message: Dict[str, Any],
    functions: List[FunctionSchema],
    web_search_enabled: bool = False,
) -> None:
    """Update *context* with an up-to-date system message and tool list.

    This helper removes any previous system messages before inserting the new
    *system_message* at the top of the conversation history and then instructs
    the LLM which *functions* (a.k.a. tools) are currently available.
    
    Args:
        context: The LLM context to update.
        system_message: The new system message to set.
        functions: List of function schemas for tools.
        web_search_enabled: If True, adds provider-specific web search tools.
    """
    from pipecat.adapters.schemas.tools_schema import AdapterType

    custom_tools = None
    if web_search_enabled:
        custom_tools = {
            AdapterType.OPENAI: [{"type": "web_search_preview"}],
            AdapterType.GEMINI: [{"google_search": {}}],
        }
        logger.info(
            "🌐 [WEB SEARCH] Adding web search tools to LLM context - "
            "agent can now search the internet for real-time information"
        )

    # Wrap the provided function schemas in a ToolsSchema so that the adapter
    # associated with the current LLM service can convert them to the correct
    # provider-specific representation when required.
    tools_schema = ToolsSchema(standard_tools=functions, custom_tools=custom_tools)
    previous_interactions = context.messages

    # Log tools summary
    tool_count = len(functions)
    if web_search_enabled:
        logger.debug(
            f"🌐 [WEB SEARCH] LLM context updated with {tool_count} function tools + web search"
        )

    # Filter out old system messages but keep user/assistant/function content.
    # The long-call history summary note is preserved — dropping it would lose
    # everything that was compacted away on a previous transition.
    filtered: List[Dict[str, Any]] = [
        interaction
        for interaction in previous_interactions
        if interaction["role"] != "system"
        or is_history_summary_message(interaction)
    ]

    # Merge consecutive user messages so the LLM doesn't see
    # fragments like  [user: "So"] [user: "what do you need?"]
    # as separate turns — they become [user: "So what do you need?"].
    # This reduces token count and gives the model cleaner context.
    merged_history: List[Dict[str, Any]] = []
    for msg in filtered:
        if (
            merged_history
            and msg.get("role") == "user"
            and merged_history[-1].get("role") == "user"
            and isinstance(msg.get("content"), str)
            and isinstance(merged_history[-1].get("content"), str)
        ):
            merged_history[-1] = {
                "role": "user",
                "content": merged_history[-1]["content"] + " " + msg["content"],
            }
        else:
            merged_history.append(msg)

    # Long-call retention: bound the history size so per-turn latency stays
    # flat on long calls, while a compact summary preserves earlier details.
    merged_history = _compact_history(merged_history)

    context.set_messages([system_message] + merged_history)

    if functions or web_search_enabled:
        context.set_tools(tools_schema)
