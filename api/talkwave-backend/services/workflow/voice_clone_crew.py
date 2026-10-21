"""
Voice Agent Cloning crew.

Analyzes transcripts of real human agent calls and reverse-engineers
a complete workflow that mimics the human's conversational patterns.

Uses 4 sequential CrewAI agents:
  1. Conversation Analyst  — Extracts personality, tone, techniques
  2. Decision Tree Mapper  — Maps decision-making into branches/conditions
  3. Workflow Builder      — Converts the tree into a node/edge blueprint
  4. Prompt Writer         — Writes prompts that capture the human's style
"""

import json
import uuid
from typing import Optional

from loguru import logger

from api.services.workflow.industry_templates import assemble_workflow_definition


def _parse_json_from_output(text: str) -> dict:
    """Extract JSON from CrewAI task output."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start >= 0 and end > start:
        cleaned = cleaned[start:end]
    return json.loads(cleaned)


def _validate_blueprint(blueprint: dict) -> None:
    """Add missing IDs and fix common issues."""
    node_ids = set()
    for n in blueprint.get("nodes", []):
        if "id" not in n:
            n["id"] = f"node-{uuid.uuid4().hex[:8]}"
        node_ids.add(n["id"])
        for ec in n.get("exit_conditions", []):
            if "id" not in ec:
                ec["id"] = f"exit-{uuid.uuid4().hex[:8]}"
    valid_edges = []
    for e in blueprint.get("edges", []):
        if e.get("source") in node_ids and e.get("target") in node_ids:
            if "id" not in e:
                e["id"] = f"edge-{uuid.uuid4().hex[:8]}"
            valid_edges.append(e)
    blueprint["edges"] = valid_edges


def _build_clone_crew(
    transcripts: list[str],
    business_name: str,
    call_type: str,
):
    """Build the 4-agent cloning crew."""
    from crewai import Agent, Crew, Process, Task

    from api.services.workflow.industry_crew import _get_llm_model_string

    llm_model = _get_llm_model_string()

    transcripts_block = ""
    for i, t in enumerate(transcripts, 1):
        truncated = t[:4000] if len(t) > 4000 else t
        transcripts_block += f"\n--- Recording #{i} ---\n{truncated}\n"

    # --- Agent 1: Conversation Analyst ---
    conversation_analyst = Agent(
        role="Human Agent Conversation Analyst",
        goal=(
            "Analyze recordings of a real human agent to extract their personality, "
            "communication style, techniques, and the business information they reference."
        ),
        backstory=(
            "You are an expert at studying human communication patterns. You can identify "
            "a person's tone, vocabulary, empathy techniques, objection handling, closing "
            "strategies, and conversational rhythm from transcripts. You notice subtle "
            "patterns that make one agent more effective than another."
        ),
        llm=llm_model,
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )

    # --- Agent 2: Decision Tree Mapper ---
    decision_mapper = Agent(
        role="Conversational Decision Tree Mapper",
        goal=(
            "Map the human agent's decision-making process into a structured decision "
            "tree with branches, conditions, and outcomes."
        ),
        backstory=(
            "You analyze conversation transcripts to find the hidden structure — what "
            "questions does the agent ask to determine the next step? What triggers "
            "escalation? What causes them to offer alternatives? You turn organic human "
            "conversations into structured decision flows."
        ),
        llm=llm_model,
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )

    # --- Agent 3: Workflow Builder ---
    workflow_builder = Agent(
        role="Voice AI Workflow Architect",
        goal=(
            "Convert the decision tree into a concrete workflow blueprint with nodes, "
            "exit conditions, and edge connections."
        ),
        backstory=(
            "You design multi-node voice agent workflows. You know node types: startCall "
            "(greeting + router), agentNode (handles a specific topic), endCall (goodbye), "
            "globalNode (business persona). You create proper exit conditions and edge "
            "routing to replicate human decision-making patterns."
        ),
        llm=llm_model,
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )

    # --- Agent 4: Prompt Writer ---
    prompt_writer = Agent(
        role="Voice AI Conversation Cloner",
        goal=(
            "Write prompts for every workflow node that capture the human agent's specific "
            "style — their vocabulary, tone, pacing, personality, and techniques."
        ),
        backstory=(
            "You write voice agent prompts that sound like a specific person. You study "
            "their word choices, how they open conversations, how they handle silence, "
            "how they confirm information, and their unique phrases. Your prompts, when "
            "spoken by TTS, should feel like talking to the same person."
        ),
        llm=llm_model,
        verbose=False,
        allow_delegation=False,
        max_iter=5,
    )

    # --- Task 1: Analyze Conversations ---
    task_analyze = Task(
        description=f"""Analyze these transcripts of a real human agent at "{business_name}" and extract their complete communication profile.

TRANSCRIPTS:
{transcripts_block}

Identify:
1. Personality & Tone: formal/casual, warm/professional, pace, energy level
2. Greeting patterns: how they open calls, first impression style
3. Information gathering: what questions they ask, in what order
4. Objection handling: how they respond to pushback, concerns, complaints
5. Closing technique: how they wrap up conversations, create next steps
6. Empathy patterns: phrases used for empathy, de-escalation, reassurance
7. Unique phrases: specific words, idioms, or patterns they repeat
8. Business knowledge: what facts/policies/prices they reference
9. Error recovery: how they handle misunderstandings or confusion

Return ONLY valid JSON:
{{
    "agent_profile": {{
        "personality": "Warm, patient, uses first names, conversational pace",
        "tone": "Professional but friendly",
        "greeting_style": "How they open calls",
        "closing_style": "How they end calls",
        "unique_phrases": ["phrase 1", "phrase 2"],
        "empathy_patterns": ["When caller is upset, agent says..."],
        "objection_techniques": ["technique 1"],
        "business_facts": ["hours: ...", "policy: ..."]
    }},
    "conversation_intents": [
        {{"intent": "scheduling", "frequency": "high", "description": "Caller wants to book or change appointment"}}
    ]
}}""",
        expected_output="JSON with agent_profile and conversation_intents.",
        agent=conversation_analyst,
    )

    # --- Task 2: Map Decision Tree ---
    task_map = Task(
        description=f"""Using the conversation analysis, map the human agent's decision-making into a structured tree.

For each decision point:
- What question or signal triggers the branch?
- What are the possible outcomes?
- What does the agent do in each case?
- When do they escalate, transfer, or end the call?

Return ONLY valid JSON:
{{
    "decision_tree": {{
        "root": "initial_greeting",
        "branches": [
            {{
                "id": "greeting",
                "description": "Initial greeting and intent discovery",
                "question": "How may I help you today?",
                "outcomes": [
                    {{"condition": "wants_to_schedule", "next": "scheduling"}},
                    {{"condition": "has_question", "next": "general_inquiry"}},
                    {{"condition": "has_complaint", "next": "complaint_handling"}}
                ]
            }},
            {{
                "id": "scheduling",
                "description": "Handle appointment scheduling",
                "steps": ["ask date preference", "check availability", "confirm booking"],
                "outcomes": [
                    {{"condition": "booked_successfully", "next": "closing"}},
                    {{"condition": "no_availability", "next": "offer_alternatives"}}
                ]
            }}
        ]
    }}
}}""",
        expected_output="JSON with a decision_tree containing branches and outcomes.",
        agent=decision_mapper,
    )

    # --- Task 3: Build Blueprint ---
    task_blueprint = Task(
        description=f"""Convert the decision tree into a workflow blueprint.

RULES:
1. ALWAYS include: one globalNode, one startCall, one endCall
2. Each major branch becomes an agentNode
3. EVERY agentNode must have: "task_complete" exit → endCall AND "user_wants_to_end" exit → endCall
4. startCall must route to the right agent based on caller intent
5. Call type: {call_type}

Return ONLY valid JSON:
{{
    "nodes": [
        {{"id": "node-global", "type": "globalNode", "name": "Global Prompt"}},
        {{"id": "node-start", "type": "startCall", "name": "Greeting",
          "exit_conditions": [{{"name": "intent_name", "llm_description": "When caller wants X"}}]}},
        {{"id": "node-agent", "type": "agentNode", "name": "Agent Name",
          "exit_conditions": [
            {{"name": "task_complete", "llm_description": "Task done"}},
            {{"name": "user_wants_to_end", "llm_description": "Caller wants to end"}}
          ]}},
        {{"id": "node-end", "type": "endCall", "name": "End Call"}}
    ],
    "edges": [
        {{"source": "node-start", "target": "node-agent", "condition": "intent_name", "label": "Intent"}}
    ]
}}""",
        expected_output="JSON with nodes and edges arrays forming the workflow blueprint.",
        agent=workflow_builder,
    )

    # --- Task 4: Write Prompts ---
    task_prompts = Task(
        description=f"""Write prompts for every node that replicate the human agent's EXACT style.

Using the agent profile from the analysis:
- Use their greeting style for startCall
- Mirror their vocabulary, tone, and pacing in every agentNode
- Include their unique phrases and empathy patterns
- Use their closing technique for endCall
- globalNode should capture their overall personality and any business facts they reference
- Prompts must sound natural spoken aloud (this is VOICE, not text)
- 150-400 words per prompt
- ONLY use business facts discovered from the transcripts

Return ONLY valid JSON:
{{
    "prompts": {{
        "node-id-1": "Full prompt text that sounds like the original agent...",
        "node-id-2": "..."
    }}
}}""",
        expected_output="JSON mapping each node ID to its prompt text.",
        agent=prompt_writer,
    )

    crew = Crew(
        agents=[conversation_analyst, decision_mapper, workflow_builder, prompt_writer],
        tasks=[task_analyze, task_map, task_blueprint, task_prompts],
        process=Process.sequential,
        verbose=False,
    )

    return crew


async def run_voice_clone_crew(
    transcripts: list[str],
    business_name: str = "Business",
    call_type: str = "INBOUND",
) -> dict:
    """
    Run the 4-agent cloning crew and return a workflow definition.

    Args:
        transcripts: list of transcribed call recordings
        business_name: optional business name
        call_type: INBOUND, OUTBOUND, or WEBSITE

    Returns: {"name": str, "workflow_definition": dict}
    """
    import asyncio

    if not transcripts:
        raise ValueError("At least one transcript is required")

    valid_transcripts = [t for t in transcripts if t and len(t.strip()) > 50]
    if not valid_transcripts:
        raise ValueError("No valid transcripts found (all too short or empty)")

    logger.info(f"[VoiceClone] Starting crew with {len(valid_transcripts)} transcripts")

    crew = _build_clone_crew(valid_transcripts, business_name, call_type)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, crew.kickoff)

    logger.info("[VoiceClone] Crew finished, parsing outputs")

    task_outputs = result.tasks_output if hasattr(result, "tasks_output") else []

    # Task 3: blueprint
    blueprint = None
    if len(task_outputs) >= 3:
        try:
            blueprint = _parse_json_from_output(task_outputs[2].raw)
            _validate_blueprint(blueprint)
            logger.info(f"[VoiceClone] Blueprint: {len(blueprint.get('nodes', []))} nodes")
        except Exception as e:
            logger.error(f"[VoiceClone] Failed to parse blueprint: {e}")

    if not blueprint:
        raise ValueError("Workflow Builder failed to produce a valid blueprint")

    # Task 4: prompts
    final_prompts = {}
    if len(task_outputs) >= 4:
        try:
            prompt_data = _parse_json_from_output(task_outputs[3].raw)
            final_prompts = prompt_data.get("prompts", prompt_data)
        except Exception as e:
            logger.error(f"[VoiceClone] Failed to parse prompts: {e}")

    if not final_prompts:
        raise ValueError("Prompt Writer failed to produce prompts")

    workflow_def = assemble_workflow_definition(blueprint, final_prompts)

    node_count = len(blueprint.get("nodes", []))
    logger.info(f"[VoiceClone] Complete: {business_name} ({node_count} nodes)")

    return {
        "name": business_name,
        "workflow_definition": workflow_def,
    }
