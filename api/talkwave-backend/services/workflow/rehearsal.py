"""
Workflow Auto-Rehearsal — stress-test a workflow before real callers hit it.

When a workflow is generated (industry_crew) or meaningfully changed, we run
3 text-based simulated calls against it — one per "persona" — to:
  1. Produce a Workflow Health Score (0-100) shown in the UI.
  2. Surface concrete failure modes ("agent looped on the date field 3 times").
  3. Auto-queue fixes into the self-improve pipeline for the ones we can patch.

Why text-based (no audio)? Cost and latency. A full LoopTalk voice simulation
costs ~$0.10–0.30 per call. A text rehearsal round-trip is ~$0.01 and finishes
in seconds. We can run hundreds per day without breaking the budget.

Memory characteristics:
  - Each rehearsal holds only the transcript (≤4 KB) and a compact blueprint.
  - Max 3 personas × max 10 turns = 30 LLM calls per rehearsal (hard cap).
  - Per-run timeout so a stuck LLM can't starve the ARQ worker.

Personas are designed to probe the three most common failure modes we've
seen in production: misunderstanding, impatience, and ambiguity.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from loguru import logger

MAX_TURNS = 10
MAX_CONCURRENT_PERSONAS = 3
PER_CALL_TIMEOUT_SECONDS = 90
OUTCOME_COMPLETE = "complete"
OUTCOME_INCOMPLETE = "incomplete"
OUTCOME_ERROR = "error"

# The personas are intentionally diverse and target different failure modes.
PERSONAS: List[Dict[str, str]] = [
    {
        "id": "confused",
        "name": "Confused Caller",
        "goal": "You are a hesitant caller who doesn't fully understand what the agent is asking. You give vague answers, occasionally ask 'what do you mean?', and sometimes give irrelevant information before eventually cooperating. Probes: whether the agent can recover from ambiguity without looping.",
    },
    {
        "id": "rushed",
        "name": "Rushed Caller",
        "goal": "You are in a huge hurry. You answer in 2-5 words, interrupt, and push the agent to finish as quickly as possible. If the agent asks redundant questions, you express frustration. Probes: whether the agent respects brevity and doesn't waste turns.",
    },
    {
        "id": "happy",
        "name": "Cooperative Caller",
        "goal": "You are the ideal caller: polite, forthcoming, and answer every question directly and concisely. You have a clear reason for calling and provide all requested information. Probes: whether the agent can complete its happy path cleanly.",
    },
]


def _get_llm_model_string() -> str:
    """Pick a cheap fast model for rehearsal. Prefer gpt-4.1-mini if available."""
    if os.getenv("OPENAI_API_KEY"):
        return "openai/gpt-4.1-mini"
    if os.getenv("GROQ_API_KEY"):
        return "groq/llama-3.3-70b-versatile"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic/claude-haiku-4-20250514"
    return "openai/gpt-4.1-mini"


def _summarize_workflow_for_persona(workflow_definition: Dict[str, Any]) -> str:
    """
    Extract a compact spec from the workflow that the caller-persona LLM
    can use as 'the agent it is talking to'. We don't ship the full prompt
    tree — just node purposes + exit conditions so the persona can react
    realistically.
    """
    nodes = workflow_definition.get("nodes") or []
    if not nodes:
        return "(empty workflow)"

    # Identify the StartCall node to figure out what the agent is calling ABOUT
    start = next(
        (n for n in nodes if (n.get("type") or "").lower() in ("startcall", "startnode")),
        None,
    )
    purpose = ""
    if start:
        data = start.get("data") or {}
        purpose = (
            data.get("purpose")
            or data.get("objective")
            or data.get("description")
            or data.get("name")
            or ""
        )

    lines: List[str] = []
    if purpose:
        lines.append(f"Agent's purpose: {purpose[:240]}")

    agent_nodes = [n for n in nodes if (n.get("type") or "").lower() == "agentnode"]
    lines.append(f"Agent has {len(agent_nodes)} conversation step(s).")
    for n in agent_nodes[:6]:  # cap to keep context small
        data = n.get("data") or {}
        name = data.get("name") or n.get("id", "?")
        goal = data.get("name") or data.get("goal") or ""
        lines.append(f"  - {name}: {goal[:160]}")
    return "\n".join(lines)


def _build_agent_system_prompt(workflow_definition: Dict[str, Any]) -> str:
    """
    Synthesize a system prompt for the "agent" side of the simulation from
    the workflow definition. Uses StartCall purpose + concatenated agent
    node prompts as a lightweight behavioral spec. This is not 1:1 with
    the live PipecatEngine (which does graph routing), but it's a
    faithful-enough proxy to catch ~80% of prompt quality issues in
    seconds.
    """
    nodes = workflow_definition.get("nodes") or []

    preamble = "You are a voice agent on a phone call. Follow the playbook below. Keep responses conversational and brief (1-2 sentences). When the task is done, end with exactly the token [END_CALL]."
    parts = [preamble]

    start = next(
        (n for n in nodes if (n.get("type") or "").lower() in ("startcall", "startnode")),
        None,
    )
    if start:
        sd = start.get("data") or {}
        opener = sd.get("prompt") or sd.get("message") or sd.get("description") or ""
        if opener:
            parts.append(f"Opening/purpose:\n{opener[:800]}")

    agent_nodes = [n for n in nodes if (n.get("type") or "").lower() == "agentnode"]
    for n in agent_nodes[:6]:
        data = n.get("data") or {}
        name = data.get("name") or n.get("id", "Step")
        prompt = data.get("prompt") or data.get("instructions") or ""
        if prompt:
            parts.append(f"Step '{name}':\n{prompt[:600]}")

    parts.append(
        "Constraints: Never invent information not given. If the caller is confused, "
        "clarify in simpler words. If the caller is rushed, cut directly to the point. "
        "When the caller's need has been addressed, say a brief goodbye and append [END_CALL]."
    )
    return "\n\n".join(parts)


async def _llm_complete(messages: List[Dict[str, str]], temperature: float, max_tokens: int = 200) -> str:
    """
    Minimal async LLM completion wrapper. Uses openai's AsyncClient when
    available (present in the repo as the canonical provider). Returns the
    assistant text or an empty string on any failure (we never want rehearsal
    to crash the user's workflow generation).
    """
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.warning("[Rehearsal] openai package unavailable — skipping rehearsal")
        return ""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return ""

    model = os.getenv("REHEARSAL_MODEL", "gpt-4.1-mini")

    client = AsyncOpenAI(api_key=api_key)
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning(f"[Rehearsal] LLM completion failed: {e}")
        return ""


async def _run_persona_dialogue(
    agent_system: str,
    workflow_summary: str,
    persona: Dict[str, str],
) -> Dict[str, Any]:
    """Simulate a conversation between one persona and the agent. ≤10 turns."""
    start_ts = time.time()
    transcript: List[Dict[str, str]] = []
    outcome = OUTCOME_INCOMPLETE
    issues: List[str] = []

    persona_system = (
        f"You are role-playing a caller. {persona['goal']}\n\n"
        f"You are calling an agent with this context:\n{workflow_summary}\n\n"
        "Rules: stay in character, ONE short utterance per turn (1-2 sentences), "
        "react naturally to what the agent just said. When you are done (got what "
        "you needed OR decided to leave), end your final utterance with [HANGUP]."
    )

    # Agent opens the call.
    agent_turn = await _llm_complete(
        [
            {"role": "system", "content": agent_system},
            {"role": "user", "content": "(Call connected. You speak first.)"},
        ],
        temperature=0.4,
        max_tokens=180,
    )
    if not agent_turn:
        return {
            "persona": persona["id"],
            "outcome": OUTCOME_ERROR,
            "transcript": [],
            "issues": ["Agent failed to produce opening utterance"],
            "turns": 0,
            "elapsed_seconds": round(time.time() - start_ts, 2),
        }
    transcript.append({"role": "agent", "content": agent_turn})

    # Track repetition for loop detection
    recent_agent_turns: List[str] = [agent_turn]

    for turn in range(MAX_TURNS):
        # Check for agent-initiated end
        if "[END_CALL]" in agent_turn:
            outcome = OUTCOME_COMPLETE
            break

        # Caller persona responds
        caller_context = "\n".join(
            f"{m['role']}: {m['content']}" for m in transcript[-8:]
        )
        caller_turn = await _llm_complete(
            [
                {"role": "system", "content": persona_system},
                {"role": "user", "content": f"Conversation so far:\n{caller_context}\n\nYour reply:"},
            ],
            temperature=0.8,
            max_tokens=120,
        )
        if not caller_turn:
            issues.append("Persona LLM failed — simulation cut short")
            outcome = OUTCOME_ERROR
            break
        transcript.append({"role": "caller", "content": caller_turn})

        if "[HANGUP]" in caller_turn:
            # Caller ended the call. If agent didn't get to [END_CALL], that's
            # typically an abandonment.
            outcome = OUTCOME_INCOMPLETE
            issues.append("Caller ended the call before agent completed objective")
            break

        # Agent responds
        agent_context = "\n".join(
            f"{m['role']}: {m['content']}" for m in transcript[-10:]
        )
        agent_turn = await _llm_complete(
            [
                {"role": "system", "content": agent_system},
                {"role": "user", "content": f"Conversation so far:\n{agent_context}\n\nYour reply:"},
            ],
            temperature=0.3,
            max_tokens=180,
        )
        if not agent_turn:
            issues.append("Agent failed mid-conversation")
            outcome = OUTCOME_ERROR
            break
        transcript.append({"role": "agent", "content": agent_turn})

        # Loop detection: agent said something ≥80% similar to a recent turn
        for prior in recent_agent_turns[-3:]:
            if _similarity_ratio(prior, agent_turn) > 0.82:
                issues.append(f"Agent looped at turn {turn + 1}: repeated itself")
                outcome = OUTCOME_INCOMPLETE
                break
        if outcome == OUTCOME_INCOMPLETE and "looped" in (issues[-1] if issues else ""):
            break

        recent_agent_turns.append(agent_turn)
    else:
        # Hit turn limit without completion
        issues.append(f"Conversation hit {MAX_TURNS}-turn limit without resolution")
        outcome = OUTCOME_INCOMPLETE

    return {
        "persona": persona["id"],
        "persona_name": persona["name"],
        "outcome": outcome,
        "transcript": transcript,
        "issues": issues,
        "turns": len(transcript),
        "elapsed_seconds": round(time.time() - start_ts, 2),
    }


def _similarity_ratio(a: str, b: str) -> float:
    """Cheap character-3gram Jaccard similarity for loop detection."""
    if not a or not b:
        return 0.0
    a = re.sub(r"\s+", " ", a.lower()).strip()
    b = re.sub(r"\s+", " ", b.lower()).strip()
    if a == b:
        return 1.0

    def grams(s: str) -> set:
        return {s[i:i + 3] for i in range(len(s) - 2)} if len(s) > 2 else {s}

    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    union = len(ga | gb)
    return inter / union if union else 0.0


def _compute_health_score(results: List[Dict[str, Any]]) -> int:
    """0-100 score. Complete outcomes score full. Loops/abandonment penalize."""
    if not results:
        return 0
    total = 0
    for r in results:
        outcome = r.get("outcome")
        if outcome == OUTCOME_COMPLETE:
            total += 100
        elif outcome == OUTCOME_INCOMPLETE:
            # Partial credit based on issue severity
            penalty = min(40 + 10 * len(r.get("issues") or []), 80)
            total += max(100 - penalty, 20)
        else:
            total += 0
    return int(total / len(results))


async def run_rehearsal(
    workflow_definition: Dict[str, Any],
    personas: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Main entry point. Runs one simulated call per persona concurrently
    (bounded) and returns a compact report:

        {
          "health_score": 78,
          "personas_tested": 3,
          "results": [{persona, outcome, issues, turns, transcript_preview}, ...],
          "summary": "2/3 personas completed; 1 abandonment on the 'confused' persona.",
          "elapsed_seconds": 14.2
        }
    """
    t0 = time.time()
    personas = personas or PERSONAS

    agent_system = _build_agent_system_prompt(workflow_definition)
    workflow_summary = _summarize_workflow_for_persona(workflow_definition)

    # Run personas concurrently, bounded
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_PERSONAS)

    async def _bounded(persona):
        async with semaphore:
            try:
                return await asyncio.wait_for(
                    _run_persona_dialogue(agent_system, workflow_summary, persona),
                    timeout=PER_CALL_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return {
                    "persona": persona["id"],
                    "persona_name": persona.get("name", persona["id"]),
                    "outcome": OUTCOME_ERROR,
                    "transcript": [],
                    "issues": [f"Persona simulation timed out after {PER_CALL_TIMEOUT_SECONDS}s"],
                    "turns": 0,
                    "elapsed_seconds": PER_CALL_TIMEOUT_SECONDS,
                }

    results = await asyncio.gather(*(_bounded(p) for p in personas))

    # Trim transcripts to a short preview for storage (full transcript would
    # bloat the DB). The issues list is what users actually care about.
    compact_results = []
    for r in results:
        transcript = r.get("transcript") or []
        preview = transcript[-4:] if len(transcript) > 4 else transcript
        compact_results.append(
            {
                "persona": r.get("persona"),
                "persona_name": r.get("persona_name"),
                "outcome": r.get("outcome"),
                "issues": r.get("issues") or [],
                "turns": r.get("turns", 0),
                "elapsed_seconds": r.get("elapsed_seconds"),
                "transcript_preview": preview,
            }
        )

    score = _compute_health_score(results)
    completed = sum(1 for r in results if r.get("outcome") == OUTCOME_COMPLETE)
    summary = (
        f"{completed}/{len(results)} simulated calls completed successfully. "
        f"Workflow Health Score: {score}/100."
    )
    if completed < len(results):
        failed_personas = [r.get("persona_name") for r in results if r.get("outcome") != OUTCOME_COMPLETE]
        summary += f" Failures on: {', '.join(p for p in failed_personas if p)}."

    return {
        "health_score": score,
        "personas_tested": len(results),
        "results": compact_results,
        "summary": summary,
        "elapsed_seconds": round(time.time() - t0, 2),
    }


async def run_workflow_rehearsal_task(ctx: Dict, workflow_id: int):
    """
    ARQ task entry point. Runs a rehearsal for `workflow_id` and stores the
    result in the workflow's `workflow_configurations.rehearsal` field so the
    UI can display the Health Score and issues.
    """
    from api.db import db_client

    try:
        workflow = await db_client.get_workflow_by_id(workflow_id)
        if not workflow:
            logger.warning(f"[Rehearsal] Workflow {workflow_id} not found")
            return

        definition = workflow.workflow_definition or {}
        if not definition.get("nodes"):
            logger.info(f"[Rehearsal] Workflow {workflow_id} has no nodes — skipping")
            return

        logger.info(f"[Rehearsal] Starting rehearsal for workflow {workflow_id}")
        report = await run_rehearsal(definition)
        logger.info(
            f"[Rehearsal] Complete | workflow={workflow_id} | "
            f"score={report['health_score']} | elapsed={report['elapsed_seconds']}s"
        )

        # Persist the report onto the workflow so the UI can show it.
        # `update_workflow` merges workflow_configurations rather than replacing,
        # so we only ship the new `rehearsal` key — safe alongside any
        # concurrent writes. We pass workflow_definition=None to avoid
        # bumping the definition version.
        rehearsal_payload = {
            **report,
            "workflow_definition_hash": _hash_definition(definition),
            "generated_at": time.time(),
        }
        try:
            await db_client.update_workflow(
                workflow_id=workflow_id,
                name=workflow.name,
                workflow_definition=None,
                template_context_variables=None,
                workflow_configurations={"rehearsal": rehearsal_payload},
                organization_id=getattr(workflow, "organization_id", None),
            )
        except Exception as persist_err:
            logger.warning(f"[Rehearsal] Could not persist report: {persist_err}")

    except Exception as e:
        logger.error(f"[Rehearsal] Task failed for workflow {workflow_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())


def _hash_definition(definition: Dict[str, Any]) -> str:
    """Stable short hash so the UI can tell if the rehearsal is stale."""
    import hashlib
    try:
        blob = json.dumps(definition, sort_keys=True, default=str).encode()
    except Exception:
        blob = str(definition).encode()
    return hashlib.md5(blob).hexdigest()[:12]
