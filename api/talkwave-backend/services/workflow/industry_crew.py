"""
CrewAI-powered industry-specialized workflow generation.

Uses 4 sequential CrewAI agents, each tuned for its role:
  1. Industry Expert   — Analyzes business, discovers all use cases      (temp 0.25)
  2. Workflow Architect — Designs the dynamic node/edge blueprint        (temp 0.1)
  3. Prompt Engineer    — Writes prompts for all nodes                   (temp 0.55)
  4. QA Reviewer        — Validates compliance, consistency              (temp 0.2)

Safety net: the blueprint is post-validated and self-repaired before the
Prompt Engineer runs. A missing `task_complete` or `user_wants_to_end` exit
would otherwise break downstream routing — we inject them automatically.

Context is bounded: scraped link context is hard-capped to ~6 KB using a
head+tail sample so the crew never blows its context budget.
"""

import json
import os
import re
import uuid
from typing import Optional

from loguru import logger

from api.services.workflow.industry_templates import (
    INDUSTRY_REGISTRY,
    assemble_workflow_definition,
)

# Disable CrewAI's interactive tracing prompt + telemetry in production.
# Without this, every crew run prints `Would you like to view your execution
# traces? [y/N]` and waits 20 seconds — pure noise in headless deployments.
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

# Hard cap on scraped link context delivered to the LLM crew. Keeps the whole
# generation roughly ≤ 20 KB of input per task so even small-context models
# (e.g. 32K) have plenty of headroom for the blueprint + prompt output.
MAX_SCRAPED_CONTEXT_CHARS = 6000

# Default exits every non-router agent node must have. If the architect
# forgets one we inject it automatically during validation.
_REQUIRED_AGENT_EXITS = (
    ("task_complete", "The user's task has been completed successfully."),
    ("user_wants_to_end", "The caller explicitly wants to end the conversation."),
)


# =============================================================================
# Variable policy — shared by EVERY CrewAI task.
#
# Priority order for any concrete fact (hours, address, phone, email,
# services, policies, etc.):
#   1. Explicit `business_info` variable supplied by the user → use verbatim.
#   2. Scraped knowledge-base content (homepage, About / Contact / FAQ pages,
#      uploaded docs) → extract the exact value if it appears there.
#   3. Otherwise → omit the field or use generic phrasing. Never fabricate.
#
# `business_name` is always a Tier-1 value: use it verbatim, never rename.
# =============================================================================
def _build_variable_policy(
    business_name: str,
    business_info: Optional[dict[str, str]],
    has_kb_content: bool = False,
) -> str:
    """Format the user-supplied variables as a strict manifest the LLM sees
    at the top of every task. Concrete facts must come from PROVIDED (Tier-1)
    or, failing that, the scraped knowledge-base content (Tier-2). Anything
    that exists in neither source must be omitted or expressed with generic
    phrasing — never fabricated."""
    provided: list[str] = [f"- business_name = {business_name!r}"]
    omitted: list[str] = []
    fields = [
        ("business_hours", "hours"),
        ("location", "location"),
        ("phone", "phone"),
        ("email", "email"),
        ("services", "services"),
        ("policies", "policies"),
    ]
    info = business_info or {}
    for key, label in fields:
        val = (info.get(key) or "").strip()
        if val:
            provided.append(f"- {label} = {val!r}")
        else:
            omitted.append(label)

    # The fallback paragraph depends on whether scraped KB content is in the
    # task input. When it is, the LLM can fill missing fields from the website
    # / docs. When it isn't, the only allowed fallback is generic phrasing.
    if has_kb_content:
        kb_clause = (
            "If a field is missing from PROVIDED but the SCRAPED CONTENT / "
            "knowledge base below mentions it explicitly (e.g. a phone number "
            "on the Contact page, hours on the About page, an address in the "
            "footer), copy that exact value into the prompt. Treat scraped "
            "content as authoritative just like PROVIDED — but only when the "
            "fact is unambiguously stated, not implied or paraphrased."
        )
    else:
        kb_clause = (
            "No knowledge-base content was supplied for this workflow. The "
            "ONLY authoritative source is the PROVIDED list above."
        )

    omitted_section = ""
    if omitted:
        omitted_section = (
            "\n\nNOT PROVIDED (look in scraped content first; otherwise omit "
            "or use generic phrasing):\n"
            + "\n".join(f"- {o}" for o in omitted)
        )

    return (
        "VARIABLE POLICY (read first, applies to EVERY field you write):\n"
        "Source priority for any concrete fact:\n"
        "  1. PROVIDED (Tier-1) → quote verbatim.\n"
        "  2. SCRAPED CONTENT / knowledge base (Tier-2) → quote verbatim if "
        "the fact appears there.\n"
        "  3. Otherwise → omit or use generic phrasing such as \"during our "
        "regular business hours\", \"at our location\", \"you can reach our "
        "team\".\n"
        "NEVER fabricate addresses, phone numbers, hours, emails, prices, or "
        "services. NEVER substitute the business name with anything else "
        "(no \"FitLife Wellness Center\" if the user typed \"ufc gym\").\n\n"
        f"{kb_clause}\n\n"
        "PROVIDED (use verbatim, do NOT rename, polish, or paraphrase):\n"
        + "\n".join(provided)
        + omitted_section
    )


def _get_llm_model_string() -> str:
    """Return a CrewAI-compatible LLM model string based on available env keys."""
    if os.getenv("OPENAI_API_KEY"):
        return "openai/gpt-4.1"
    elif os.getenv("GROQ_API_KEY"):
        return "groq/llama-3.3-70b-versatile"
    elif os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic/claude-sonnet-4-20250514"
    return "openai/gpt-4.1"


def _build_llm(temperature: float, max_tokens: int = 2048):
    """
    Build a CrewAI LLM object with tuned temperature/max_tokens for a specific role.
    Falls back to a plain model string if the CrewAI LLM class isn't importable.
    """
    model = _get_llm_model_string()
    try:
        from crewai import LLM  # type: ignore
        return LLM(model=model, temperature=temperature, max_tokens=max_tokens)
    except Exception:
        return model


def _bound_context(text: Optional[str], max_chars: int = MAX_SCRAPED_CONTEXT_CHARS) -> str:
    """Truncate long context using a head + tail sample so key info at both ends is retained."""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    head_share = int(max_chars * 0.7)
    tail_share = max_chars - head_share - 40
    return f"{text[:head_share]}\n... [content truncated, {len(text) - max_chars} chars omitted] ...\n{text[-tail_share:]}"


class _NoJsonInOutput(ValueError):
    """Raised when the LLM output contains no JSON object at all.

    This commonly happens when a QA/review agent decides no fixes are needed
    and replies with an approval paragraph instead of a JSON envelope.
    The caller can treat this as a soft signal to fall back to a previous
    step's output without logging a scary error.
    """


def _parse_json_from_output(text: str) -> dict:
    """
    Extract JSON from CrewAI task output. Handles:
      - markdown code fences (```json ... ```)
      - surrounding prose
      - trailing commas before ] or }
      - single-quoted strings emitted by some models
    Raises ``_NoJsonInOutput`` when the payload contains no '{' at all so
    callers can distinguish "approval prose" from genuine parse failures.
    """
    if not text:
        raise ValueError("Empty LLM output")
    cleaned = text.strip()

    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    # Isolate the outermost JSON object — but only if one exists.
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start < 0 or end <= start:
        # No JSON object at all → almost certainly an approval/prose response.
        raise _NoJsonInOutput(
            f"LLM returned prose with no JSON object. First 200 chars: {cleaned[:200]}"
        )
    cleaned = cleaned[start:end]

    # Attempt 1: parse as-is
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Attempt 2: remove trailing commas before ] or }
    repaired = re.sub(r",\s*([\]}])", r"\1", cleaned)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Attempt 3: swap single quotes for double quotes (last-ditch)
    # Only do this if there are obviously no double quotes wrapping keys/values
    if '"' not in repaired and "'" in repaired:
        try:
            return json.loads(repaired.replace("'", '"'))
        except json.JSONDecodeError:
            pass

    # Diagnose truncation (most common cause of unrecoverable parse failures):
    # if the open/close bracket counts don't match, the LLM hit max_tokens
    # mid-output. Surface that explicitly so the operator can bump the cap.
    open_braces = cleaned.count("{")
    close_braces = cleaned.count("}")
    open_brackets = cleaned.count("[")
    close_brackets = cleaned.count("]")
    truncated = (open_braces != close_braces) or (open_brackets != close_brackets)

    logger.error(
        f"[JSON parse] failed | len={len(cleaned)} | "
        f"braces {open_braces}/{close_braces} | brackets {open_brackets}/{close_brackets} | "
        f"truncated={truncated}"
    )
    logger.error(f"[JSON parse] last 300 chars of payload: {cleaned[-300:]}")

    detail = "LLM output appears truncated (likely max_tokens cap)" if truncated else "malformed JSON"
    raise ValueError(
        f"Could not parse JSON from LLM output — {detail}. "
        f"First 200 chars: {cleaned[:200]}"
    )


def _ensure_exit(exit_conditions: list, name: str, description: str) -> None:
    """Add an exit condition by name if missing."""
    for ec in exit_conditions:
        if (ec.get("name") or "").strip().lower() == name.lower():
            return
    exit_conditions.append({
        "id": f"exit-{uuid.uuid4().hex[:8]}",
        "name": name,
        "llm_description": description,
    })


def _validate_blueprint(blueprint: dict) -> None:
    """
    Repair + validate an LLM-generated workflow blueprint in place.

    Guarantees after this runs:
      - Every node has a unique id.
      - Every edge points to valid node ids (invalid edges dropped, logged).
      - Every agentNode has `task_complete` AND `user_wants_to_end` exit conditions.
      - Every agentNode has at least one outgoing edge; if missing, we wire
        task_complete → endCall.
      - Every exit condition has an id.
      - At least one endCall exists (if not, we synthesize one).
    """
    nodes = blueprint.get("nodes") or []
    edges = blueprint.get("edges") or []

    # 1. Assign ids & collect node ids by type
    node_ids = set()
    end_call_ids: list[str] = []
    agent_node_ids: list[str] = []
    start_call_id: Optional[str] = None
    global_node_id: Optional[str] = None

    for n in nodes:
        if "id" not in n or not n["id"]:
            n["id"] = f"node-{uuid.uuid4().hex[:8]}"
        node_ids.add(n["id"])
        ntype = n.get("type")
        if ntype == "endCall":
            end_call_ids.append(n["id"])
        elif ntype == "agentNode":
            agent_node_ids.append(n["id"])
        elif ntype == "startCall":
            start_call_id = n["id"]
        elif ntype == "globalNode":
            global_node_id = n["id"]

        for ec in n.get("exit_conditions", []) or []:
            if "id" not in ec or not ec["id"]:
                ec["id"] = f"exit-{uuid.uuid4().hex[:8]}"

    # 2. Ensure an endCall exists — synthesize if missing
    if not end_call_ids:
        synth = {
            "id": f"end-{uuid.uuid4().hex[:8]}",
            "type": "endCall",
            "name": "End Call",
        }
        nodes.append(synth)
        node_ids.add(synth["id"])
        end_call_ids.append(synth["id"])
        logger.warning("[IndustryCrew] Architect forgot endCall — synthesized one")

    # 3. Drop invalid edges
    valid_edges = []
    for e in edges:
        if e.get("source") in node_ids and e.get("target") in node_ids:
            if "id" not in e or not e["id"]:
                e["id"] = f"edge-{uuid.uuid4().hex[:8]}"
            valid_edges.append(e)
    dropped = len(edges) - len(valid_edges)
    if dropped:
        logger.warning(f"[IndustryCrew] Dropped {dropped} edges pointing to unknown nodes")
    blueprint["edges"] = valid_edges

    # 4. Every agentNode must have task_complete + user_wants_to_end exits
    #    and at least one outgoing edge. If it has none, wire task_complete → endCall.
    outgoing_by_source: dict[str, list[dict]] = {}
    for e in valid_edges:
        outgoing_by_source.setdefault(e["source"], []).append(e)

    default_end = end_call_ids[0]
    for n in nodes:
        if n.get("type") != "agentNode":
            continue
        exits = n.setdefault("exit_conditions", [])
        for name, desc in _REQUIRED_AGENT_EXITS:
            _ensure_exit(exits, name, desc)

        node_out = outgoing_by_source.get(n["id"], [])
        if not node_out:
            # No outgoing routing → caller can get stuck. Wire task_complete → endCall.
            blueprint["edges"].append({
                "id": f"edge-{uuid.uuid4().hex[:8]}",
                "source": n["id"],
                "target": default_end,
                "condition": "task_complete",
                "label": "Task Complete",
            })
            logger.warning(f"[IndustryCrew] Agent node {n['id']} had no outgoing edges — wired to endCall")

        # Ensure there's at least one edge for user_wants_to_end → endCall
        has_user_end = any(
            (e.get("condition") or "").lower() == "user_wants_to_end"
            for e in outgoing_by_source.get(n["id"], [])
        )
        if not has_user_end:
            blueprint["edges"].append({
                "id": f"edge-{uuid.uuid4().hex[:8]}",
                "source": n["id"],
                "target": default_end,
                "condition": "user_wants_to_end",
                "label": "User Ends",
            })

    # 5. Sanity log — this helps catch model regressions fast
    logger.info(
        f"[IndustryCrew] Validated blueprint: {len(nodes)} nodes "
        f"({len(agent_node_ids)} agents, {len(end_call_ids)} endCalls, "
        f"start={'yes' if start_call_id else 'no'}, global={'yes' if global_node_id else 'no'}), "
        f"{len(blueprint['edges'])} edges"
    )


def _ensure_all_prompts(blueprint: dict, prompts: dict[str, str]) -> dict[str, str]:
    """
    Guarantee every node has at least a minimal prompt. This avoids silent
    rendering failures downstream if the prompt engineer skipped a node.
    """
    result = dict(prompts or {})
    for n in blueprint.get("nodes", []):
        nid = n["id"]
        if nid in result and result[nid]:
            continue
        ntype = n.get("type")
        name = n.get("name") or ntype or "Agent"
        if ntype == "endCall":
            result[nid] = "Thanks for calling. Have a great day!"
        elif ntype == "startCall":
            result[nid] = "Hi, thanks for reaching out. How can I help you today?"
        elif ntype == "globalNode":
            result[nid] = "You are a friendly, professional voice assistant. Speak naturally as if on a phone call."
        elif ntype == "ifElse":
            # ifElse uses `condition_text`, not `prompt`. Provide a safe
            # default condition if the architect left it blank so the node
            # still renders editable in the UI.
            if not n.get("condition_text"):
                n["condition_text"] = (
                    "True when the caller has confirmed they want to proceed; "
                    "false otherwise."
                )
                logger.warning(
                    f"[IndustryCrew] Missing condition_text on ifElse {nid} — using fallback"
                )
            result[nid] = ""
            continue
        elif ntype == "categorize":
            result[nid] = (
                "Classify the caller's intent based on the most recent few "
                "turns of the conversation and pick the best-matching category."
            )
        elif ntype == "transfer":
            result[nid] = (
                "Please hold while I transfer you to the right team. "
                "Thanks for your patience."
            )
        else:
            result[nid] = f"You are the {name}. Help the caller with their request clearly and concisely."
        logger.warning(f"[IndustryCrew] Missing prompt for {nid} ({ntype}) — using fallback")
    return result


def _build_crew(
    industry_key: str,
    business_name: str,
    business_description: str,
    call_type: str,
    scraped_link_context: Optional[str] = None,
    business_info: Optional[dict[str, str]] = None,
):
    """Build and return a CrewAI Crew with 4 agents and 4 sequential tasks."""
    from crewai import Agent, Task, Crew, Process

    industry = INDUSTRY_REGISTRY[industry_key]

    # Token budgets are sized for the WORST case of each task. The Architect
    # in particular emits the full blueprint JSON (nodes + edges + global) and
    # complex industries routinely cross 4k tokens — under-sizing here causes
    # silent JSON truncation that the downstream parser cannot recover from.
    expert_llm = _build_llm(temperature=0.25, max_tokens=4096)
    architect_llm = _build_llm(temperature=0.1, max_tokens=8192)
    prompt_llm = _build_llm(temperature=0.55, max_tokens=8192)
    qa_llm = _build_llm(temperature=0.2, max_tokens=8192)

    compliance_rules_text = "\n".join(f"- {r}" for r in industry["compliance_rules"])
    use_cases_text = "\n".join(
        f"- {uc['name']}: {uc['description']}" for uc in industry["possible_use_cases"]
    )
    fixed_patterns = industry.get("fixed_patterns") or {}
    fixed_pattern_text = (
        f"FIXED PATTERN: {fixed_patterns['description']}"
        if fixed_patterns
        else "No fixed structural patterns required."
    )

    # Single source of truth for what the LLM is allowed to commit to as
    # concrete fact. Prepended to every task description below.
    # When the user provided reference links we ALSO let the LLM source
    # facts from the scraped content (Tier-2). Without scraped content, the
    # only authoritative source is the structured business_info (Tier-1).
    variable_policy = _build_variable_policy(
        business_name,
        business_info,
        has_kb_content=bool(scraped_link_context),
    )

    # `reasoning=True` makes each agent draft a plan, sanity-check it, and
    # refine before execution — CrewAI's built-in equivalent of using an
    # o-series reasoning model, but on top of gpt-4.1. The max_reasoning
    # caps below bound the planning loop so a stuck agent can't burn
    # unbounded tokens; CrewAI defaults to None which is infinite and
    # dangerous in production. The values are tuned per role:
    #   - architect / qa_reviewer (3): they make structural decisions —
    #     blueprint correctness and hallucination sweeps benefit most from
    #     a couple of refinement passes.
    #   - expert / prompt_engineer (2): more mechanical work; one plan +
    #     one refinement is plenty without inflating cost too much.
    # Net effect vs. the old config: ~2–3× LLM calls per generation,
    # significantly higher output quality (especially on the architect's
    # branching graph and the QA's anti-hallucination sweep).
    industry_expert = Agent(
        role=f"{industry['display_name']} Business Analyst",
        goal=(
            f"Analyze the business description for '{business_name}' and produce a structured "
            "Business Profile with ALL discovered use cases that need voice agent handling."
        ),
        backstory=industry["expert_backstory"],
        llm=expert_llm,
        verbose=False,
        allow_delegation=False,
        max_iter=4,
        reasoning=True,
        max_reasoning_attempts=2,
    )

    workflow_architect = Agent(
        role="Voice AI Workflow Architect",
        goal=(
            "Design a complete workflow blueprint with the right number of nodes, "
            "exit conditions, and edge connections based on the discovered use cases."
        ),
        backstory=(
            "You are an expert at designing multi-node voice agent workflows. You know "
            "when to use parallel branches (independent intents from a router), sequential "
            "chains (dependent steps), and sub-flows (complex multi-step processes). You "
            "understand node exit conditions and edge routing deeply, and you ALWAYS "
            "include `task_complete` and `user_wants_to_end` exits on every agent node. "
            "Before you emit the blueprint, you reason explicitly about whether the "
            "workflow needs branching nodes (ifElse / categorize / transfer) and only "
            "skip them when none of the self-check questions apply."
        ),
        llm=architect_llm,
        verbose=False,
        allow_delegation=False,
        max_iter=4,
        reasoning=True,
        max_reasoning_attempts=3,
    )

    prompt_engineer = Agent(
        role="Voice AI Conversation Designer",
        goal=(
            "Write production-quality voice agent prompts for every node in the workflow "
            "that sound natural when spoken aloud and include specific business details."
        ),
        backstory=(
            "You are an expert in writing prompts for voice AI agents. You understand the "
            "difference between written text and natural spoken dialogue. You know how to "
            "design multi-turn conversations with readback confirmations, empathy patterns, "
            "and graceful error handling. Each prompt you write is 150-400 words. You never "
            "invent business details — you stay strictly within the provided profile."
        ),
        llm=prompt_llm,
        verbose=False,
        allow_delegation=False,
        max_iter=4,
        reasoning=True,
        max_reasoning_attempts=2,
    )

    qa_reviewer = Agent(
        role="Voice Agent Quality Assurance Specialist",
        goal=(
            "Review all prompts for production readiness: no hallucinated details, "
            "compliance language preserved, natural conversation flow, and consistent tone."
        ),
        backstory=(
            "You review voice AI agents before production deployment. You catch compliance "
            "gaps, hallucinated business details not in the original description, unnatural "
            "phrasing that sounds robotic, and inconsistent tone across nodes. When you "
            "find issues, you fix them directly and explain each fix briefly. Before "
            "passing or failing the prompts you reason through every Tier-1/Tier-2 "
            "source check listed in the hallucination sweep."
        ),
        llm=qa_llm,
        verbose=False,
        allow_delegation=False,
        max_iter=4,
        reasoning=True,
        max_reasoning_attempts=3,
    )

    bounded_context = _bound_context(scraped_link_context)
    scraped_section = ""
    kb_available_note = ""
    if bounded_context:
        scraped_section = f"""

ADDITIONAL CONTEXT FROM REFERENCE LINKS (website, documents, etc.):
{bounded_context}

Use the information above to enrich the business profile — extract services, products,
policies, pricing, FAQs, and any details that would help the voice agent.
Treat this as supplementary to the business description; the description takes priority
if there are conflicts.

IMPORTANT: This same scraped content is also being INDEXED into a runtime Knowledge
Base attached to the workflow. That means any agent node you create can retrieve
this information at call time via the search_knowledge_base tool. Therefore, mark
use_cases as `kb_eligible: true` whenever they require recalling specific facts
from the reference content (services, prices, policies, hours, FAQs, product
specs, eligibility, etc.). Do NOT mark routing-only or pure scheduling use cases
as kb_eligible."""
        kb_available_note = (
            "\n\nKNOWLEDGE BASE IS LIVE: A workflow-scoped knowledge base "
            "containing the full reference-link content is already indexed. "
            "Set `kb_enabled: true` on every agentNode whose duties involve "
            "answering factual questions, citing services, pricing, policies, "
            "hours, FAQs, or any detail likely sourced from the website / docs. "
            "Leave `kb_enabled: false` only for pure routers, schedulers, "
            "or trivial confirmation nodes."
        )

    biz_info_section = ""
    if business_info:
        lines = []
        field_labels = {
            "business_hours": "Business Hours",
            "location": "Location/Address",
            "phone": "Phone",
            "email": "Email",
            "services": "Main Services",
            "policies": "Key Policies",
        }
        for field, label in field_labels.items():
            val = business_info.get(field, "").strip()
            if val:
                lines.append(f"- {label}: {val}")
        if lines:
            biz_info_section = "\n\nSTRUCTURED BUSINESS DATA (treat as DYNAMIC — these values may change):\n" + "\n".join(lines)

    task_analyze = Task(
        description=f"""{variable_policy}

---

Analyze this business and produce a structured Business Profile with all use cases.

Business Name: {business_name}
Call Type: {call_type}
Industry: {industry['display_name']}

Business Description:
{business_description}
{biz_info_section}
{scraped_section}

COMPLIANCE RULES for this industry:
{compliance_rules_text}

KNOWN USE CASES (use as reference, discover MORE from the description):
{use_cases_text}

ANTI-HALLUCINATION RULES (CRITICAL — read carefully):
1. The `name` field MUST be EXACTLY: "{business_name}". Do not rename, polish,
   translate, expand, or substitute it. If the user typed "ufc gym" it stays
   "ufc gym" — never "FitLife Wellness Center", "UFC Gym Inc.", "The UFC Fitness
   Center", or any other variant.
2. Do NOT invent specific facts. If the description / structured data / scraped
   links do not contain a value, OMIT the field entirely or set it to "" — do
   not synthesise plausible-sounding placeholders like fake addresses ("1234
   Main St"), fake phone numbers ("555-123-4567"), or fake hours
   ("Mon–Fri 9 AM–5 PM"). Leaving a field blank is far better than fabricating.
3. For `dynamic_info.hours`, `location`, `phone`, `email`: copy the EXACT value
   from STRUCTURED BUSINESS DATA or from a clearly stated sentence in the
   description / scraped content. If nothing matches, leave the field as "".
4. For `key_offerings` and `unique_details`: only list items you can point to in
   the description or scraped content. No category-typical guesses
   ("smoothie bar", "personal trainers") unless the source actually mentions them.

CRITICAL — USE CASES ARE STRUCTURAL, NOT FACTS (this is the #1 failure to avoid):
The anti-hallucination rules above apply to concrete FACTS (hours, prices,
addresses). They do NOT apply to use cases. A use case describes the KIND of
call this business handles ("Take a reservation", "Answer menu questions",
"Handle a complaint") — that is structural reasoning about the industry, not a
fabricated fact. You MUST therefore NEVER return an empty `use_cases` array.
- If the description is rich, discover use cases from it.
- If the description is sparse (e.g. just a name like "ufc gym") or the scraped
  content is thin, FALL BACK to the standard KNOWN USE CASES for this industry
  listed above and include the 4-8 that any business of this type would handle.
- A {industry['display_name']} business ALWAYS has at least 4 core use cases.
  Returning fewer than 4 is a hard failure.

THINK OUT LOUD ABOUT EDGE CASES (this directly shapes how robust the agent is):
For EACH use case, reason explicitly about what can realistically go wrong in a
spoken conversation, and record those in an `edge_cases` array. Consider, at
minimum, these general failure modes (include the ones that apply, phrased for
THIS use case — do not copy them verbatim):
  - The caller bundles MULTIPLE requests/items into one turn.
  - The caller CHANGES or CORRECTS something they said earlier, including after
    you have already read it back / confirmed it.
  - The caller gives partial, ambiguous, or contradictory information.
  - The caller interrupts, repeats themselves, or jumps to a different intent
    mid-task.
  - The caller asks to cancel or undo part (not all) of the request.
  - The requested thing is unavailable / out of scope and needs a graceful
    fallback or handoff.
Be specific and precise — these edge cases become the explicit handling
instructions the downstream prompt engineer must build into each node.

Return ONLY valid JSON. No markdown. No commentary. Double-quoted keys and strings.
{{
    "business_profile": {{
        "name": "{business_name}",
        "type": "Specific type (only what's in the description / scraped content)",
        "brand_voice": "Tone and personality (inferred from description's tone)",
        "key_offerings": ["only items actually mentioned in the source material"],
        "dynamic_info": {{
            "hours": "exact value from structured data or description, else \\"\\"",
            "location": "exact value from structured data or description, else \\"\\"",
            "phone": "exact value if provided, else \\"\\"",
            "email": "exact value if provided, else \\"\\"",
            "policies": "key policies actually stated, else \\"\\""
        }},
        "unique_details": ["only details actually mentioned, else empty array"],
        "compliance_notes": ["compliance requirements relevant to this industry"]
    }},
    "use_cases": [
        {{"name": "Name", "description": "What it handles", "kb_eligible": false,
          "priority": "high", "routing_hint": "agent",
          "edge_cases": ["Caller adds several items in one turn",
                         "Caller changes a detail after it was read back",
                         "Caller cancels just one part of the request"]}}
    ]
}}

`routing_hint` MUST be one of:
  - "agent"           default conversational handler (most cases).
  - "qualification"   yes/no gate the downstream architect should turn into
                       an ifElse node (e.g. "Verify caller is a member",
                       "Confirm appointment date"). Use when the use case is
                       a single binary decision rather than a back-and-forth.
  - "triage"          3+ way dispatch the architect should turn into a
                       categorize node (e.g. "Route between sales, support
                       and billing"). Only use when there are clearly 3+
                       disjoint sub-cases.
  - "transfer"        live-call handoff to a human / phone / SIP (e.g.
                       "Escalate complex billing to human rep", "Warm
                       transfer to sales closer", "Connect caller to
                       on-call doctor"). Use whenever the business
                       description, scraped content, or compliance notes
                       imply a human in the loop.

You SHOULD include at least one "transfer" use case if the business has any
plausible escalation path — billing disputes, legal questions, sales
closers, on-call medical staff, manager requests — even if it's not
explicitly stated. The architect will wire it as an optional fallback the
user can hook up to a real number later.

Only include use cases relevant to THIS business. A simple business: 4-8 use cases. Complex: 10-15+.""",
        expected_output="A JSON object with business_profile and use_cases arrays.",
        agent=industry_expert,
    )

    # ──────────────────────────────────────────────────────────────────────
    # Branching-node guide — shared by MEETING and standard blueprints.
    #
    # ifElse / categorize / transfer give the architect tools that go beyond
    # plain agentNode chains. They are POWERFUL but should NOT be sprinkled
    # on every workflow — over-using them produces brittle flows where the
    # caller can get stuck in a branch with no recovery path. The rules
    # below tell the architect when each one is justified and when to keep
    # the routing inside an agentNode's exit_conditions instead.
    # ──────────────────────────────────────────────────────────────────────
    branching_guide = """

NODE TYPES YOU CAN USE (besides startCall / agentNode / endCall / globalNode):
You are NOT limited to chains of agentNodes. The following three node types
are first-class and you SHOULD reach for them whenever the workflow has a
qualification gate, an escalation path, or 3+ way routing. Skipping them
when they fit produces clunky, agentNode-heavy graphs that are harder for
the caller to navigate.

1. ifElse — Binary yes/no branch on a runtime condition.
   USE WHEN any of these patterns appears in the use cases:
     - Qualification / eligibility check ("Is the caller a current member?",
       "Did the lead say they have a budget?", "Is the appointment in the
       next 24 hours?").
     - Confirmation gate before a destructive or irreversible action
       ("Did the caller confirm they want to cancel?").
     - Yes/no routing where one branch goes to fulfilment and the other to
       an objection-handling / decline path.
   AVOID WHEN the choice is already two exit_conditions on an agentNode
   (e.g. "task_complete" vs "needs_escalation"). Keep it inside the agent.
   SHAPE:
     {"id": "node-eligibility", "type": "ifElse", "name": "Is Eligible",
      "condition_text": "The caller confirmed they have an active membership."}
   EDGES (condition MUST be exactly "true" or "false"):
     {"source": "node-eligibility", "target": "node-book",    "condition": "true",  "label": "Yes"},
     {"source": "node-eligibility", "target": "node-decline", "condition": "false", "label": "No"}

2. categorize — Multi-way classification (3+ disjoint paths).
   USE WHEN the agent has gathered an intent / topic and needs to dispatch
   to one of 3 OR MORE specialised agents (sales / support / billing /
   scheduling; new patient / returning patient / emergency; etc.).
   AVOID WHEN there are only 2 paths (use ifElse) or when the routing can
   happen directly off startCall via multiple intent exit_conditions.
   SHAPE:
     {"id": "node-triage", "type": "categorize", "name": "Route by Intent",
      "prompt": "Classify the caller's primary intent based on the last few turns.",
      "categories": ["Sales", "Support", "Billing"]}
   EDGES (condition MUST exactly match a category string):
     {"source": "node-triage", "target": "node-sales",   "condition": "Sales",   "label": "Sales"},
     {"source": "node-triage", "target": "node-support", "condition": "Support", "label": "Support"},
     {"source": "node-triage", "target": "node-billing", "condition": "Billing", "label": "Billing"}

3. transfer — Hand off the live call to a phone number / SIP address / human.
   USE WHEN any of these patterns appears:
     - Caller asks for / clearly needs a human.
     - Request is out of scope (legal advice, medical advice, refunds above
       a threshold, complex billing disputes).
     - Industry compliance requires a licensed human to take over.
     - Sales workflows that include a "warm transfer to closer" step.
     - The business description / scraped content mentions a hotline,
       on-call number, or specialist line.
   transfer_target SOURCES (in priority order):
     a. Real number from the business: if the scraped content or
        business_info contains a phone number meant for human contact
        (e.g. the Contact page lists "Sales: +1-555-0100"), copy it
        verbatim into `transfer_target`.
     b. Dynamic from an upstream agent: if an agentNode extracts a
        phone-like variable into context (e.g. a callback number the
        caller dictates, or a routing number looked up from a CRM tool),
        reference it with a template — `transfer_target: "{phone_number}"`
        or `transfer_target: "{specialist_phone}"`. The engine substitutes
        the variable at runtime from the call's context.
     c. Empty string: only when neither (a) nor (b) applies. The user
        wires the destination in the UI before going live. Do NOT invent a
        number — fabricated phone numbers are a critical regression.
   AVOID inventing a phone number under any circumstance.
   SHAPE (NO outgoing edges — this node terminates the agent's leg):
     {"id": "node-transfer-human", "type": "transfer", "name": "Transfer to Human",
      "prompt": "Please hold while I connect you with a specialist who can help.",
      "transfer_target": "",
      "is_literal": true}
   DYNAMIC EXAMPLE (when an upstream agent collects a callback number):
     {"id": "node-callback-transfer", "type": "transfer", "name": "Call Back Caller",
      "prompt": "Thanks — we'll call you right back at the number you provided.",
      "transfer_target": "{callback_number}",
      "is_literal": true}
   INCOMING EDGE (typically from an agentNode exit named like "needs_human"):
     {"source": "node-billing", "target": "node-transfer-human",
      "condition": "needs_human", "label": "Needs Human"}

────────────────────────────────────────────────────────────────────────
SELF-CHECK BEFORE YOU EMIT THE BLUEPRINT — ask yourself each of these:
  Q1. Does any use case involve a yes/no qualification or confirmation
      gate? If YES, place an ifElse between the gathering agentNode and
      the two downstream agents.
  Q2. Does the workflow have ≥3 distinct caller intents that each need
      a dedicated agentNode after the initial gather? If YES, add a
      categorize node to route between them (instead of one mega-agent
      with 5 exit conditions).
  Q3. Does the business have ANY escalation path — billing disputes,
      legal questions, sales closers, on-call doctors, manager requests?
      If YES, add a transfer node connected from the relevant agentNode
      via a `needs_human` (or similarly named) exit. Use transfer_target
      = "" so the user can plug in the real number from the UI.
  Q4. Does any use case involve COLLECTING or BUILDING something over
      multiple turns (an order, a booking, a list of items, a form)?
      The `edge_cases` from the analysis will tell you. If YES, that
      agentNode MUST be re-enterable so the caller can change/correct/
      cancel an item WITHOUT the flow breaking. Give it a self-loop or a
      `revise`-style exit that returns to the SAME node, and make sure
      every downstream confirmation node has an edge BACK to the
      collecting node (condition like "wants_changes") so a correction
      after read-back is always possible. Never design a strictly linear
      chain for multi-step collection — that is exactly what breaks when
      the caller says "actually, change that".

If the answer to Q1/Q2/Q3/Q4 is YES, you MUST include the corresponding
node / routing. Leaving these out when they apply is a regression — the
user has the nodes available in the UI and expects the architect to use
them. In particular, a confirmation/summary node with no path back to the
collection node is a defect: it traps callers who want to make a change.
────────────────────────────────────────────────────────────────────────

REFERENCE EXAMPLE (gym membership workflow with all three node types):
  nodes:
    {"id": "node-global", "type": "globalNode", "name": "Global Prompt"}
    {"id": "node-start",  "type": "startCall",  "name": "Greeting",
     "exit_conditions": [
       {"name": "membership_inquiry", "llm_description": "Caller wants info or to sign up"},
       {"name": "billing_issue",      "llm_description": "Caller has a billing question"},
       {"name": "user_wants_to_end",  "llm_description": "Caller wants to end the call"}]}
    {"id": "node-qualify", "type": "agentNode", "name": "Qualify Lead", "kb_enabled": true,
     "exit_conditions": [
       {"name": "info_gathered",      "llm_description": "Got goal, schedule, budget"},
       {"name": "user_wants_to_end",  "llm_description": "Caller wants to end"}]}
    {"id": "node-budget-ok", "type": "ifElse", "name": "Budget In Range",
     "condition_text": "The caller's stated budget is at or above the standard membership tier."}
    {"id": "node-signup",   "type": "agentNode", "name": "Sign Up", "kb_enabled": true, "exit_conditions": [...]}
    {"id": "node-nurture",  "type": "agentNode", "name": "Offer Trial", "kb_enabled": true, "exit_conditions": [...]}
    {"id": "node-billing",  "type": "agentNode", "name": "Billing Support", "kb_enabled": true,
     "exit_conditions": [
       {"name": "task_complete",     "llm_description": "Resolved"},
       {"name": "needs_human",       "llm_description": "Needs a human billing rep"},
       {"name": "user_wants_to_end", "llm_description": "Caller wants to end"}]}
    {"id": "node-transfer", "type": "transfer", "name": "Transfer to Billing Team",
     "prompt": "Thanks for your patience — let me get you to a billing specialist right away.",
     "transfer_target": "", "is_literal": true}
    {"id": "node-end", "type": "endCall", "name": "End Call"}
  edges:
    {"source": "node-start",     "target": "node-qualify", "condition": "membership_inquiry"}
    {"source": "node-start",     "target": "node-billing", "condition": "billing_issue"}
    {"source": "node-qualify",   "target": "node-budget-ok", "condition": "info_gathered"}
    {"source": "node-budget-ok", "target": "node-signup",  "condition": "true",  "label": "Yes"}
    {"source": "node-budget-ok", "target": "node-nurture", "condition": "false", "label": "No"}
    {"source": "node-billing",   "target": "node-transfer","condition": "needs_human"}
    {"source": "node-signup",    "target": "node-end",     "condition": "task_complete"}
    {"source": "node-nurture",   "target": "node-end",     "condition": "task_complete"}
    {"source": "node-billing",   "target": "node-end",     "condition": "task_complete"}
    {"source": "node-start",     "target": "node-end",     "condition": "user_wants_to_end"}
This example uses ifElse (budget gate), transfer (billing escalation), and
keeps the graph small — only 9 nodes. The standard agentNode-only version
of this workflow would need ~13 nodes and tangled edges."""

    # ──────────────────────────────────────────────────────────────────────
    # Extraction-variable guide — tells the architect how to turn a
    # data-collecting agentNode into structured variables the user can wire
    # into integrations (calendar, CRM, email, webhooks) with no extra setup.
    # These map 1:1 onto the app's existing per-node extraction schema
    # (extraction_enabled / extraction_variables) and become {{name}}
    # placeholders the action panels expose automatically.
    # ──────────────────────────────────────────────────────────────────────
    extraction_guide = """
EXTRACTION VARIABLES (turn what the agent hears into structured, reusable data):
For each agentNode where you set "extraction_enabled": true, add an
"extraction_variables" array. Each entry has this exact shape:
    {"name": "snake_case_key", "type": "string", "prompt": "what to capture", "required": true}

Rules:
- "name" MUST be snake_case (it is used directly as a {{name}} placeholder in
  integrations, so keep it clean: caller_name, phone, email, party_size,
  reservation_date, reservation_time, order_items, address, callback_number).
- "type" MUST be exactly one of: "string", "number", "boolean".
- "prompt" is a short instruction describing the value to pull from the
  conversation.
- "required" marks whether the field is CRITICAL (true) or OPTIONAL (false):
    * required=true  → the agent MUST collect it before moving on; it gates the
      node. Use for the essentials the business genuinely needs (a booking's
      date/time, a lead's phone).
    * required=false → still extracted if the caller mentions it, but it NEVER
      blocks the flow. Use for nice-to-haves (special_requests, dietary_notes,
      secondary_email, preferred_contact_time).
  Mark a field optional whenever a caller could reasonably decline it — this
  stops the agent getting stuck demanding non-essential info.
- KEEP REQUIRED VARIABLES MINIMAL: mark AT MOST 2-3 variables as required=true
  across the ENTIRE workflow — only the few the business absolutely cannot
  operate without. Everything else MUST be required=false. A shorter required
  list keeps the call natural and fast; the agent should never feel like a form.
- DEFINE THE OTHER USEFUL VARIABLES ANYWAY (as required=false). They are NOT
  wasted: every variable you define is automatically listed as a suggestion in
  the "Call Variables" hub, where the user can add/promote the ones they care
  about themselves. So generate a generous set of optional variables, but only
  2-3 required ones.
- REUSE the same variable names across nodes for the same concept so a value
  collected early (e.g. caller_name, phone) flows cleanly into later
  integration steps.
- Typical sets by intent: a booking → caller_name (required), party_size
  (required), reservation_date (required), reservation_time (required),
  special_requests (optional); a lead capture → caller_name (required), phone
  (required), email (optional), interest (optional); an order → caller_name
  (required), phone (required), order_items (required), address (required),
  delivery_notes (optional).

This is what makes integrations plug-and-play: the user connects their tool
(Google Calendar, a CRM webhook, an email action) and drops in {{caller_name}},
{{reservation_date}}, etc. without configuring extraction by hand.

POST-CALL DATA HUB: you do NOT need to repeat variables anywhere for post-call
use. The system automatically adds a dedicated "Call Variables" hub node right
after the End node and surfaces EVERY variable collected anywhere in the flow on
it. That hub is where the user attaches post-call integration actions (calendar,
CRM, email, webhooks) and references {{caller_name}}, {{reservation_date}}, etc.
Just define each variable once, on the agentNode that actually collects it — do
NOT add extraction_variables to the endCall node."""

    if call_type == "MEETING":
        blueprint_rules = f"""Using the business analysis from the previous task, design a workflow blueprint for a MEETING ASSISTANT.

RULES FOR MEETING AGENTS:
1. ALWAYS include: one globalNode, one startCall, one endCall
2. The startCall is the ENTRY POINT — it has NO greeting. The agent stays SILENT until called by a wake word.
3. The startCall prompt should instruct the agent: "You are a meeting assistant. Stay silent and listen. Only respond when someone calls you by name. When called, answer concisely using your knowledge."
4. The startCall acts as a ROUTER — when the user asks a question (after wake word), route to the appropriate knowledge agent.
5. Each knowledge area / expertise becomes one agentNode with kb_enabled=true
6. Agent nodes should be focused areas of expertise (e.g., "Financial Data", "Product Info", "Policy Expert", "Meeting Notes")
7. EVERY agentNode MUST have: "answered" exit → node-start (loop back to listening) AND "follow_up" exit to related agents
8. The endCall should say something brief like "Meeting assistance ended."
9. {fixed_pattern_text}
{branching_guide}

Return ONLY valid JSON. No markdown. Double-quoted keys and strings.
{{
    "nodes": [
        {{"id": "node-global", "type": "globalNode", "name": "Meeting Assistant Context"}},
        {{"id": "node-start", "type": "startCall", "name": "Listen & Route",
          "exit_conditions": [{{"name": "topic_name", "llm_description": "When user asks about X"}}]}},
        {{"id": "node-agent", "type": "agentNode", "name": "Knowledge Area", "kb_enabled": true,
          "exit_conditions": [
            {{"name": "answered", "llm_description": "Question answered, return to listening"}},
            {{"name": "follow_up", "llm_description": "User has a follow-up question"}}
          ]}},
        {{"id": "node-end", "type": "endCall", "name": "End Assistance"}}
    ],
    "edges": [
        {{"source": "node-start", "target": "node-agent", "condition": "topic_name", "label": "Topic"}},
        {{"source": "node-agent", "target": "node-start", "condition": "answered", "label": "Back to Listening"}}
    ]
}}

Node IDs: lowercase with hyphens. Every edge condition MUST match a source node exit_condition name (for
agentNode/startCall) OR a "true"/"false" handle (for ifElse) OR a category string (for categorize).
The agent MUST loop back to node-start after answering so it can listen for the next question.{kb_available_note}"""
    else:
        blueprint_rules = f"""Using the business analysis from the previous task, design a workflow blueprint.

RULES:
1. ALWAYS include: one globalNode, one startCall, one endCall
2. The startCall routes to the right agent based on caller intent
3. Each use case maps to ONE node: usually an agentNode, but use ifElse for
   yes/no qualification gates, categorize for 3+ way dispatch, and transfer
   for human handoff. Do NOT default every step to an agentNode — read the
   self-check questions in the branching-node guide below.
4. EVERY agentNode MUST have: "task_complete" exit → endCall AND "user_wants_to_end" exit → endCall
5. The startCall MUST have one exit per agent it routes to, plus "user_wants_to_end"
6. Call type: {call_type} (INBOUND=router pattern, OUTBOUND=sequential, WEBSITE=web-friendly)
7. {fixed_pattern_text}
8. DATA CAPTURE FOR INTEGRATIONS: for every agentNode that COLLECTS specific
   data the business will need afterwards (a reservation, an order, a lead's
   contact details, an appointment, a support ticket), set
   "extraction_enabled": true and list the fields under "extraction_variables".
   These become reusable variables the user can plug straight into integrations
   (calendar, CRM, email, webhooks, sheets) with zero extra setup — referenced
   as {{{{variable_name}}}}. Do NOT enable extraction on pure Q&A, routing, or
   info-only nodes (e.g. "Answer menu questions") — they collect nothing.
{branching_guide}
{extraction_guide}

Return ONLY valid JSON. No markdown. Double-quoted keys and strings.
{{
    "nodes": [
        {{"id": "node-global", "type": "globalNode", "name": "Global Prompt"}},
        {{"id": "node-start", "type": "startCall", "name": "Greeting",
          "exit_conditions": [{{"name": "intent_name", "llm_description": "When caller wants X"}}]}},
        {{"id": "node-agent", "type": "agentNode", "name": "Collect Reservation", "kb_enabled": false,
          "extraction_enabled": true,
          "extraction_variables": [
            {{"name": "caller_name", "type": "string", "prompt": "The caller's full name", "required": true}},
            {{"name": "party_size", "type": "number", "prompt": "How many people in the party", "required": true}},
            {{"name": "reservation_date", "type": "string", "prompt": "The date requested for the booking", "required": true}},
            {{"name": "special_requests", "type": "string", "prompt": "Any special requests (optional)", "required": false}}
          ],
          "exit_conditions": [
            {{"name": "task_complete", "llm_description": "Task done"}},
            {{"name": "user_wants_to_end", "llm_description": "Caller wants to end"}}
          ]}},
        {{"id": "node-end", "type": "endCall", "name": "End Call"}}
    ],
    "edges": [
        {{"source": "node-start", "target": "node-agent", "condition": "intent_name", "label": "Intent"}}
    ]
}}

Node IDs: lowercase with hyphens. Every edge condition MUST match a source node exit_condition name (for
agentNode/startCall) OR a "true"/"false" handle (for ifElse) OR a category string (for categorize).{kb_available_note}"""

    task_blueprint = Task(
        description=f"{variable_policy}\n\n---\n\n{blueprint_rules}",
        expected_output="A JSON object with nodes and edges arrays forming the workflow blueprint.",
        agent=workflow_architect,
    )

    biz_info_prompt_note = ""
    if business_info:
        biz_info_prompt_note = """
IMPORTANT — DYNAMIC BUSINESS DATA:
The business provided structured operational details (hours, location, phone, services, policies).
When writing prompts, reference these details naturally (e.g., "Our hours are..." or "We're located at...")
but write them in a way that reads the ACTUAL values from the business profile rather than inventing
or paraphrasing. Use the exact hours, address, phone number, and policies provided. These may be updated
later, so the prompts should clearly state these facts so they are easy to find and edit."""

    # This block ALWAYS goes into the prompt engineer instructions, regardless
    # of whether structured business_info was provided. It's the primary
    # defence against the LLM inventing fictional addresses / phone numbers /
    # alternate business names like "FitLife Wellness Center".
    anti_hallucination_block = f"""

ANTI-HALLUCINATION RULES (NON-NEGOTIABLE):
- The business name in every prompt MUST be EXACTLY "{business_name}". Never
  invent a different name. Never "polish" it. If the user typed "ufc gym",
  the agent says "ufc gym" — not "FitLife Wellness Center", not
  "UFC Wellness Center", not "The UFC Fitness Group".
- A concrete fact (address, phone, email, hours, price, named service) is
  only allowed in the prompt if it comes from ONE of these sources:
    1. The PROVIDED list at the top of this task (Tier-1).
    2. The original business description.
    3. The SCRAPED CONTENT / knowledge base above (Tier-2) — e.g. a phone
       number on the Contact page, hours on the About page, an address in
       the footer. Quote it verbatim if it appears there.
  If the value lives in NONE of those, do NOT write it. No "1234 Health
  Drive", no "555-123-4567", no "Monday through Friday 9 AM to 5 PM"
  placeholders.
- When a fact is missing from every source, use generic phrasing:
    * Hours missing → "during our regular business hours"
    * Address missing → "at our location" or omit entirely
    * Phone missing → "you can reach our team" (no number)
    * Services missing → describe only what IS in the source
- The greeting MUST identify the business by its real name and what the
  caller is calling about ("Hi, thanks for calling {business_name}…"),
  but it must NOT include invented operational details.
- If you find yourself writing a number, an address, or specific hours,
  STOP and confirm the exact value appears in one of the three sources
  listed above. If not, remove it.
- REMEMBER: the runtime agent has a `search_knowledge_base` tool. If a
  caller asks for something we don't know at prompt-build time, the agent
  can look it up live. So it's safe — and preferred — to omit a fact now
  rather than fabricate one."""

    # Branching nodes are NOT conversational — they either silently evaluate
    # a condition (ifElse / categorize) or speak a short literal handoff
    # message (transfer). Telling the prompt engineer to write long
    # conversational scripts for them produces garbage. This block is
    # appended to both MEETING and standard prompt instructions.
    branching_prompt_note = """

BRANCHING NODE HANDLING (only applies if the blueprint contains these types):
- ifElse nodes have NO `prompt` field; their `condition_text` is set by the
  architect. Emit an empty string ("") for ifElse node IDs.
- categorize nodes: emit a SHORT classification instruction (1-2 sentences,
  max ~40 words) like "Classify the caller's intent based on the most recent
  turns of the conversation and pick the best-matching category." Do NOT write
  a conversational script — the node never speaks to the caller.
- transfer nodes: emit a SHORT spoken handoff line (1-2 sentences, max ~30
  words), e.g. "Please hold while I transfer you to a specialist who can help."
  Never invent the destination name or phone number — keep it generic."""

    # General, domain-agnostic robustness block. The Industry Expert emits an
    # `edge_cases` array per use case; this tells the prompt engineer to turn
    # those into concrete in-prompt handling so the agent doesn't break when a
    # caller changes their mind, bundles requests, or corrects a confirmed
    # detail. Written generically so it works for orders, bookings,
    # appointments, applications, support tickets — any multi-step collection.
    state_edge_case_block = """

ROBUST STATE & EDGE-CASE HANDLING (apply to every agentNode that collects,
builds, or modifies something over multiple turns — orders, bookings,
appointments, lists, forms, applications):
The Business Profile lists `edge_cases` for each use case. You MUST translate
the relevant ones into explicit instructions inside the node prompt. At a
minimum, every collection/modification prompt must tell the agent to:
  1. MAINTAIN A RUNNING STATE: keep an internal, ordered summary of everything
     the caller has requested so far (each item + its details/quantity). Treat
     this as the single source of truth for the rest of the call.
  2. HANDLE MULTIPLE ITEMS IN ONE TURN: if the caller lists several things at
     once, capture each one separately into the running state — do not collapse
     or drop any.
  3. ALLOW CHANGES AT ANY TIME — INCLUDING AFTER READ-BACK: if the caller says
     "actually…", "change…", "make that…", "remove…", "cancel the…", locate the
     SPECIFIC item they mean and modify ONLY that item. Never overwrite,
     duplicate, or reset the other items. If it's ambiguous which item they
     mean, ask one short clarifying question first.
  4. NO OVERLAP / NO DUPLICATES: when modifying an item, replace it in place;
     do not silently add a second conflicting copy.
  5. READ BACK AFTER EVERY CHANGE: after each addition or modification, briefly
     restate the COMPLETE current state ("So right now I have: …") and ask if
     that's correct or if they'd like anything else.
  6. CONFIRM BEFORE FINALIZING: before completing the task, read back the full
     final summary once and get an explicit yes. If they say no / want a change,
     loop back into collection (do not proceed to the end).
  7. GRACEFUL UNAVAILABLE/OUT-OF-SCOPE: if something requested isn't available
     or is out of scope, say so plainly and offer the closest alternative or a
     handoff — never pretend it was captured.
Write these as natural spoken instructions woven into the prompt, NOT as a
numbered checklist the agent reads aloud. Be precise about the "change after
confirmation" case — that is the most common way these agents break."""

    if call_type == "MEETING":
        prompt_instructions = f"""Using the business profile and workflow blueprint from previous tasks, write prompts for EVERY node.

This is a MEETING ASSISTANT agent. Your prompts must:
- Be written for an AI that sits SILENTLY in a meeting and only speaks when called
- For startCall (Listen & Route): Instruct the agent to stay completely silent and listen. It should ONLY respond when explicitly called by name/wake word. When called, identify the topic and route to the right knowledge agent. NO greeting — the agent is a silent participant.
- For agentNodes: Write concise, knowledge-focused prompts. The agent should answer questions briefly and professionally, using its knowledge base. After answering, it should return to silent listening mode. Responses should be 1-3 sentences max.
- For endCall: A brief "Meeting assistance ended" — no lengthy goodbye.
- For globalNode: Define the assistant's expertise areas, knowledge base context, tone (professional, concise), and the rule that it MUST stay silent unless called. Include relevant business/domain context.
- All prompts should emphasize BREVITY — meeting time is precious
- ONLY reference information from the business profile. Do NOT invent details.
{biz_info_prompt_note}
{anti_hallucination_block}
{branching_prompt_note}

Compliance rules to incorporate:
{compliance_rules_text}"""
    else:
        prompt_instructions = f"""Using the business profile and workflow blueprint from previous tasks, write prompts for EVERY node.

Your prompts must:
- Sound natural when spoken aloud (PHONE/VOICE conversation, not text)
- Include specific business details (name, services, key info) from the profile
- Use the exact hours, location, phone, and policies from the business profile — do NOT paraphrase or approximate
- Ask one question at a time, confirm details by reading them back
- Handle edge cases (confused caller, angry caller, unclear request)
- Be 150-400 words each for agentNode / startCall / endCall / globalNode
- For startCall: prompt IS the greeting — start with natural spoken greeting
- For endCall: warm, context-appropriate goodbye
- For globalNode: business persona, tone, key policies for ALL agents — include ONLY hours, location, and contact details that exist in the business profile. If they are missing, omit them.
- ONLY reference information from the business profile. Do NOT invent details.
{biz_info_prompt_note}
{anti_hallucination_block}
{branching_prompt_note}
{state_edge_case_block}

Compliance rules to incorporate:
{compliance_rules_text}"""

    task_prompts = Task(
        description=f"{variable_policy}\n\n---\n\n" + prompt_instructions + f"""

Return ONLY valid JSON. No markdown. Double-quoted keys and strings.
{{
    "prompts": {{
        "node-id-1": "Full prompt text...",
        "node-id-2": "Full prompt text..."
    }}
}}

You MUST include a prompt for every single node in the blueprint.""",
        expected_output="A JSON object mapping each node ID to its complete prompt text.",
        agent=prompt_engineer,
    )

    qa_anti_hallucination_block = f"""

HALLUCINATION SWEEP (run this BEFORE any other checks — fix violations in place):

A "source" for the purposes of these checks is ANY of:
  1. The PROVIDED list at the top of this task (Tier-1: structured business_info).
  2. The original business description.
  3. The SCRAPED CONTENT / knowledge-base text shown above (Tier-2). Phone
     numbers on a Contact page, hours on an About page, addresses in a
     footer all count as authoritative when they appear there explicitly.

A. Business name: every prompt must reference the business as EXACTLY
   "{business_name}". If any prompt uses a different name (e.g. invented
   "FitLife Wellness Center" when the user said "ufc gym"), rewrite that
   prompt so the business name is "{business_name}" everywhere.
B. Addresses / phone numbers / emails: scan each prompt for digits, street
   suffixes (St, Ave, Drive, Blvd, Road, Way), area codes, and "@". For each
   one, verify the exact value appears in a source (see definition above). If
   it does NOT, DELETE that fact from the prompt or replace it with generic
   phrasing ("at our location", "you can reach our team", "during our business
   hours"). Do NOT keep fabricated "1234 Main St" / "555-123-4567" placeholders.
C. Hours: any "Monday through Friday from X to Y" / "9 AM to 5 PM" must come
   verbatim from a source. Otherwise replace with "during regular business
   hours" or remove the sentence.
D. Services / products: each named offering must appear in a source. Strip
   any that don't (e.g. don't claim the gym has a "smoothie bar" or
   "personal trainers" unless the description or scraped content says so).
E. Record every fix you made in `fixes_applied`. If you found zero issues,
   leave `fixes_applied` as `[]` and return the prompts unchanged."""

    qa_branching_note = """

BRANCHING NODE PROMPT RULES (these node types are silent or near-silent — do NOT
treat them like conversational agents):
- ifElse nodes: their prompt MUST be an empty string (""). They route silently on
  a condition; never give them a spoken prompt. If you see prose on an ifElse node,
  replace it with "".
- categorize nodes: keep the prompt a SHORT classification instruction (1-2
  sentences). It is never spoken to the caller. Trim anything verbose.
- transfer nodes: keep the prompt a SHORT spoken handoff line (≤30 words), e.g.
  "Please hold while I connect you to a specialist." Do NOT add a phone number to
  the spoken line (the destination lives in transfer_target, not the prompt)."""

    if call_type == "MEETING":
        qa_checklist = f"""{variable_policy}

---

Review ALL prompts from the previous task against this MEETING AGENT checklist:
{qa_anti_hallucination_block}
{qa_branching_note}

1. Does each prompt ONLY reference information from the business description and structured data? (No hallucinated details)
2. Is industry compliance language present? Rules:
{compliance_rules_text}
3. Does the startCall have NO greeting? It should instruct the agent to stay SILENT until called.
4. Are agent node responses concise (1-3 sentences)? Meeting assistants must be brief.
5. Do agent nodes loop back to the listening state after answering?
6. Does the globalNode clearly define the assistant's expertise and the wake-word-only rule?
7. Is the endCall brief (not a lengthy phone-style goodbye)?
8. Is tone professional and concise across all nodes?"""
    else:
        qa_checklist = f"""{variable_policy}

---

Review ALL prompts from the previous task against this checklist:
{qa_anti_hallucination_block}
{qa_branching_note}

1. Does each prompt ONLY reference information from the business description and structured data? (No hallucinated hours, prices, products)
2. Are business hours, location, phone, and policies accurately stated using the EXACT values provided (not approximated or invented)? If a value was never provided, the prompt must NOT contain a fabricated stand-in.
3. Is industry compliance language present? Rules:
{compliance_rules_text}
4. Does each prompt sound natural when read aloud?
5. Are exit conditions well-supported by the prompt instructions?
6. Is tone consistent across all nodes?
7. Does startCall greeting match call type ({call_type}) and greet the caller using the EXACT business name "{business_name}"?
8. Does globalNode include business identity (using "{business_name}" verbatim) and ONLY the operational facts that were actually provided?
9. Does endCall have a warm goodbye?
10. EDGE-CASE / STATE ROBUSTNESS: for every node that collects or modifies
    something over multiple turns (order, booking, appointment, list, form),
    does the prompt explicitly tell the agent to (a) keep a running summary of
    the current state, (b) let the caller change/correct/cancel a SPECIFIC item
    at any time — including after read-back — without overwriting or duplicating
    the others, (c) read back the full updated state after each change, and
    (d) confirm the complete summary before finalizing? If any of these are
    missing on such a node, ADD them. This is the most common way these agents
    break, so treat a missing change-after-confirmation path as a defect to fix."""

    task_qa = Task(
        description=qa_checklist + """

If a prompt has issues, FIX IT directly. Return ALL prompts (fixed + unchanged).

Return ONLY valid JSON. No markdown. Double-quoted keys and strings.
{
    "prompts": {
        "node-id-1": "Final reviewed prompt...",
        "node-id-2": "Final reviewed prompt..."
    },
    "fixes_applied": ["Description of each fix, or empty if none"]
}""",
        expected_output="A JSON object with all reviewed/fixed prompts and a list of fixes applied.",
        agent=qa_reviewer,
    )

    crew = Crew(
        agents=[industry_expert, workflow_architect, prompt_engineer, qa_reviewer],
        tasks=[task_analyze, task_blueprint, task_prompts, task_qa],
        process=Process.sequential,
        verbose=False,
        memory=False,  # keep deterministic + memory-light; we don't want cross-run memory
    )

    return crew


async def run_industry_crew(
    industry_key: str,
    business_name: str,
    business_description: str,
    call_type: str,
    user_id: Optional[int] = None,
    scraped_link_context: Optional[str] = None,
    business_info: Optional[dict[str, str]] = None,
) -> dict:
    """
    Execute the full 4-agent CrewAI crew and return a complete workflow_definition.

    Returns: {"name": str, "workflow_definition": dict}
    """
    import asyncio

    if industry_key not in INDUSTRY_REGISTRY:
        raise ValueError(f"Unknown industry: {industry_key}")

    industry = INDUSTRY_REGISTRY[industry_key]

    has_links = bool(scraped_link_context)
    logger.info(
        f"[IndustryCrew] Starting CrewAI crew for {industry_key}: {business_name} "
        f"(links={has_links}, description={len(business_description)} chars)"
    )

    crew = _build_crew(
        industry_key, business_name, business_description, call_type,
        scraped_link_context=scraped_link_context,
        business_info=business_info,
    )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, crew.kickoff)

    logger.info("[IndustryCrew] CrewAI crew finished, parsing outputs")

    task_outputs = result.tasks_output if hasattr(result, "tasks_output") else []

    # Task 1: business profile (informational logging only)
    if len(task_outputs) >= 1:
        try:
            expert_data = _parse_json_from_output(task_outputs[0].raw)
            use_case_count = len(expert_data.get("use_cases", []))
            logger.info(f"[IndustryCrew] Expert found {use_case_count} use cases")
        except Exception as e:
            logger.warning(f"[IndustryCrew] Could not parse expert output: {e}")

    # Task 2: blueprint (required)
    blueprint: Optional[dict] = None
    if len(task_outputs) >= 2:
        try:
            blueprint = _parse_json_from_output(task_outputs[1].raw)
            _validate_blueprint(blueprint)
        except Exception as e:
            logger.error(f"[IndustryCrew] Failed to parse blueprint: {e}")

    if not blueprint:
        raise ValueError("Workflow Architect failed to produce a valid blueprint")

    # Task 4: QA-reviewed prompts (preferred), fall back to Task 3 (prompt engineer)
    final_prompts: dict[str, str] = {}
    if len(task_outputs) >= 4:
        try:
            qa_data = _parse_json_from_output(task_outputs[3].raw)
            final_prompts = qa_data.get("prompts", {}) or {}
            fixes = qa_data.get("fixes_applied", [])
            if fixes:
                logger.info(f"[IndustryCrew] QA applied {len(fixes)} fixes")
        except _NoJsonInOutput:
            # Normal path: QA returned an approval paragraph saying "no fixes
            # needed" — fall back to the prompt engineer's output silently.
            logger.info(
                "[IndustryCrew] QA returned approval prose (no fixes) — "
                "using prompt engineer output as-is"
            )
        except Exception as e:
            logger.warning(f"[IndustryCrew] Could not parse QA output: {e}, trying prompt engineer output")

    if not final_prompts and len(task_outputs) >= 3:
        try:
            pe_data = _parse_json_from_output(task_outputs[2].raw)
            final_prompts = pe_data.get("prompts", {}) or {}
        except Exception as e:
            logger.warning(f"[IndustryCrew] Prompt engineer fallback also failed: {e}")

    # Fill in any missing prompts with safe fallbacks (never leave a node blank)
    final_prompts = _ensure_all_prompts(blueprint, final_prompts)

    workflow_def = assemble_workflow_definition(blueprint, final_prompts)

    node_count = len(blueprint.get("nodes", []))
    logger.info(f"[IndustryCrew] Complete: {business_name} ({node_count} nodes)")

    return {
        "name": business_name,
        "workflow_definition": workflow_def,
    }
