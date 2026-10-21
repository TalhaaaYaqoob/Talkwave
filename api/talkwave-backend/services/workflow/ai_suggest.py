"""
AI Suggestion Service for Workflow Builder.

Provides intelligent suggestions for:
1. Edge conditions between nodes (analyzes source → target context)
2. Agent node prompts (analyzes full workflow context)
3. Node improvements (reviews existing prompt and suggests fixes)
"""

import json
from typing import Optional

from loguru import logger
from openai import AsyncOpenAI

from api.db import db_client
from api.schemas.user_configuration import UserConfiguration


EDGE_CONDITION_SYSTEM_PROMPT = """You are an expert voice AI workflow designer. You create edge conditions (transition rules) between agent nodes.

CRITICAL RULES for edge conditions:
1. Edge conditions are SHORT state-based transitions, NOT verbose descriptions.
2. They describe WHEN the source node's job is done and the conversation should move to the target.
3. Look at OTHER existing edge conditions in the workflow and MATCH THEIR STYLE exactly.
4. Typical patterns: "greeting_complete", "user_wants_dining", "reservation_confirmed", "caller_asks_about_location", "inquiry_resolved"
5. Use snake_case or short phrases (2-5 words max)
6. The condition should be from the SOURCE node's perspective — what happens in that node that triggers moving to the target

BAD examples (too verbose): "user inquires about spa services or requests spa appointment"
GOOD examples: "user_wants_spa", "spa_inquiry", "asks_about_spa"

If other edges from the same source node exist, MATCH their exact style and format.

Respond with a JSON object:
{
  "condition": "short_condition_text",
  "label": "Short Label"
}

Only return the JSON, nothing else."""

NODE_PROMPT_SYSTEM_PROMPT = """You are an expert voice AI workflow designer. You help users write agent node prompts for voice AI agents.

CRITICAL: The call direction (INBOUND vs OUTBOUND vs WEBSITE vs MEETING) dramatically changes how agents should behave:

**INBOUND CALLS** (customer calls you):
- The caller initiated the call - they want something
- Agent should be welcoming, helpful, and ready to assist
- Greeting should acknowledge they called (e.g., "Thank you for calling...")
- Agent should ask "How can I help you today?" or similar
- Agent should be prepared to answer questions, take orders, schedule appointments, etc.
- More reactive - respond to what the caller needs

**OUTBOUND CALLS** (you call the customer):
- You initiated the call - you have a purpose
- Agent should introduce themselves and the company immediately
- Agent should state the reason for calling (e.g., "I'm calling to follow up on...", "We'd like to offer you...")
- Agent should be proactive - guide the conversation toward a goal
- Agent should be respectful of the caller's time
- More directive - lead the conversation toward an objective

**WEBSITE** (visitor clicks widget on a website):
- Visitor is browsing a website and clicked a voice assistant button
- Agent should be friendly, casual, and web-native (e.g., "Hi! How can I help you today?")
- Do NOT use phone-style greetings — this is a website widget, not a phone call
- Agent uses knowledge base content scraped from the website to provide real-time answers
- Helps with: product info, support, pricing, navigation, FAQs
- Tone: Conversational, approachable, like a helpful chat assistant but voice-powered

**MEETING** (AI assistant that joins meetings):
- Agent sits in a meeting (Google Meet, Zoom, Teams) alongside real participants
- Agent ONLY speaks when explicitly called by a wake word (e.g., "Hey TalkWave", "Jarvis")
- Agent must NEVER interrupt, talk over participants, or respond to conversations not directed at it
- When called, agent should answer concisely and helpfully using its knowledge base
- Agent should be professional, brief, and to-the-point — meetings have limited time
- Agent can help with: answering questions, recalling facts, providing data, summarizing points
- Tone: Professional, concise, like a knowledgeable colleague who only speaks when asked
- The startCall node should NOT have a greeting — the agent stays silent until called
- Prompts should instruct the agent to wait for its wake word before responding

Given the full workflow context (all nodes, edges, and the global prompt), suggest what this specific node's prompt should be.

The prompt should:
- Be specific to this node's role in the workflow
- Reference what the previous nodes handle so this node focuses on its unique responsibility
- Include clear instructions for the AI agent
- Mention what information to collect if relevant
- Be conversational and natural for voice interactions
- Be 3-8 sentences long
- **CRITICALLY**: Adjust tone and approach based on the call type (INBOUND, OUTBOUND, WEBSITE, or MEETING)

Respond with a JSON object:
{
  "prompt": "the suggested prompt text",
  "name": "suggested name for this node (2-4 words)"
}

Only return the JSON, nothing else."""

NODE_IMPROVE_SYSTEM_PROMPT = """You are an expert voice AI workflow designer. You review and improve existing agent node prompts.

CRITICAL: The call direction (INBOUND vs OUTBOUND vs WEBSITE vs MEETING) dramatically changes how agents should behave:

**INBOUND CALLS** (customer calls you):
- The caller initiated the call - they want something
- Agent should be welcoming, helpful, and ready to assist
- More reactive - respond to what the caller needs

**OUTBOUND CALLS** (you call the customer):
- You initiated the call - you have a purpose
- Agent should introduce themselves and the company immediately
- More directive - lead the conversation toward an objective

**WEBSITE** (visitor on a webpage):
- Visitor clicked a voice widget on a website
- Agent is friendly, casual, web-native — NOT phone-style
- Uses website knowledge base to answer questions about the site

**MEETING** (AI assistant in a meeting):
- Agent joins a live meeting (Google Meet, Zoom, Teams) as a silent participant
- Agent ONLY speaks when called by a wake word — never interrupts
- Responses must be concise, professional, and knowledge-based
- No greeting — the agent stays silent until explicitly called upon

Given the current prompt, the node's context in the workflow, and connected nodes, suggest improvements.

Your improvements should:
- Make the prompt clearer and more specific
- Add missing instructions that would help the voice agent
- Improve conversational flow
- Ensure smooth transitions to/from connected nodes
- Keep the original intent but enhance it
- **CRITICALLY**: Ensure the prompt matches the call type (INBOUND, OUTBOUND, or WEBSITE) - adjust tone and approach accordingly

Respond with a JSON object:
{
  "improved_prompt": "the improved prompt text",
  "suggestions": ["list of 2-3 specific changes you made and why"]
}

Only return the JSON, nothing else."""


async def _get_openai_client(user_id: int, complex_task: bool = False) -> tuple[AsyncOpenAI, str]:
    """Get OpenAI client using user's configured LLM settings.

    Matches the pattern from workflow_generator.py for provider compatibility.

    Args:
        complex_task: When True, select the strongest available model for the
            provider (e.g. full gpt-4.1 instead of the cheap nano/mini default).
            Use for reasoning-heavy work like whole-graph editing; keep False for
            cheap one-shot suggestions (edge labels, field names) to control cost.
    """
    import os
    from api.constants import MPS_API_URL

    user_config = await db_client.get_user_configurations(user_id)

    # Check for API key: first from user config, then from environment variables
    api_key = None
    provider_name = "openai"

    if user_config.llm and user_config.llm.api_key:
        api_key = user_config.llm.api_key
        provider = user_config.llm.provider
        provider_name = provider.value if hasattr(provider, 'value') else str(provider) if provider else "openai"
    else:
        # Fallback to environment variables
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("GROQ_API_KEY")
        if os.getenv("OPENAI_API_KEY"):
            provider_name = "openai"
        elif os.getenv("GROQ_API_KEY"):
            provider_name = "groq"

    if not api_key:
        raise ValueError("No LLM API key configured. Please set up your API keys in Settings.")

    # Configure client based on provider
    client_kwargs = {"api_key": api_key}

    if provider_name.lower() == "groq":
        client_kwargs["base_url"] = "https://api.groq.com/openai/v1"
        model = "llama-3.3-70b-versatile"  # already Groq's strongest general model
    elif provider_name.lower() == "dograh":
        # Dograh uses MPS API as OpenAI-compatible endpoint
        client_kwargs["base_url"] = f"{MPS_API_URL}/v1"
        model = "gpt-4.1" if complex_task else "gpt-4.1-nano"
    elif provider_name.lower() == "azure":
        if hasattr(user_config.llm, 'base_url') and user_config.llm.base_url:
            client_kwargs["base_url"] = user_config.llm.base_url
        model = "gpt-4.1" if complex_task else "gpt-4.1-mini"
    else:
        # OpenAI
        if hasattr(user_config.llm, 'base_url') and user_config.llm.base_url:
            client_kwargs["base_url"] = user_config.llm.base_url
        model = "gpt-4.1" if complex_task else "gpt-4.1-nano"

    return AsyncOpenAI(**client_kwargs), model


async def suggest_edge_condition(
    user_id: int,
    source_node: dict,
    target_node: dict,
    all_edges: list,
    global_prompt: Optional[str] = None,
    call_type: str = "OUTBOUND",
) -> dict:
    """
    Suggest an edge condition between two nodes.

    Args:
        user_id: User ID for LLM access
        source_node: The source node data (where conversation is)
        target_node: The target node data (where it should go)
        all_edges: All edges in the workflow (for context of other transitions)
        global_prompt: The global prompt if available

    Returns:
        dict with 'condition' and 'label' keys
    """
    client, model = await _get_openai_client(user_id)

    # Build context about the edge
    source_info = f"Source Node: \"{source_node.get('data', {}).get('name', 'Unknown')}\"\n"
    source_info += f"Type: {source_node.get('type', 'unknown')}\n"
    source_info += f"Prompt: {source_node.get('data', {}).get('prompt', 'No prompt')}\n"

    target_info = f"Target Node: \"{target_node.get('data', {}).get('name', 'Unknown')}\"\n"
    target_info += f"Type: {target_node.get('type', 'unknown')}\n"
    target_info += f"Prompt: {target_node.get('data', {}).get('prompt', 'No prompt')}\n"

    # Show ALL existing edge conditions from the same source — critical for style matching
    other_edges_from_source = [
        e for e in all_edges
        if e.get("source") == source_node.get("id") and e.get("target") != target_node.get("id")
    ]
    # Also get any edge that already exists between source and target (user might be editing)
    existing_edge = next(
        (e for e in all_edges if e.get("source") == source_node.get("id") and e.get("target") == target_node.get("id")),
        None
    )

    style_context = ""
    if other_edges_from_source:
        style_context = "\n⚠️ IMPORTANT - Match the EXACT style of these existing conditions from the same source:\n"
        for e in other_edges_from_source:
            cond = e.get("data", {}).get("condition", "")
            label = e.get("data", {}).get("label", "")
            if cond:
                style_context += f"  → \"{cond}\" (label: \"{label}\")\n"
        style_context += "Your suggestion MUST use the same format/style as the above.\n"

    if existing_edge:
        existing_cond = existing_edge.get("data", {}).get("condition", "")
        if existing_cond:
            style_context += f"\nCurrent condition for this edge: \"{existing_cond}\"\n"

    global_context = ""
    if global_prompt:
        global_context = f"\nBusiness context:\n{global_prompt[:300]}\n"

    call_direction_context = f"\n⚠️ CALL DIRECTION: {call_type}\n"
    if call_type == "INBOUND":
        call_direction_context += "This is an INBOUND call (customer called you). Edge conditions should reflect customer-initiated actions.\n"
    elif call_type == "MEETING":
        call_direction_context += "This is a MEETING agent (joins live meetings). Edge conditions should reflect wake-word triggers and question types.\n"
    elif call_type == "WEBSITE":
        call_direction_context += "This is a WEBSITE widget agent. Edge conditions should reflect visitor browsing intent.\n"
    else:
        call_direction_context += "This is an OUTBOUND call (you called the customer). Edge conditions should reflect progress toward your goal.\n"

    user_message = f"""Suggest an edge condition for this transition:

{source_info}
{target_info}
{style_context}
{global_context}
{call_direction_context}

Generate a SHORT edge condition (2-5 words, snake_case or short phrase). Match the style of existing conditions."""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": EDGE_CONDITION_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=100,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        return {
            "condition": result.get("condition", ""),
            "label": result.get("label", ""),
        }
    except Exception as e:
        logger.error(f"AI edge suggestion failed: {e}")
        raise ValueError(f"AI suggestion failed: {str(e)}")


async def suggest_node_prompt(
    user_id: int,
    target_node: dict,
    all_nodes: list,
    all_edges: list,
    global_prompt: Optional[str] = None,
    call_type: str = "OUTBOUND",
) -> dict:
    """
    Suggest a prompt for a specific node based on workflow context.

    Args:
        user_id: User ID for LLM access
        target_node: The node to suggest a prompt for
        all_nodes: All nodes in the workflow
        all_edges: All edges in the workflow
        global_prompt: The global prompt if available

    Returns:
        dict with 'prompt' and 'name' keys
    """
    client, model = await _get_openai_client(user_id)

    # Build full workflow context
    workflow_summary = "FULL WORKFLOW STRUCTURE:\n\n"

    if global_prompt:
        workflow_summary += f"Global Prompt:\n{global_prompt[:500]}\n\n"

    workflow_summary += "Nodes:\n"
    for node in all_nodes:
        nd = node.get("data", {})
        node_id = node.get("id", "")
        is_target = " ← THIS IS THE NODE TO SUGGEST FOR" if node_id == target_node.get("id") else ""
        workflow_summary += f"  [{node.get('type', '?')}] \"{nd.get('name', 'Unnamed')}\"{is_target}\n"
        if nd.get("prompt") and node_id != target_node.get("id"):
            workflow_summary += f"    Prompt: {nd['prompt'][:200]}...\n"
        workflow_summary += "\n"

    workflow_summary += "Transitions (edges):\n"
    node_names = {n.get("id"): n.get("data", {}).get("name", n.get("id", "?")) for n in all_nodes}
    for edge in all_edges:
        src_name = node_names.get(edge.get("source"), "?")
        tgt_name = node_names.get(edge.get("target"), "?")
        cond = edge.get("data", {}).get("condition", "always")
        workflow_summary += f"  {src_name} → {tgt_name} (when: {cond})\n"

    # Info about connected nodes
    incoming = [e for e in all_edges if e.get("target") == target_node.get("id")]
    outgoing = [e for e in all_edges if e.get("source") == target_node.get("id")]

    connections = "\nConnections for this node:\n"
    for e in incoming:
        src_name = node_names.get(e.get("source"), "?")
        connections += f"  Incoming from: {src_name} (condition: {e.get('data', {}).get('condition', 'always')})\n"
    for e in outgoing:
        tgt_name = node_names.get(e.get("target"), "?")
        connections += f"  Outgoing to: {tgt_name} (condition: {e.get('data', {}).get('condition', 'always')})\n"

    target_info = f"\nNode to generate prompt for:\n"
    target_info += f"  Type: {target_node.get('type', 'unknown')}\n"
    target_info += f"  Current Name: {target_node.get('data', {}).get('name', 'Unnamed')}\n"
    current_prompt = target_node.get("data", {}).get("prompt", "")
    if current_prompt:
        target_info += f"  Current Prompt: {current_prompt}\n"

    call_direction_context = f"\n⚠️ CRITICAL - CALL DIRECTION: {call_type}\n"
    if call_type == "INBOUND":
        call_direction_context += """This is an INBOUND call (customer called you). The prompt should:
- Welcome the caller and acknowledge they initiated the call
- Be helpful and ready to assist with their needs
- Ask "How can I help you?" or similar welcoming questions
- Be reactive - respond to what the caller wants
- Use phrases like "Thank you for calling", "How can I assist you today?"
"""
    elif call_type == "MEETING":
        call_direction_context += """This is a MEETING agent (joins live meetings as an AI assistant). The prompt should:
- Instruct the agent to stay SILENT until explicitly called by a wake word
- When called, respond concisely and professionally using knowledge base information
- NEVER interrupt or speak over meeting participants
- Keep answers brief — meetings have limited time
- Be factual, helpful, and to-the-point when responding
- The startCall node should have NO greeting — the agent listens silently
- Use phrases like "Based on our records...", "The answer to that is..."
"""
    else:
        call_direction_context += """This is an OUTBOUND call (you called the customer). The prompt should:
- Introduce yourself and your company immediately
- State the reason for calling clearly
- Be proactive and guide the conversation toward your goal
- Be respectful of the caller's time
- Use phrases like "I'm calling to...", "We'd like to offer you..."
"""

    user_message = f"""{workflow_summary}
{connections}
{target_info}
{call_direction_context}

Based on the workflow structure, this node's role, and the call direction ({call_type}), suggest an ideal prompt for this agent node."""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": NODE_PROMPT_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.4,
            max_tokens=500,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        return {
            "prompt": result.get("prompt", ""),
            "name": result.get("name", ""),
        }
    except Exception as e:
        logger.error(f"AI node suggestion failed: {e}")
        raise ValueError(f"AI suggestion failed: {str(e)}")


async def improve_node_prompt(
    user_id: int,
    target_node: dict,
    all_nodes: list,
    all_edges: list,
    global_prompt: Optional[str] = None,
    call_type: str = "OUTBOUND",
) -> dict:
    """
    Improve an existing node prompt.

    Returns:
        dict with 'improved_prompt' and 'suggestions' keys
    """
    client, model = await _get_openai_client(user_id)

    current_prompt = target_node.get("data", {}).get("prompt", "")
    if not current_prompt:
        # If no prompt, generate one instead
        return await suggest_node_prompt(user_id, target_node, all_nodes, all_edges, global_prompt)

    # Build context
    node_names = {n.get("id"): n.get("data", {}).get("name", n.get("id", "?")) for n in all_nodes}

    incoming = [e for e in all_edges if e.get("target") == target_node.get("id")]
    outgoing = [e for e in all_edges if e.get("source") == target_node.get("id")]

    context = f"Node: \"{target_node.get('data', {}).get('name', 'Unknown')}\"\n"
    context += f"Current Prompt:\n{current_prompt}\n\n"

    if global_prompt:
        context += f"Global Prompt (business context):\n{global_prompt[:500]}\n\n"

    context += "Connected nodes:\n"
    for e in incoming:
        src_name = node_names.get(e.get("source"), "?")
        context += f"  Comes from: {src_name}\n"
    for e in outgoing:
        tgt_name = node_names.get(e.get("target"), "?")
        cond = e.get("data", {}).get("condition", "always")
        context += f"  Goes to: {tgt_name} (when: {cond})\n"

    call_direction_context = f"\n⚠️ CRITICAL - CALL DIRECTION: {call_type}\n"
    if call_type == "INBOUND":
        call_direction_context += """This is an INBOUND call (customer called you). Ensure the prompt:
- Welcomes the caller appropriately
- Acknowledges they initiated the call
- Is helpful and ready to assist
- Uses welcoming, reactive language
"""
    elif call_type == "MEETING":
        call_direction_context += """This is a MEETING agent (joins live meetings). Ensure the prompt:
- Instructs the agent to stay SILENT until called by wake word
- Keeps responses concise and professional
- Never interrupts meeting participants
- Uses knowledge base for factual answers
"""
    else:
        call_direction_context += """This is an OUTBOUND call (you called the customer). Ensure the prompt:
- Introduces the agent and company clearly
- States the reason for calling
- Is proactive and goal-oriented
- Uses professional, directive language
"""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": NODE_IMPROVE_SYSTEM_PROMPT},
                {"role": "user", "content": f"Review and improve this node:\n\n{context}{call_direction_context}"},
            ],
            temperature=0.4,
            max_tokens=600,
            response_format={"type": "json_object"},
        )

        raw_content = response.choices[0].message.content
        logger.debug(f"AI improve raw response: {raw_content[:500]}")
        result = json.loads(raw_content)

        improved = (
            result.get("improved_prompt")
            or result.get("prompt")
            or result.get("improved")
            or result.get("text")
        )
        if not improved or improved.strip() == current_prompt.strip():
            improved = result.get("improved_prompt", current_prompt)

        return {
            "improved_prompt": improved or current_prompt,
            "suggestions": result.get("suggestions", []),
        }
    except Exception as e:
        logger.error(f"AI improve suggestion failed: {e}")
        raise ValueError(f"AI suggestion failed: {str(e)}")


EXTRACTION_PROMPT_SYSTEM = """You are an expert at designing variable extraction prompts for voice AI agents.

Given the agent's main prompt, its extraction variables, and the full workflow context, improve the extraction prompt.

CRITICAL RULES:
- The extraction prompt MUST be ONE short sentence (max 10-15 words). Example: "Extract reservation details from the conversation"
- NEVER write long multi-line prompts. Keep it extremely concise.
- The prompt should summarize WHAT to extract in a few words, not HOW.

Respond with a JSON object:
{
  "improved_prompt": "Short one-line extraction prompt",
  "suggestions": ["list of 1-2 brief changes you made"]
}

Only return the JSON, nothing else."""


async def improve_extraction_prompt(
    user_id: int,
    target_node: dict,
    all_nodes: list,
    all_edges: list,
    global_prompt: Optional[str] = None,
    call_type: str = "OUTBOUND",
) -> dict:
    """Improve the extraction prompt for a node based on its full context."""
    client, model = await _get_openai_client(user_id)

    node_data = target_node.get("data", {})
    current_extraction_prompt = node_data.get("extraction_prompt", "")
    main_prompt = node_data.get("prompt", "")
    variables = node_data.get("extraction_variables", [])

    context = f"Node: \"{node_data.get('name', 'Unknown')}\"\n"
    context += f"Agent Prompt:\n{main_prompt}\n\n"

    if current_extraction_prompt:
        context += f"Current Extraction Prompt:\n{current_extraction_prompt}\n\n"
    else:
        context += "Current Extraction Prompt: (empty - generate one from scratch)\n\n"

    if variables:
        context += "Variables to extract:\n"
        for v in variables:
            context += f"  - {v.get('name', '?')} ({v.get('type', 'string')})"
            if v.get('prompt'):
                context += f": {v['prompt']}"
            context += "\n"
    else:
        context += "No specific variables defined yet. Suggest a general extraction prompt based on the agent's goals.\n"

    if global_prompt:
        context += f"\nBusiness context:\n{global_prompt[:400]}\n"

    context += f"\nCall direction: {call_type}\n"

    node_names = {n.get("id"): n.get("data", {}).get("name", n.get("id", "?")) for n in all_nodes}
    incoming = [e for e in all_edges if e.get("target") == target_node.get("id")]
    outgoing = [e for e in all_edges if e.get("source") == target_node.get("id")]

    context += "\nConnected nodes:\n"
    for e in incoming:
        context += f"  Comes from: {node_names.get(e.get('source'), '?')}\n"
    for e in outgoing:
        cond = e.get("data", {}).get("condition", "always")
        context += f"  Goes to: {node_names.get(e.get('target'), '?')} (when: {cond})\n"

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT_SYSTEM},
                {"role": "user", "content": f"Review and improve this extraction prompt:\n\n{context}"},
            ],
            temperature=0.3,
            max_tokens=200,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        logger.debug(f"AI extraction improve raw response: {raw[:500]}")
        result = json.loads(raw)

        improved = (
            result.get("improved_prompt")
            or result.get("prompt")
            or result.get("extraction_prompt")
            or result.get("text")
        )

        return {
            "improved_prompt": improved or current_extraction_prompt,
            "suggestions": result.get("suggestions", []),
        }
    except Exception as e:
        logger.error(f"AI extraction prompt improvement failed: {e}")
        raise ValueError(f"AI suggestion failed: {str(e)}")


SUGGEST_VARIABLES_SYSTEM = """You are an expert at designing data extraction schemas for voice AI agents.

Given the agent's main prompt and context, suggest extraction variables.

CRITICAL RULES for variable prompts:
- Each variable "prompt" MUST be very short (3-6 words max). Examples:
  "Customer's full name", "Number of guests", "Preferred date and time", "Customer's phone number"
- NEVER write long descriptions. Just a brief label.
- Variable names must be snake_case (e.g., customer_name, party_size)
- Only suggest variables the agent is actually collecting

CRITICAL RULES for extraction_prompt:
- Must be ONE short sentence (max 10-15 words). Example: "Extract reservation details from the conversation"
- NEVER write long multi-line prompts.

Respond with a JSON object:
{
  "variables": [
    {"name": "customer_name", "type": "string", "prompt": "Customer's full name"},
    {"name": "party_size", "type": "number", "prompt": "Number of guests"}
  ],
  "extraction_prompt": "Extract reservation details from the conversation"
}

Only return the JSON, nothing else."""


async def suggest_extraction_variables(
    user_id: int,
    target_node: dict,
    all_nodes: list,
    all_edges: list,
    global_prompt: Optional[str] = None,
    call_type: str = "OUTBOUND",
) -> dict:
    """Suggest extraction variables based on the agent's prompt and context."""
    client, model = await _get_openai_client(user_id)

    node_data = target_node.get("data", {})
    main_prompt = node_data.get("prompt", "")
    existing_vars = node_data.get("extraction_variables", [])

    context = f"Node: \"{node_data.get('name', 'Unknown')}\"\n"
    context += f"Agent Prompt:\n{main_prompt}\n\n"

    if existing_vars:
        context += "Existing variables (keep these and suggest additional ones if needed):\n"
        for v in existing_vars:
            context += f"  - {v.get('name', '?')} ({v.get('type', 'string')}): {v.get('prompt', '')}\n"
        context += "\n"

    if global_prompt:
        context += f"Business context:\n{global_prompt[:400]}\n\n"

    context += f"Call direction: {call_type}\n"

    node_names = {n.get("id"): n.get("data", {}).get("name", n.get("id", "?")) for n in all_nodes}
    incoming = [e for e in all_edges if e.get("target") == target_node.get("id")]
    outgoing = [e for e in all_edges if e.get("source") == target_node.get("id")]

    context += "\nConnected nodes:\n"
    for e in incoming:
        context += f"  Comes from: {node_names.get(e.get('source'), '?')}\n"
    for e in outgoing:
        cond = e.get("data", {}).get("condition", "always")
        context += f"  Goes to: {node_names.get(e.get('target'), '?')} (when: {cond})\n"

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SUGGEST_VARIABLES_SYSTEM},
                {"role": "user", "content": f"Suggest extraction variables for this agent:\n\n{context}"},
            ],
            temperature=0.2,
            max_tokens=400,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        logger.debug(f"AI suggest variables raw response: {raw[:500]}")
        result = json.loads(raw)

        variables = result.get("variables", [])
        validated = []
        for v in variables:
            name = v.get("name", "").strip()
            vtype = v.get("type", "string")
            if vtype not in ("string", "number", "boolean"):
                vtype = "string"
            vprompt = v.get("prompt", "").strip()
            if name:
                validated.append({"name": name, "type": vtype, "prompt": vprompt})

        return {
            "variables": validated,
            "extraction_prompt": result.get("extraction_prompt", ""),
        }
    except Exception as e:
        logger.error(f"AI suggest variables failed: {e}")
        raise ValueError(f"AI suggestion failed: {str(e)}")


IMPROVE_RESPONSE_SYSTEM = """You are an expert voice AI conversation designer. You review a specific agent response from a real test call transcript and suggest improvements.

Given:
- The full conversation so far
- The specific agent response to improve

Your improvements should:
- Make the response more natural and conversational for voice
- Improve clarity and conciseness (voice agents should be brief)
- Ensure the response moves the conversation forward
- Fix any awkward phrasing or overly robotic language
- Maintain the agent's persona and goal

Respond with a JSON object:
{
  "improved_prompt": "the improved response text",
  "suggestions": ["list of 2-3 specific changes you made and why"]
}

Only return the JSON, nothing else."""


async def improve_agent_response(
    user_id: int,
    conversation_context: str,
    target_response: str,
) -> dict:
    """
    Improve a specific agent response based on transcript context.

    Returns:
        dict with 'improved_prompt' and 'suggestions' keys
    """
    client, model = await _get_openai_client(user_id)

    user_message = f"""Conversation transcript:
{conversation_context}

Agent response to improve:
"{target_response}"

Suggest an improved version of this specific agent response."""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": IMPROVE_RESPONSE_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=400,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        return {
            "improved_prompt": result.get("improved_prompt", target_response),
            "suggestions": result.get("suggestions", []),
        }
    except Exception as e:
        logger.error(f"AI response improvement failed: {e}")
        raise ValueError(f"AI response improvement failed: {str(e)}")


AI_FLOW_EDIT_SYSTEM = """You are an elite voice AI workflow architect operating an in-canvas editor. You can perform
ANY edit a human could make in the builder — both INSIDE a node (rewrite prompts, add/remove exit
conditions, change extraction variables, toggle the knowledge base, edit branch conditions,
categories, transfer targets, etc.) and OUTSIDE the node (add/remove/rename nodes, rewire edges,
restructure branches, reposition the layout). Be bold and literal: do exactly what the user asks,
and make every related change needed for the result to be valid and coherent.

You receive the current workflow as JSON (nodes + edges + viewport) and a natural-language
instruction. Each node is {id, type, position:{x,y}, data:{...}}.

═══════════════════════════════════════════════════════════════════════════════
NODE TYPES AND THEIR EDITABLE data FIELDS (you may set/change any of these):
═══════════════════════════════════════════════════════════════════════════════
- "startCall"  — Entry point. EXACTLY ONE per workflow. data.is_start:true.
    • data.name, data.prompt (the opening greeting; for MEETING agents leave it empty/silent).
- "agentNode"  — A conversation step. The workhorse.
    • data.name, data.prompt (the instructions, ~150-400 words, natural spoken voice).
    • data.exit_conditions: [{id, name, llm_description, required_variables:[{name,type,description}]}]
      — when the node's job is done it exits via one of these; the matching outgoing edge's
      `condition` MUST equal the exit `name`. ALWAYS keep "task_complete" and "user_wants_to_end".
    • data.extraction_enabled (bool), data.extraction_prompt (ONE short sentence),
      data.extraction_variables: [{name (snake_case), type:"string"|"number"|"boolean", prompt}].
    • data.knowledge_base: {enabled:bool, llm_description, query_override, chunk_limit:int} —
      enable when the node answers factual questions from the business knowledge base.
    • data.allow_interrupt (bool), data.web_search_enabled (bool), data.add_global_prompt (bool),
      data.timer_duration (int seconds), data.max_rounds (int).
- "endCall"    — Terminates the call. data.is_end:true. data.name, data.prompt (warm goodbye).
- "globalNode" — Shared context prepended to every node. data.prompt (business identity + rules).
- "actionNode" — Post-call actions. data.name, data.actions:[...], data.execution_mode:
      "sequential"|"parallel". Each action has {id, type, name, enabled, ...type-specific fields}.
- "ifElse"     — SILENT binary branch. data.name, data.condition_text (the yes/no statement the LLM
      evaluates, e.g. "The caller confirmed they are an existing member"). NO data.prompt.
      Outputs EXACTLY two edges (one true, one false).
- "categorize" — SILENT multi-way router. data.name, data.prompt (short 1-2 sentence classification
      instruction), data.categories (array of ≥2 distinct strings). Outputs ONE edge per category.
- "transfer"   — Hands the live call to a human/phone/SIP. data.name, data.prompt (short spoken
      handoff line, ≤30 words), data.transfer_target (REQUIRED), data.is_literal (bool).
      transfer_target is one of: a literal phone number ("+15551234567"), a SIP URI, OR a template
      variable that an upstream agent extracts ("{callback_number}", "{specialist_phone}").
      NEVER leave it empty and NEVER invent a fake number. Transfer nodes have NO outgoing edges.
- "meetingTrigger" / "meetingSummary" — only in MEETING-type workflows; preserve unless asked.

═══════════════════════════════════════════════════════════════════════════════
WHEN TO REACH FOR BRANCHING NODES (infer intent — don't wait for exact keywords):
═══════════════════════════════════════════════════════════════════════════════
- ifElse → a yes/no qualification or confirmation gate ("only book if they're a member",
  "confirm before cancelling", "check eligibility first").
- categorize → routing among 3+ distinct intents ("send sales / support / billing to the right
  team", "triage by reason for calling").
- transfer → caller wants a human, an escalation, an out-of-scope request, or a warm handoff
  ("transfer angry callers to a manager", "connect them to billing").

═══════════════════════════════════════════════════════════════════════════════
EDGE RULES:
═══════════════════════════════════════════════════════════════════════════════
1. Every edge: {id, source, target, data:{label, condition}}.
2. From an agentNode/startCall, `data.condition` MUST match one of the source node's exit_conditions
   `name` values. If you add a new branch, also add the matching exit condition on the source node.
3. CRITICAL — branch edges need a top-level "sourceHandle" so they attach to the right output:
   • ifElse: the true edge MUST have sourceHandle:"true" and data.condition:"true" (label "True");
     the false edge MUST have sourceHandle:"false" and data.condition:"false" (label "False").
   • categorize: each edge MUST have sourceHandle:"category-<CategoryName>" and
     data.condition:"<CategoryName>" matching a string in that node's data.categories EXACTLY
     (label = the category name).
   • All other source types: omit sourceHandle (single default output).

═══════════════════════════════════════════════════════════════════════════════
GENERAL RULES:
═══════════════════════════════════════════════════════════════════════════════
1. Return the COMPLETE modified workflow (ALL nodes and edges), never a partial diff.
2. Preserve existing node IDs when modifying them; generate new unique IDs ("node_<random>") for
   new nodes. Never duplicate an ID.
3. When the user asks to edit content "inside" a node (its prompt, variables, exits, KB, condition,
   categories, transfer number, etc.), modify that node's data IN PLACE and leave the graph shape
   intact unless the edit logically requires new edges/nodes.
4. Keep the graph valid: exactly one startCall, at least one terminal (endCall or transfer), every
   node reachable from start, no dangling edges (source/target must reference existing node IDs).
5. Never fabricate business facts (names, addresses, phone numbers, hours, prices). Use template
   variables like {customer_name} when a value should come from the conversation.
6. Layout: increment y by ~250 per row; spread parallel branches horizontally by ~480 on x so
   nothing overlaps. Keep the original viewport.
7. If the instruction is impossible or unsafe, return the workflow UNCHANGED and explain why in
   "explanation".

Respond with a JSON object ONLY (no markdown, no commentary):
{
  "nodes": [...],
  "edges": [...],
  "viewport": {x, y, zoom},
  "explanation": "Brief, specific description of exactly what was changed"
}"""


async def ai_edit_workflow(
    user_id: int,
    instruction: str,
    current_nodes: list,
    current_edges: list,
    current_viewport: dict,
    global_prompt: Optional[str] = None,
    call_type: str = "OUTBOUND",
) -> dict:
    """
    Modify an existing workflow graph based on natural language instruction.

    Returns:
        dict with 'nodes', 'edges', 'viewport', and 'explanation' keys
    """
    # Whole-graph editing is the most reasoning-heavy AI task in the builder, so
    # use the strongest available model rather than the cheap suggestion default.
    client, model = await _get_openai_client(user_id, complex_task=True)

    workflow_json = json.dumps({
        "nodes": current_nodes,
        "edges": current_edges,
        "viewport": current_viewport,
    }, indent=2, default=str)

    context = f"Call type: {call_type}\n"
    if global_prompt:
        context += f"Business context: {global_prompt[:500]}\n"

    user_message = f"""Current workflow:
{workflow_json}

{context}

User instruction: {instruction}

Apply the requested changes and return the complete modified workflow."""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": AI_FLOW_EDIT_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_tokens=16000,
            response_format={"type": "json_object"},
        )

        result = json.loads(response.choices[0].message.content)
        nodes = result.get("nodes", current_nodes)
        edges = _normalize_branch_edges(nodes, result.get("edges", current_edges))
        return {
            "nodes": nodes,
            "edges": edges,
            "viewport": result.get("viewport", current_viewport),
            "explanation": result.get("explanation", "Workflow updated"),
        }
    except Exception as e:
        logger.error(f"AI flow edit failed: {e}")
        raise ValueError(f"AI flow edit failed: {str(e)}")


def _normalize_branch_edges(nodes: list, edges: list) -> list:
    """Backfill sourceHandle on edges leaving ifElse / categorize nodes.

    The React Flow canvas connects branch edges via the source handle id. LLMs frequently
    set only the label/condition, leaving sourceHandle blank, which renders disconnected
    branches. This deterministically repairs the handle from the edge's condition/label so
    AI-edited branching nodes wire up correctly regardless of model compliance.
    """
    node_by_id = {n.get("id"): n for n in nodes if isinstance(n, dict)}

    # Transfer nodes terminate the agent's leg of the call, so any outgoing edge
    # the model may have added is invalid — drop them.
    transfer_ids = {
        n.get("id") for n in nodes
        if isinstance(n, dict) and n.get("type") == "transfer"
    }
    edges = [
        e for e in edges
        if not (isinstance(e, dict) and e.get("source") in transfer_ids)
    ]

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src = node_by_id.get(edge.get("source"))
        if not src:
            continue
        src_type = src.get("type")
        data = edge.get("data") or {}
        cond = str(data.get("condition") or data.get("label") or "").strip()

        if src_type == "ifElse":
            if edge.get("sourceHandle") in ("true", "false"):
                continue
            truthy = cond.lower() in ("true", "yes", "1", "t")
            handle = "true" if truthy else "false"
            edge["sourceHandle"] = handle
            data.setdefault("label", "True" if truthy else "False")
            data["condition"] = handle
            edge["data"] = data
        elif src_type == "categorize":
            if str(edge.get("sourceHandle") or "").startswith("category-"):
                continue
            categories = (src.get("data") or {}).get("categories") or []
            match = next(
                (c for c in categories if str(c).strip().lower() == cond.lower()),
                cond,
            )
            if match:
                edge["sourceHandle"] = f"category-{match}"
                data["label"] = str(match)
                data["condition"] = str(match)
                edge["data"] = data

    return edges


QUERY_GENERATOR_SYSTEM = """You are an expert database assistant helping non-technical users build database queries.

The user will tell you in plain English what they want to do. You must generate the correct query and explain it simply.

RULES:
1. Generate a syntactically correct query for the specified database type
2. Use {{variable_name}} placeholders for dynamic values from the available variables
3. Keep queries simple and safe — always use parameterized placeholders
4. The explanation MUST be in very simple terms a non-technical person can understand
5. For MongoDB, generate JSON-style queries
6. For Firebase/Firestore, generate a structured path-based query description
7. For SQL databases (PostgreSQL, MySQL, Supabase), generate standard SQL

Respond with JSON:
{
  "query_template": "the generated query with {{variable}} placeholders",
  "explanation": "Simple 1-2 sentence explanation of what this query does, written for someone who doesn't know code"
}

Only return JSON, nothing else."""


ACTION_HELPER_SYSTEM = """You are a helpful assistant that generates technical configurations for non-technical users.

The user will describe what they want in plain English. Based on the action type, generate the appropriate configuration.

For "api_call" or "webhook":
- Generate a valid JSON body template using {{variable_name}} for dynamic values
- Generate appropriate headers if needed
- Explain what it does simply

For "email":
- Generate subject line and email body
- Use {{variable_name}} for personalization
- Keep it professional and friendly

Respond with JSON:
{
  "content": { ... fields relevant to the action type ... },
  "explanation": "Simple explanation of what this will do"
}

Only return JSON, nothing else."""


SUGGEST_FIELD_SYSTEM = """You are an expert voice AI workflow designer. You suggest concise, descriptive text for workflow node fields.

RULES:
- For "name" fields: Return a short 2-4 word name in Title Case (e.g., "Greeting Agent", "Reservation Handler", "Post-Call Actions")
- For "description" fields: Return one brief sentence describing purpose (e.g., "Handles initial greeting and routing", "Sends confirmation email after booking")
- For "improve" mode: Make the existing text clearer and more professional while keeping it short
- Base suggestions on the node's prompt, type, connected nodes, and workflow context

Respond with JSON: {"text": "the suggested text"}
Only return JSON, nothing else."""


async def suggest_field(
    user_id: int,
    target_node: dict,
    all_nodes: list,
    all_edges: list,
    field_name: str = "name",
    current_value: str = "",
    global_prompt: Optional[str] = None,
    call_type: str = "OUTBOUND",
) -> dict:
    """Suggest or improve a short text field (name, description) for a node."""
    client, model = await _get_openai_client(user_id)

    node_data = target_node.get("data", {})
    node_type = target_node.get("type", "unknown")
    prompt_text = node_data.get("prompt", "")

    context = f"Node type: {node_type}\n"
    if node_data.get("name"):
        context += f"Current name: {node_data['name']}\n"
    if prompt_text:
        context += f"Node prompt: {prompt_text[:300]}\n"
    if global_prompt:
        context += f"Business context: {global_prompt[:200]}\n"

    node_names = {n.get("id"): n.get("data", {}).get("name", n.get("id", "?")) for n in all_nodes}
    incoming = [e for e in all_edges if e.get("target") == target_node.get("id")]
    outgoing = [e for e in all_edges if e.get("source") == target_node.get("id")]
    if incoming or outgoing:
        context += "Workflow flow: "
        for e in incoming:
            context += f"{node_names.get(e.get('source'), '?')} → this node, "
        for e in outgoing:
            context += f"this node → {node_names.get(e.get('target'), '?')}, "
        context += "\n"

    context += f"Call direction: {call_type}\n"

    mode = "improve" if current_value.strip() else "suggest"
    user_msg = f"{mode.capitalize()} a {field_name} for this node"
    if current_value.strip():
        user_msg += f"\nCurrent {field_name}: \"{current_value}\""
    user_msg += f"\n\nContext:\n{context}"

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SUGGEST_FIELD_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=100,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        logger.debug(f"AI suggest field raw: {raw}")
        result = json.loads(raw)
        return {"text": result.get("text", current_value or "")}
    except Exception as e:
        logger.error(f"AI suggest field failed: {e}")
        raise ValueError(f"AI suggestion failed: {str(e)}")


async def suggest_database_query(
    user_id: int,
    database_service: str,
    table_name: str,
    operation: str,
    description: str,
    available_variables: list,
) -> dict:
    """Generate a database query from plain English description."""
    client, model = await _get_openai_client(user_id)

    db_type_labels = {
        "postgresql": "PostgreSQL (SQL)",
        "mysql": "MySQL (SQL)",
        "supabase": "Supabase (PostgreSQL/SQL)",
        "mongodb": "MongoDB (JSON query)",
        "firebase": "Firebase/Firestore (path-based)",
        "redis": "Redis (key-value commands)",
    }

    db_label = db_type_labels.get(database_service, database_service)

    user_msg = f"""Database type: {db_label}
Table/Collection name: {table_name or '(not specified)'}
Operation: {operation}
User's description: "{description}"
Available variables: {', '.join(f'{{{{{v}}}}}' for v in available_variables) if available_variables else 'None'}

Generate the appropriate query and explain it in simple terms."""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": QUERY_GENERATOR_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=500,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        logger.debug(f"AI query generation raw: {raw}")
        result = json.loads(raw)
        return {
            "query_template": result.get("query_template", ""),
            "explanation": result.get("explanation", ""),
        }
    except Exception as e:
        logger.error(f"AI query generation failed: {e}")
        raise ValueError(f"AI query generation failed: {str(e)}")


async def suggest_action_content(
    user_id: int,
    action_type: str,
    description: str,
    action_data: dict,
    available_variables: list,
) -> dict:
    """Generate technical configuration from plain English for any action type."""
    client, model = await _get_openai_client(user_id)

    type_instructions = {
        "api_call": "Generate: url (string), method (GET/POST/PUT/DELETE), headers (object), body_template (JSON string with {{var}} placeholders). Return in 'content' field.",
        "webhook": "Generate: url (string), method (POST/PUT), headers (object), body_template (JSON string with {{var}} placeholders). Return in 'content' field.",
        "email": "Generate: subject (string with {{var}} placeholders), body (string with {{var}} placeholders), is_html (boolean). Return in 'content' field.",
    }

    instruction = type_instructions.get(action_type, "Generate appropriate content. Return in 'content' field.")

    user_msg = f"""Action type: {action_type}
User's description: "{description}"
Current configuration: {json.dumps(action_data, default=str)}
Available variables: {', '.join(f'{{{{{v}}}}}' for v in available_variables) if available_variables else 'None'}

{instruction}

Also provide a simple explanation of what this will do."""

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": ACTION_HELPER_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=800,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        logger.debug(f"AI action content raw: {raw}")
        result = json.loads(raw)
        return {
            "content": result.get("content", {}),
            "explanation": result.get("explanation", ""),
        }
    except Exception as e:
        logger.error(f"AI action content failed: {e}")
        raise ValueError(f"AI action content generation failed: {str(e)}")
