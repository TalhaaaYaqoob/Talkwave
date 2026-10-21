"""
Self-improving agent analysis crew.

Uses 4 sequential CrewAI agents to analyze recent call transcripts and
generate actionable improvement suggestions for a workflow:
  1. Failure Detector       — Identifies problematic calls and categorizes issues       (temp 0.15)
  2. Coverage Gap Analyst   — Spots topics/intents the current node set fails to cover  (temp 0.2)
  3. Pattern Analyst        — Clusters failures + gaps into prioritized patterns        (temp 0.2)
  4. Improvement Architect  — Generates concrete fixes (prompt rewrites, new nodes,
                              new exit conditions, edge tweaks, or full new workflows)  (temp 0.35)

The architect can emit a `spawn_workflow` suggestion when a coverage gap is too
large to fit as a single node (e.g. an entire separate use case surfaced on
calls). This becomes a brand-new workflow on the user's dashboard.

Memory / cost efficiency:
  - Pre-screens calls with deterministic heuristics BEFORE spending any tokens;
    only suspicious calls are sent to the Failure Detector. The Gap Analyst
    sees a wider sample (including healthy calls) because gaps often hide
    inside otherwise-successful conversations.
  - If every call looks healthy AND nothing suggests a gap, we skip the crew.
  - Transcripts are compressed to ~2KB with head+tail sampling.
  - Past suggestions are de-duplicated so the user never sees the same
    rewrite they already dismissed.
  - The crew runs with `memory=False` to stay deterministic and light.
"""

import json
import re
from typing import Optional

from loguru import logger

MAX_TRANSCRIPT_CHARS = 2000
MAX_CALLS_PER_ANALYSIS = 20
# If fewer than this fraction of calls look problematic, still run but flag
# the analysis as low-signal. If zero calls are suspicious, skip entirely.
MIN_SUSPICIOUS_FRACTION_TO_RUN = 0.0  # any suspicious call runs the crew

# Minimum edit-distance-style similarity to treat two suggestions as duplicates.
_DUP_SIMILARITY_PREFIX = 120  # chars compared for dedup


def _compress_transcript(transcript_text: str) -> str:
    """Compress a full transcript to keep only the most analytically useful parts."""
    if not transcript_text or len(transcript_text) <= MAX_TRANSCRIPT_CHARS:
        return transcript_text or ""

    head = transcript_text[:1200]
    tail = transcript_text[-600:]
    return f"{head}\n... [middle truncated] ...\n{tail}"


def _score_suspicion(run) -> tuple[int, list[str]]:
    """
    Deterministic heuristic score for how likely a call had issues.
    Higher score = more suspicious. Returns (score, reasons[]).

    We run this locally (no LLM) so we only spend tokens on calls worth analyzing.
    """
    gc = run.gathered_context or {}
    usage = run.usage_info or {}

    disposition = (gc.get("mapped_call_disposition") or gc.get("call_disposition") or "").upper()
    duration = usage.get("call_duration_seconds") or 0
    transcript = gc.get("transcript_text") or ""
    has_user_speech = bool(re.search(r"(?:^|\n)\s*user\s*:", transcript, re.IGNORECASE))

    score = 0
    reasons: list[str] = []

    # 1. Disposition hints
    if disposition and disposition not in ("SUCCESS", "COMPLETED", "BOOKED", "TRANSFERRED", "RESOLVED"):
        score += 2
        reasons.append(f"non-success disposition ({disposition})")

    # 2. Premature hangup
    if duration and duration < 15:
        score += 3
        reasons.append(f"very short call ({duration}s)")
    elif duration and duration < 30:
        score += 1
        reasons.append(f"short call ({duration}s)")

    # 3. No user speech = the caller never really engaged
    if transcript and not has_user_speech:
        score += 2
        reasons.append("no user speech detected")

    # 4. Very long calls without a success disposition → likely a loop
    if duration and duration > 300 and disposition and disposition not in ("SUCCESS", "COMPLETED"):
        score += 1
        reasons.append(f"long call without success ({duration}s)")

    # 5. Frustration keywords in transcript
    if transcript:
        lower = transcript.lower()
        for kw in ("repeat yourself", "already told you", "not listening", "stop repeating", "human please", "speak to a human", "this is frustrating"):
            if kw in lower:
                score += 2
                reasons.append(f"frustration keyword ('{kw}')")
                break

    # 6. Call tags that indicate issues (if present)
    tags = gc.get("call_tags") or {}
    if isinstance(tags, dict):
        if tags.get("loop_detected"):
            score += 3
            reasons.append("tagged: loop_detected")
        if tags.get("hallucination_detected"):
            score += 3
            reasons.append("tagged: hallucination_detected")
        if tags.get("unanswered_question"):
            score += 2
            reasons.append("tagged: unanswered_question")

    return score, reasons


def _extract_call_summary(run) -> dict:
    """Extract a lightweight analysis-ready summary from a workflow run."""
    gc = run.gathered_context or {}
    usage = run.usage_info or {}

    transcript = gc.get("transcript_text", "")
    disposition = gc.get("mapped_call_disposition", gc.get("call_disposition", "UNKNOWN"))
    duration = usage.get("call_duration_seconds", 0)
    tags = gc.get("call_tags", {})

    has_user_speech = bool(re.search(r"(?:^|\n)\s*user\s*:", transcript, re.IGNORECASE))

    score, reasons = _score_suspicion(run)

    return {
        "run_id": run.id,
        "disposition": disposition,
        "duration_seconds": duration,
        "has_user_speech": has_user_speech,
        "tags": tags,
        "suspicion_score": score,
        "suspicion_reasons": reasons,
        "transcript_compressed": _compress_transcript(transcript),
    }


def _parse_json_from_output(text: str) -> dict:
    """Extract JSON from CrewAI task output. Robust to markdown fences and trailing commas."""
    if not text:
        raise ValueError("Empty LLM output")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start >= 0 and end > start:
        cleaned = cleaned[start:end]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    repaired = re.sub(r",\s*([\]}])", r"\1", cleaned)
    return json.loads(repaired)


def _suggestion_dedupe_key(s: dict) -> tuple[str, str, str]:
    """Identity key for a suggestion. Different fields matter for different types:
      - rewrite_prompt   → (target_node_id, prefix of new prompt)
      - add_exit_condition → (target_node_id, new exit name)
      - add_node         → (source_node_id, new node name)
      - adjust_edge      → (from_source + to_target, new condition)
      - spawn_workflow   → ('', spawn name lowercased)
    Falls back to description for any unknown shape.
    """
    s_type = (s.get("type") or "").lower()

    if s_type == "rewrite_prompt":
        return (
            s_type,
            s.get("target_node_id") or "",
            ((s.get("after") or s.get("description") or "").strip())[:_DUP_SIMILARITY_PREFIX].lower(),
        )

    if s_type == "add_exit_condition":
        new_exit = s.get("new_exit_condition") or {}
        return (s_type, s.get("target_node_id") or "", (new_exit.get("name") or "").strip().lower())

    if s_type == "add_node":
        new_node = s.get("new_node") or {}
        return (
            s_type,
            (new_node.get("source_node_id") or "").strip(),
            (new_node.get("name") or "").strip().lower(),
        )

    if s_type == "adjust_edge":
        change = s.get("edge_change") or {}
        return (
            s_type,
            f"{(change.get('from_source') or '')}->{(change.get('to_target') or '')}",
            (change.get("new_condition") or "").strip().lower(),
        )

    if s_type == "spawn_workflow":
        spawn = s.get("spawn") or {}
        return (s_type, "", (spawn.get("name") or "").strip().lower())

    # Unknown / legacy shape
    return (
        s_type,
        s.get("target_node_id") or "",
        ((s.get("after") or s.get("description") or "").strip())[:_DUP_SIMILARITY_PREFIX].lower(),
    )


def _dedupe_suggestions(
    new_suggestions: list[dict],
    past_suggestions: list[dict],
) -> list[dict]:
    """Drop suggestions that are effectively identical to ones we already proposed.
    Identity comparison is type-aware (see `_suggestion_dedupe_key`)."""
    if not past_suggestions:
        return new_suggestions

    seen_keys: set[tuple[str, str, str]] = {
        _suggestion_dedupe_key(prev) for prev in past_suggestions
    }

    unique: list[dict] = []
    dropped = 0
    for s in new_suggestions:
        key = _suggestion_dedupe_key(s)
        if key in seen_keys:
            dropped += 1
            continue
        unique.append(s)
        seen_keys.add(key)

    if dropped:
        logger.info(f"[SelfImprove] De-duplicated {dropped} suggestions against past improvements")
    return unique


def _build_improvement_crew(
    workflow_name: str,
    workflow_definition: dict,
    call_summaries: list[dict],
    gap_scan_summaries: list[dict],
    aggregate_stats: dict,
):
    """Build the 4-agent improvement crew.

    Args:
        call_summaries: suspicious calls fed to the Failure Detector.
        gap_scan_summaries: broader sample (suspicious + healthy) fed to the
            Coverage Gap Analyst. Often a superset of `call_summaries`.
    """
    from crewai import Agent, Crew, Process, Task

    from api.services.workflow.industry_crew import _build_llm

    # Each role gets a tuned temperature — failure detection / gap analysis /
    # pattern analysis should be precise; improvement generation can be a
    # little more creative.
    detector_llm = _build_llm(temperature=0.15, max_tokens=2048)
    gap_llm = _build_llm(temperature=0.2, max_tokens=2048)
    analyst_llm = _build_llm(temperature=0.2, max_tokens=2048)
    architect_llm = _build_llm(temperature=0.35, max_tokens=3500)

    nodes_summary = []
    valid_node_ids: list[str] = []
    for node in workflow_definition.get("nodes", []):
        data = node.get("data", {})
        prompt_preview = (data.get("prompt") or "")[:200]
        exit_names = [ec.get("name", "") for ec in data.get("exit_conditions", [])]
        valid_node_ids.append(node["id"])
        nodes_summary.append(
            f"- {node['id']} ({node.get('type', '?')}): \"{data.get('name', '')}\" "
            f"| exits: {exit_names} | prompt preview: \"{prompt_preview}...\""
        )
    nodes_text = "\n".join(nodes_summary) or "No nodes found"
    valid_node_ids_text = ", ".join(valid_node_ids) or "(none)"

    def _format_block(items: list[dict]) -> str:
        parts: list[str] = []
        for s in items:
            reasons = ", ".join(s.get("suspicion_reasons", [])) or "n/a"
            parts.append(
                f"\n--- Call #{s['run_id']} | disposition={s['disposition']} | "
                f"duration={s['duration_seconds']}s | suspicion_score={s.get('suspicion_score', 0)} "
                f"| flags=[{reasons}] ---\n{s['transcript_compressed']}\n"
            )
        return "".join(parts)

    transcripts_block = _format_block(call_summaries)
    gap_transcripts_block = _format_block(gap_scan_summaries)

    stats_text = json.dumps(aggregate_stats, indent=2)

    failure_detector = Agent(
        role="Voice Agent Call Failure Analyst",
        goal=(
            "Identify calls where the voice agent failed, underperformed, or left the "
            "caller unsatisfied. Categorize each failure precisely. Use the suspicion_score "
            "hints to focus attention but form your own judgment from the transcript."
        ),
        backstory=(
            "You are an expert at reviewing voice call transcripts for quality issues. "
            "You catch when agents hallucinate info not in the prompt, fail to answer "
            "questions, go in conversational loops, sound robotic, or cause callers to "
            "hang up frustrated. You never miss a subtle failure."
        ),
        llm=detector_llm,
        verbose=False,
        allow_delegation=False,
        max_iter=4,
    )

    coverage_gap_analyst = Agent(
        role="Voice Workflow Coverage Gap Analyst",
        goal=(
            "Find topics, intents, and side-questions that callers bring up which the "
            "current workflow has NO node or exit condition designed to handle. These "
            "are 'capability gaps' — not bugs in existing nodes, but missing capabilities. "
            "Look across BOTH successful and unsuccessful calls, because gaps often hide "
            "inside calls that 'completed' but where the agent silently sidestepped a "
            "user question."
        ),
        backstory=(
            "You are a product manager-style analyst. You compare what callers actually "
            "ask for against the existing workflow node set. When you see callers "
            "repeatedly asking about a topic (e.g. catering, refunds, dietary needs, "
            "after-hours support) that has no dedicated node or exit condition, you "
            "flag it as a coverage gap. You think in two scopes: small gaps that fit "
            "as one new agent node wired into the existing flow, and large gaps that "
            "deserve an entirely separate workflow (a whole new agent on the dashboard)."
        ),
        llm=gap_llm,
        verbose=False,
        allow_delegation=False,
        max_iter=4,
    )

    pattern_analyst = Agent(
        role="Voice Agent Failure & Gap Pattern Analyst",
        goal=(
            "Cluster individual call failures AND coverage gaps into recurring "
            "patterns with statistics and root cause analysis. Only report a pattern "
            "if it affects 2+ calls OR the single instance is critical (hangup, "
            "compliance violation, or a coverage gap with severity=high)."
        ),
        backstory=(
            "You analyze failure and gap data across many calls to find systematic "
            "issues — not one-off problems but patterns that indicate a workflow design "
            "flaw or a missing capability. You think in terms of percentages, root "
            "causes, and impact severity. You preserve the original gap_id / failure_id "
            "evidence so the next stage can act on it."
        ),
        llm=analyst_llm,
        verbose=False,
        allow_delegation=False,
        max_iter=4,
    )

    improvement_architect = Agent(
        role="Voice Workflow Improvement Architect",
        goal=(
            "For each identified pattern, generate a specific, actionable improvement. "
            "Choose the RIGHT fix type for the root cause: prompt rewrites for tone/info "
            "problems inside an existing node, new exit conditions for missing routing, "
            "new agent nodes (auto-wired into the existing flow) for in-workflow gaps, "
            "and entirely new workflows (`spawn_workflow`) for whole side-use-cases. "
            "Do NOT paper over a missing capability with a prompt rewrite."
        ),
        backstory=(
            "You design fixes for voice agent workflows. You know the node types "
            "(startCall, agentNode, endCall, globalNode), exit conditions, and edge "
            "routing. When you rewrite a prompt, it sounds natural when spoken aloud. "
            "You never invent business details — you only work with what exists in "
            "the current workflow or has direct evidence in the call transcripts. "
            "Your confidence scores are calibrated: 0.9+ means clearly correct; "
            "0.6-0.9 means likely helpful; below 0.6 means speculative."
        ),
        llm=architect_llm,
        verbose=False,
        allow_delegation=False,
        max_iter=4,
    )

    task_detect = Task(
        description=f"""Analyze these recent call transcripts for the workflow "{workflow_name}" and identify all failures.

AGGREGATE STATS (from SQL, covers all recent calls):
{stats_text}

CURRENT WORKFLOW NODES:
{nodes_text}

RECENT CALL TRANSCRIPTS (pre-filtered to suspicious ones):
{transcripts_block}

For each problematic call, identify:
- Which call (run_id)
- Failure category: "unanswered_question", "hallucination", "conversation_loop", "premature_hangup", "caller_frustration", "wrong_routing", "missing_info", "robotic_tone", "other"
- What specifically went wrong
- Which node was involved (if identifiable — match the node from CURRENT WORKFLOW NODES)

Return ONLY valid JSON. No markdown.
{{
    "failures": [
        {{
            "run_id": 123,
            "category": "unanswered_question",
            "description": "Caller asked about gluten-free options but agent had no info",
            "node_id": "node-menu",
            "severity": "high"
        }}
    ],
    "total_calls_reviewed": {len(call_summaries)},
    "calls_with_issues": 0
}}""",
        expected_output="JSON with a failures array listing each detected issue.",
        agent=failure_detector,
    )

    task_gaps = Task(
        description=f"""Scan call transcripts for CAPABILITY GAPS in the workflow "{workflow_name}".

A "capability gap" is a topic, intent, or side-question that callers repeatedly
bring up but for which the current workflow has NO dedicated node or matching
exit condition. Gaps appear in BOTH successful and unsuccessful calls — sometimes
the agent papers over them with vague answers, sometimes it just ignores them.

CURRENT WORKFLOW NODES (this is the entire capability set today):
{nodes_text}

AGGREGATE STATS:
{stats_text}

CALL TRANSCRIPTS (broader sample, includes healthy calls):
{gap_transcripts_block}

Decide a suggested scope for each gap:
- "in_workflow_node": the gap fits as a single new agent node inside this workflow
  (e.g. "dietary restrictions" wired off the existing menu node).
- "new_workflow": the gap is a whole separate use case the user would treat as a
  distinct agent on the dashboard (e.g. callers keep asking about "catering quotes"
  for a dine-in-only workflow, or "tech support" for a sales-only workflow).

Rules:
- Only report a gap with 2+ separate call occurrences, OR a single occurrence
  where the missing capability is clearly safety/compliance critical.
- "current_handling" must be one of: "ignored", "deflected", "hallucinated", "partial".
- "evidence_run_ids" must list the actual run_ids from the transcripts above.
- DO NOT invent topics not present in the transcripts.

Return ONLY valid JSON. No markdown.
{{
    "gaps": [
        {{
            "id": "gap-1",
            "topic": "Catering quotes for events",
            "description": "Callers ask about catering for parties but the workflow only handles dine-in reservations",
            "evidence_run_ids": [123, 145],
            "occurrences": 4,
            "current_handling": "deflected",
            "severity": "high",
            "suggested_scope": "new_workflow",
            "related_existing_node_id": "node-menu"
        }}
    ]
}}""",
        expected_output="JSON with a gaps array of capability gaps and their suggested scope.",
        agent=coverage_gap_analyst,
    )

    task_patterns = Task(
        description=f"""Using the failure analysis AND the coverage gaps from the previous two tasks, cluster everything into recurring patterns.

AGGREGATE STATS:
{stats_text}

For each pattern, calculate:
- How many calls are affected (count and percentage)
- Source: "failure" (an existing node misbehaves) or "gap" (a missing capability) or "mixed"
- Root cause (workflow design issue or missing capability)
- Impact: "critical" (causes hangups/frustration/compliance), "high" (degrades experience), "medium" (minor quality issue)
- For "gap" patterns: copy the gap's `suggested_scope` and `evidence_run_ids` forward so the architect can act on it.

Only emit patterns that affect 2+ calls OR are critical compliance/hangup issues OR are gaps with severity=high.

Return ONLY valid JSON. No markdown.
{{
    "patterns": [
        {{
            "id": "pattern-1",
            "name": "Missing catering capability",
            "description": "Callers ask about catering but workflow only handles dine-in",
            "source": "gap",
            "affected_calls": 4,
            "affected_percentage": 27,
            "root_cause": "No node or workflow handles catering inquiries",
            "impact": "high",
            "related_node_ids": ["node-menu"],
            "failure_categories": [],
            "suggested_scope": "new_workflow",
            "evidence_run_ids": [123, 145]
        }}
    ]
}}""",
        expected_output="JSON with a patterns array of clustered, prioritized issues spanning failures and gaps.",
        agent=pattern_analyst,
    )

    task_improve = Task(
        description=f"""For each pattern from the previous task, generate a specific fix for the workflow "{workflow_name}".

CURRENT WORKFLOW NODES:
{nodes_text}

VALID source_node_id VALUES (any add_node MUST wire off one of these):
{valid_node_ids_text}

Fix types:
1. "rewrite_prompt"       — rewrite an existing node's prompt to handle a TONE or INFO problem
                            inside that node. Do NOT use this to fix a missing capability.
2. "add_exit_condition"   — add a new exit condition to route callers correctly.
3. "add_node"             — add a new agentNode INSIDE the current workflow, wired off
                            an existing node. Use this for in-workflow gaps.
4. "adjust_edge"          — change edge routing.
5. "spawn_workflow"       — create an ENTIRELY NEW top-level workflow for a side use case.
                            Use this ONLY when the pattern's suggested_scope == "new_workflow"
                            AND it has 3+ evidence_run_ids.

HARD RULES (a violation = your suggestion will be silently dropped):
- If a pattern has `source == "gap"` you MUST emit "add_node" or "spawn_workflow" —
  NEVER paper over a missing capability with "rewrite_prompt".
- Every "add_node" suggestion MUST populate `new_node.source_node_id` (one of
  the VALID values above) AND `new_node.trigger_condition` (the exit-condition
  name on the source node that routes the caller into the new node). The exit
  condition can be one that already exists OR a new one — if new, also add the
  matching "add_exit_condition" suggestion on the same source_node_id.
- Every "spawn_workflow" suggestion MUST include `evidence_run_ids` (>=3 entries).
- NEVER invent business details not present in the transcripts or current workflow.
- Prompts must sound natural spoken aloud.
- Confidence: 0.9+ = clearly correct; 0.6-0.9 = likely helpful; <0.6 = speculative.

Field shapes:
- rewrite_prompt:    {{"target_node_id": "...", "before": "...", "after": "..."}}
- add_exit_condition:{{"target_node_id": "...", "new_exit_condition": {{"name": "...", "llm_description": "..."}}}}
- add_node:          {{"new_node": {{"type": "agentNode", "name": "...", "prompt": "...",
                          "source_node_id": "...", "trigger_condition": "...",
                          "exit_conditions": [{{"name": "...", "llm_description": "..."}}, ...]}}}}
- adjust_edge:       {{"edge_change": {{"from_source": "...", "to_target": "...", "new_condition": "..."}}}}
- spawn_workflow:    {{"spawn": {{"name": "Catering Inquiries", "initial_prompt": "<full agent prompt>",
                          "call_type": "INBOUND|OUTBOUND|WEBSITE",
                          "use_case": "<one-line summary>"}},
                       "evidence_run_ids": [123, 145, ...]}}

Return ONLY valid JSON. No markdown.
{{
    "suggestions": [
        {{
            "type": "spawn_workflow",
            "pattern_id": "pattern-1",
            "description": "Create a dedicated Catering Inquiries agent",
            "spawn": {{
                "name": "Catering Inquiries",
                "call_type": "INBOUND",
                "use_case": "Handle catering quote requests for events",
                "initial_prompt": "You are a catering specialist. Greet the caller, ask about event date, headcount, dietary needs, and preferred menu style, then offer to send a quote."
            }},
            "evidence_run_ids": [123, 145, 156, 161],
            "confidence": 0.78,
            "reason": "27% of callers ask about catering — out of scope for current dine-in workflow"
        }}
    ],
    "summary": "Found 3 patterns across 15 calls. 1 new workflow + 2 in-workflow fixes suggested."
}}""",
        expected_output="JSON with suggestions array and a human-readable summary.",
        agent=improvement_architect,
    )

    crew = Crew(
        agents=[failure_detector, coverage_gap_analyst, pattern_analyst, improvement_architect],
        tasks=[task_detect, task_gaps, task_patterns, task_improve],
        process=Process.sequential,
        verbose=False,
        memory=False,
    )

    return crew


# Cap on the broader sample the Coverage Gap Analyst sees (includes healthy
# calls). Bigger than MAX_CALLS_PER_ANALYSIS so the gap analyst has the widest
# possible signal without blowing the context window.
MAX_CALLS_FOR_GAP_SCAN = 20

# Minimum evidence for a spawn_workflow suggestion to be accepted. The architect
# is told this in the prompt; we also enforce it post-hoc.
MIN_EVIDENCE_FOR_NEW_WORKFLOW = 3


def _validate_and_clean_suggestions(
    suggestions: list[dict],
    valid_node_ids: set[str],
) -> list[dict]:
    """Drop suggestions the architect built incorrectly.

    The architect prompt enforces this in language; we enforce it in code so
    a malformed LLM response can never produce an orphan node or a wildly
    speculative new workflow.
    """
    cleaned: list[dict] = []
    dropped = 0
    for s in suggestions:
        if not isinstance(s, dict):
            dropped += 1
            continue
        s_type = s.get("type")

        if s_type == "add_node":
            new_node = s.get("new_node") or {}
            source = new_node.get("source_node_id")
            trigger = (new_node.get("trigger_condition") or "").strip()
            if not source or source not in valid_node_ids or not trigger or not new_node.get("name") or not new_node.get("prompt"):
                logger.warning(
                    f"[SelfImprove] Dropping add_node suggestion (missing/invalid wiring): "
                    f"source={source!r}, trigger={trigger!r}"
                )
                dropped += 1
                continue

        elif s_type == "spawn_workflow":
            spawn = s.get("spawn") or {}
            evidence = s.get("evidence_run_ids") or []
            if (
                not spawn.get("name")
                or not spawn.get("initial_prompt")
                or len(evidence) < MIN_EVIDENCE_FOR_NEW_WORKFLOW
            ):
                logger.warning(
                    f"[SelfImprove] Dropping spawn_workflow suggestion (insufficient evidence "
                    f"or missing fields): name={spawn.get('name')!r}, evidence={len(evidence)}"
                )
                dropped += 1
                continue

        elif s_type in ("rewrite_prompt", "add_exit_condition"):
            target = s.get("target_node_id")
            if not target or target not in valid_node_ids:
                logger.warning(
                    f"[SelfImprove] Dropping {s_type} suggestion (unknown target_node_id={target!r})"
                )
                dropped += 1
                continue

        cleaned.append(s)

    if dropped:
        logger.info(f"[SelfImprove] Validation dropped {dropped} malformed suggestion(s)")
    return cleaned


async def run_improvement_analysis(
    workflow_id: int,
    organization_id: int,
    workflow_name: str,
    workflow_definition: dict,
    runs: list,
    aggregate_stats: dict,
    past_suggestions: Optional[list[dict]] = None,
) -> dict:
    """
    Run the 4-agent improvement crew on recent call data.

    Pre-screens calls and skips the LLM entirely when no call is suspicious AND
    we have no broader sample worth scanning for gaps, which is the common case
    for healthy workflows.

    Args:
        runs: recent WorkflowRunModel objects (already loaded, max 20)
        aggregate_stats: pre-computed SQL stats (disposition counts, avg duration, etc.)
        past_suggestions: previously-seen suggestions (for deduplication)

    Returns: {"suggestions": [...], "analysis_summary": str, "calls_analyzed": int, "last_run_id": int}
    """
    import asyncio

    if not runs:
        return {"suggestions": [], "analysis_summary": "No calls to analyze.", "calls_analyzed": 0, "last_run_id": 0}

    all_summaries = [_extract_call_summary(r) for r in runs]
    suspicious = [s for s in all_summaries if s.get("suspicion_score", 0) >= 2]

    logger.info(
        f"[SelfImprove] Workflow {workflow_id}: {len(all_summaries)} calls reviewed, "
        f"{len(suspicious)} flagged as suspicious"
    )

    last_run_id = max(s["run_id"] for s in all_summaries)

    # Fast path: nothing is suspicious AND the call volume is too small for a
    # meaningful gap scan → don't spend a cent on the LLM. We still allow the
    # gap analyst to run on a small healthy sample as long as we have at least
    # 3 calls, because a side-use-case can hide in a single satisfied caller.
    if not suspicious and len(all_summaries) < 3:
        return {
            "suggestions": [],
            "analysis_summary": (
                f"Analyzed {len(all_summaries)} calls — no quality issues detected. "
                "Your agent is performing well."
            ),
            "calls_analyzed": len(all_summaries),
            "last_run_id": last_run_id,
        }

    # Failure detector input: only the flagged calls, ordered by severity.
    suspicious.sort(key=lambda s: s.get("suspicion_score", 0), reverse=True)
    detector_input = suspicious[:MAX_CALLS_PER_ANALYSIS]

    # Gap analyst input: a broader sample (suspicious + healthy) so it can
    # spot side-use-cases that hide inside satisfied calls. We always include
    # every suspicious call, then top up with healthy calls until we hit the cap.
    healthy = [s for s in all_summaries if s.get("suspicion_score", 0) < 2]
    gap_input = suspicious + healthy
    gap_input = gap_input[:MAX_CALLS_FOR_GAP_SCAN]

    enriched_stats = dict(aggregate_stats or {})
    enriched_stats["suspicious_calls_detected"] = len(suspicious)
    enriched_stats["suspicious_sample_sent_to_failure_detector"] = len(detector_input)
    enriched_stats["sample_sent_to_gap_analyst"] = len(gap_input)

    crew = _build_improvement_crew(
        workflow_name,
        workflow_definition,
        detector_input,
        gap_input,
        enriched_stats,
    )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, crew.kickoff)

    task_outputs = result.tasks_output if hasattr(result, "tasks_output") else []

    suggestions: list[dict] = []
    summary = "Analysis complete."

    # Architect output is the 4th task now (index 3): detect, gaps, patterns, improve.
    if len(task_outputs) >= 4:
        try:
            improve_data = _parse_json_from_output(task_outputs[3].raw)
            suggestions = improve_data.get("suggestions", []) or []
            summary = improve_data.get("summary", summary)
        except Exception as e:
            logger.error(f"[SelfImprove] Failed to parse improvement output: {e}")

    valid_node_ids = {n["id"] for n in workflow_definition.get("nodes", []) if isinstance(n, dict) and n.get("id")}
    suggestions = _validate_and_clean_suggestions(suggestions, valid_node_ids)

    if past_suggestions:
        suggestions = _dedupe_suggestions(suggestions, past_suggestions)

    logger.info(f"[SelfImprove] Complete: {len(suggestions)} suggestions for workflow {workflow_id}")

    return {
        "suggestions": suggestions,
        "analysis_summary": summary,
        "calls_analyzed": len(all_summaries),
        "last_run_id": last_run_id,
    }
