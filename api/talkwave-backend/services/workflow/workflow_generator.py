"""
Local AI Workflow Generator - Generates workflow definitions using user's configured LLM.

This replaces the external MPS service with a local implementation using OpenAI or
any other LLM provider configured by the user.
"""

import asyncio
import json
import os
import re
import uuid
from typing import Optional, Set, List, Tuple
from urllib.parse import urljoin, urlparse

import aiohttp
from loguru import logger
from openai import AsyncOpenAI

from api.db import db_client


# Maximum pages to crawl for deep website extraction
MAX_PAGES_TO_CRAWL = 10
# Maximum total content size (roughly 30000 chars ~ 7500 tokens)
MAX_TOTAL_CONTENT_SIZE = 30000
# Timeout for individual page requests
PAGE_TIMEOUT = 60  # 60 seconds - heavy JS sites need more time


async def _fetch_page_with_jina(
    url: str,
    session: aiohttp.ClientSession,
    jina_api_key: Optional[str] = None,
) -> Tuple[Optional[str], List[str]]:
    """Fetch a page via Jina Reader API using markdown format.

    Returns ``(content, discovered_links)``.
    Links are extracted from markdown ``[text](url)`` patterns in the response.
    """
    jina_url = "https://r.jina.ai/"

    headers = {
        "Authorization": f"Bearer {jina_api_key}" if jina_api_key else "",
        "Content-Type": "application/json",
        "DNT": "1",
        "X-Base": "final",
        "X-Cache-Tolerance": "300",
        "X-No-Cache": "true",
        "X-Proxy": "auto",
        "X-Retain-Images": "none",
        "X-Return-Format": "markdown",
        "X-Timeout": "10",
        "X-With-Iframe": "true",
    }
    if not jina_api_key:
        headers.pop("Authorization", None)

    content: Optional[str] = None

    try:
        logger.info(f"🔍 Jina Reader: fetching {url}")
        async with session.post(
            jina_url,
            headers=headers,
            json={"url": url},
            timeout=aiohttp.ClientTimeout(total=PAGE_TIMEOUT),
        ) as response:
            if response.status == 200:
                resp_text = await response.text()
                try:
                    data = json.loads(resp_text)
                    if isinstance(data, dict) and "data" in data:
                        content = data["data"].get("content", "")
                        title = data["data"].get("title", "")
                        if title and content and title not in content[:200]:
                            content = f"{title}\n\n{content}"
                    elif isinstance(data, dict):
                        content = data.get("content", resp_text)
                    else:
                        content = resp_text
                except (json.JSONDecodeError, ValueError):
                    content = resp_text
            else:
                logger.warning(f"Jina status {response.status} for {url}")
    except asyncio.TimeoutError:
        logger.warning(f"Jina timeout for {url}")
    except Exception as e:
        logger.warning(f"Jina failed for {url}: {type(e).__name__}: {e}")

    if not content or len(content.strip()) < 50:
        logger.warning(f"Jina returned no usable content for {url}")
        return None, []

    content = content.strip()
    logger.info(f"✅ Jina: {len(content)} chars from {url}")

    links = _extract_links_from_markdown(content, url)
    logger.info(f"Extracted {len(links)} links from markdown of {url}")

    return content, links


def _extract_links_from_markdown(markdown: str, source_url: str) -> List[str]:
    """Pull all ``[text](url)`` links from markdown content."""
    parsed_source = urlparse(source_url)
    base = f"{parsed_source.scheme}://{parsed_source.netloc}"
    raw = re.findall(r'\[([^\]]*)\]\(([^)]+)\)', markdown)

    seen: set = set()
    links: list = []
    for _text, href in raw:
        href = href.strip()
        if href.startswith("mailto:") or href.startswith("#") or href.startswith("javascript:"):
            continue
        if href.startswith("/"):
            href = f"{base}{href}"
        elif not href.startswith("http"):
            href = urljoin(source_url, href)
        clean = urlparse(href)
        normalized = f"{clean.scheme}://{clean.netloc}{clean.path}".rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            links.append(normalized)
    return links


async def _select_best_links_with_llm(
    page_content: str,
    all_links: List[str],
    source_url: str,
    max_links: int = 8,
) -> List[str]:
    """Ask OpenAI to pick the most useful internal links for a voice agent KB.

    Returns a subset of *all_links* that the LLM considers most informative.
    Falls back to heuristic selection if the LLM call fails.
    """
    base_domain = urlparse(source_url).netloc
    internal = [l for l in all_links if urlparse(l).netloc == base_domain]

    if len(internal) <= max_links:
        return internal

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("No OPENAI_API_KEY for link selection, using heuristic")
        return _prioritize_links(internal, f"{urlparse(source_url).scheme}://{base_domain}")[:max_links]

    numbered = "\n".join(f"{i+1}. {l}" for i, l in enumerate(internal))
    prompt = (
        f"You are helping build a knowledge base for a voice AI agent about the business at {source_url}.\n\n"
        f"Here is the homepage content (first 3000 chars):\n---\n{page_content[:3000]}\n---\n\n"
        f"Here are all internal links found on this page:\n{numbered}\n\n"
        f"Select the {max_links} most useful links that would contain important business information "
        f"for a customer-facing voice agent (e.g. about us, services, products, pricing, contact, FAQ, "
        f"press releases, careers, locations). Exclude links to login pages, social media, language "
        f"switchers, cookie policies, or generic navigation.\n\n"
        f"Return ONLY the numbers of the selected links, comma-separated. Example: 1,3,5,7,9,11,14,16"
    )

    try:
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0,
        )
        text = resp.choices[0].message.content.strip()
        indices = [int(x.strip()) - 1 for x in re.findall(r'\d+', text)]
        selected = [internal[i] for i in indices if 0 <= i < len(internal)]
        if selected:
            logger.info(f"LLM selected {len(selected)} links: {selected}")
            return selected[:max_links]
    except Exception as e:
        logger.warning(f"LLM link selection failed: {e}")

    return _prioritize_links(internal, f"{urlparse(source_url).scheme}://{base_domain}")[:max_links]


def _clean_extracted_content(content: str) -> str:
    """
    Clean extracted website content by removing navigation, UI elements, 
    booking widgets, calendars, and other non-informational junk.
    
    This ensures only meaningful business content goes into the knowledge base.
    """
    if not content:
        return content
    
    lines = content.split('\n')
    cleaned_lines = []
    
    # Patterns to skip (navigation, UI elements, booking widgets)
    skip_patterns = [
        # Navigation & UI
        r'^\s*\[?SKIP TO', r'^\s*Sign In', r'^\s*Close overlay', r'^\s*Menu$',
        r'^\s*Cart$', r'^\s*hide$', r'^\s*Done$', r'^\s*Update$',
        r'^\s*Check Rates', r'^\s*Check in', r'^\s*Check out',
        r'^\s*Best Rate', r'^\s*Promo\s*$',
        # Calendar/date stuff
        r'^\s*\*\s*(Restricted|Unavailable)', r'^\s*Updated about',
        r'^\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\s*$',
        r'^\s*S\s+M\s+T\s+W\s+T\s+F\s+S\s*$',  # Calendar header
        r'^\s*(\d{1,2}\s+){5,}',  # Calendar numbers row
        r'^\d{2}/\d{2}/\d{4}',  # Dates like 02/06/2024
        # Room/Guest selectors
        r'^\s*\d+ Room', r'^\s*\d+ Adults', r'^\s*\d+ Children',
        r'^\s*Add another room', r'^\s*Room \d+',
        r'^\s*Adults \(\d+\+\)', r'^\s*Guests\s*$',
        # Markdown links to same site (navigation)  
        r'^\s*\[Go to the', r'^\s*\[All Hotels', r'^\s*\[Itinerary\]',
        r'^\s*\[Check Rates\]', r'^\s*\[Best Rate',
        # Language selectors
        r'^\s*\*\s*\[(English|عربي|Français|Deutsch|Español|中文|日本語)',
        # Single short items that are likely buttons/links
        r'^\s*\*\s*$',
        # Selected dates
        r'^\s*Selected Dates',
    ]
    
    skip_compiled = [re.compile(p, re.IGNORECASE) for p in skip_patterns]
    
    # Track if we're in a section to skip
    in_skip_section = False
    consecutive_short_lines = 0
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines (but keep one)
        if not stripped:
            if cleaned_lines and cleaned_lines[-1].strip():
                cleaned_lines.append('')
            continue
        
        # Skip lines matching junk patterns
        if any(p.search(stripped) for p in skip_compiled):
            continue
        
        # Skip very short lines that are likely buttons (1-3 chars)
        if len(stripped) <= 3 and not stripped[0].isdigit():
            continue
        
        # Skip markdown bullet points that are just navigation links
        if stripped.startswith('* ') and '[' in stripped and '](' in stripped:
            # Keep if it looks like actual content description
            link_text = stripped.split('[')[1].split(']')[0] if '[' in stripped else ''
            if len(link_text) < 30:  # Short link text = probably navigation
                continue
        
        # Track consecutive short lines (likely a navigation menu)
        if len(stripped) < 20:
            consecutive_short_lines += 1
            if consecutive_short_lines > 5:  # Skip blocks of short lines
                continue
        else:
            consecutive_short_lines = 0
        
        cleaned_lines.append(stripped)
    
    # Join and clean up multiple blank lines
    result = '\n'.join(cleaned_lines)
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    return result.strip()


def _prioritize_links(links: List[str], base_url: str) -> List[str]:
    """
    Prioritize links that are likely to contain important business information.
    """
    # Keywords that indicate important pages
    priority_keywords = [
        'about', 'menu', 'services', 'products', 'pricing', 'price', 
        'contact', 'hours', 'location', 'faq', 'team', 'story',
        'what-we-do', 'our-services', 'offerings', 'packages',
        'rooms', 'amenities', 'facilities', 'gallery', 'portfolio',
        'book', 'reservation', 'appointment', 'schedule'
    ]
    
    # Patterns to skip
    skip_patterns = [
        r'/blog/', r'/news/', r'/press/', r'/careers/', r'/jobs/',
        r'/login', r'/signin', r'/signup', r'/register', r'/cart',
        r'/checkout', r'/account', r'/privacy', r'/terms', r'/legal',
        r'\.pdf$', r'\.jpg$', r'\.png$', r'\.gif$', r'\?page=',
        r'/tag/', r'/category/', r'/author/', r'/archive/'
    ]
    
    priority_links = []
    other_links = []
    
    for link in links:
        link_lower = link.lower()
        
        # Skip if matches skip patterns
        if any(re.search(pattern, link_lower) for pattern in skip_patterns):
            continue
        
        # Check if it's a priority link
        if any(keyword in link_lower for keyword in priority_keywords):
            priority_links.append(link)
        else:
            other_links.append(link)
    
    # Return priority links first, then others
    return priority_links + other_links


async def fetch_website_content(url: str, deep_crawl: bool = True) -> Optional[str]:
    """
    Fetch and extract text content from a website URL with deep crawling.
    
    This function crawls the main page and important subpages to build
    a comprehensive knowledge base about the business.
    
    Args:
        url: The website URL to scrape
        deep_crawl: If True, crawl multiple pages. If False, only fetch the main page.
        
    Returns:
        Extracted text content from multiple pages or None if failed
    """
    if not url:
        return None
    
    # Clean the URL
    url = url.strip()
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # Ensure URL ends properly
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    
    logger.info(f"Starting deep website crawl from: {url}")
    
    jina_api_key = os.getenv(
        "JINA_API_KEY",
        "jina_0046a448a99f43e78f58924665655499Dr6-g_l0pmB0CYqN569rDePHhWfg",
    )
    
    # Track visited URLs and collected content
    visited_urls: Set[str] = set()
    all_content: List[Tuple[str, str]] = []  # (page_url, content)
    urls_to_visit: List[str] = [url]
    total_content_size = 0
    
    async with aiohttp.ClientSession() as session:
        pages_crawled = 0
        first_page_done = False

        while urls_to_visit and pages_crawled < MAX_PAGES_TO_CRAWL and total_content_size < MAX_TOTAL_CONTENT_SIZE:
            current_url = urls_to_visit.pop(0)

            if current_url in visited_urls:
                continue

            visited_urls.add(current_url)
            pages_crawled += 1

            logger.info(f"Crawling page {pages_crawled}/{MAX_PAGES_TO_CRAWL}: {current_url}")

            content, new_links = await _fetch_page_with_jina(current_url, session, jina_api_key)

            if not content:
                logger.warning(f"No content for {current_url}, skipping")
                if deep_crawl and new_links:
                    for link in new_links:
                        if link not in visited_urls and link not in urls_to_visit:
                            urls_to_visit.append(link)
                continue

            content = _clean_extracted_content(content)

            if not content or len(content.strip()) < 50:
                logger.info(f"Skipped {current_url} - no meaningful content after cleaning")
                continue

            page_name = urlparse(current_url).path or "Home"
            page_name = page_name.strip('/').replace('/', ' > ') or "Home Page"

            if len(content) > 5000:
                content = content[:5000] + "\n[Page content truncated...]"

            all_content.append((page_name, content))
            total_content_size += len(content)
            logger.info(f"Collected {len(content)} chars from: {page_name}")

            if deep_crawl and new_links and not first_page_done:
                first_page_done = True
                best_links = await _select_best_links_with_llm(
                    content, new_links, url, max_links=8,
                )
                for link in best_links:
                    if link not in visited_urls and link not in urls_to_visit:
                        urls_to_visit.append(link)
                logger.info(f"LLM selected {len(best_links)} links to crawl from {len(new_links)} total")
            elif deep_crawl and new_links:
                base_domain = urlparse(url).netloc
                for link in new_links:
                    if urlparse(link).netloc == base_domain:
                        if link not in visited_urls and link not in urls_to_visit:
                            urls_to_visit.append(link)

            if urls_to_visit:
                await asyncio.sleep(0.5)
    
    if not all_content:
        logger.warning(f"Could not extract any content from {url}")
        return None
    
    # Combine all content with clear section headers
    combined_content = []
    combined_content.append(f"=== WEBSITE CONTENT FROM: {url} ===\n")
    combined_content.append(f"Pages crawled: {len(all_content)}\n")
    combined_content.append("=" * 50 + "\n\n")
    
    for page_name, content in all_content:
        combined_content.append(f"--- PAGE: {page_name} ---\n")
        combined_content.append(content)
        combined_content.append("\n\n")
    
    final_content = '\n'.join(combined_content)
    
    # Final truncation if needed
    if len(final_content) > MAX_TOTAL_CONTENT_SIZE:
        final_content = final_content[:MAX_TOTAL_CONTENT_SIZE] + "\n\n[Content truncated due to size limits...]"
    
    logger.info(f"Deep crawl complete: {len(all_content)} pages, {len(final_content)} total chars")
    
    return final_content


async def fetch_website_content_single_page(url: str) -> Optional[str]:
    """
    Fetch content from a single page only (no deep crawling).
    Useful for quick previews or when deep crawling is not needed.
    """
    return await fetch_website_content(url, deep_crawl=False)

# System prompt for workflow generation - INTELLIGENT STRUCTURE VERSION
WORKFLOW_GENERATOR_PROMPT = """You are an expert voice agent workflow designer. Design INTELLIGENT workflows with the APPROPRIATE structure for each use case.

CRITICAL: Analyze the use case and choose the RIGHT workflow structure:
- **SEQUENTIAL/HIERARCHICAL** - When tasks depend on each other (e.g., qualification → assessment → scheduling)
- **PARALLEL/BRANCHING** - When handling independent intents from a router (e.g., restaurant: reservations OR orders OR menu info)
- **MIXED** - Combination of both patterns

⚠️ MANDATORY - CALL MUST END PROPERLY:
- EVERY agentNode MUST have an exit condition that leads to "End Call" node
- The agent MUST end the call after completing its task (e.g., after booking confirmation, after providing info)
- Include "end_call" or "task_complete" exit condition on EVERY agent node
- The End Call node should have a friendly goodbye message

RETURN ONLY valid JSON:

{
    "workflow_definition": {
        "nodes": [...],
        "edges": [...],
        "viewport": {"x": 0, "y": 0, "zoom": 1}
    }
}

⚠️ DO NOT include a "name" field — the workflow name is set by the system from the user's input.

NODE TYPES (MUST include ALL of these):
- "globalNode" - REQUIRED! Contains the global prompt/persona that applies to ALL agents. Position at x=-200, y=100
- "startCall" - Entry point. MUST have is_start: true AND exit_conditions with "greeting_complete"
- "agentNode" - Task handler (can be sequential OR parallel depending on use case). MUST have exit_conditions
- "endCall" - Exit point. MUST have is_end: true

=== GLOBAL NODE (REQUIRED - VERY IMPORTANT!) ===
The globalNode defines the AI persona and context that applies to ALL agents in the workflow.
It should contain:
- Business identity (who you are, company name)
- Tone and personality guidelines
- Key business information (hours, location, policies)
- Communication style rules
- Any context all agents need

GLOBAL NODE STRUCTURE:
{
    "id": "node-global",
    "type": "globalNode",
    "position": {"x": -200, "y": 100},
    "data": {
        "name": "Global Prompt",
        "prompt": "You are [PERSONA] for [BUSINESS NAME]. [BUSINESS DETAILS]. Always be [TONE]. [KEY POLICIES/INFO].",
        "is_static": false
    },
    "measured": {"width": 320, "height": 180}
}

REGULAR NODE STRUCTURE:
{
    "id": "node-unique-id",
    "type": "startCall|agentNode|endCall",
    "position": {"x": 400, "y": 100},
    "data": {
        "name": "Short Name",
        "prompt": "Detailed agent instructions (specific to this step)",
        "is_start": true/false,
        "is_end": true/false,
        "is_static": false,
        "allow_interrupt": true,
        "add_global_prompt": true,
        "web_search_enabled": false,
        "knowledge_base": null,  // OR see KNOWLEDGE BASE section below
        "exit_conditions": [...]  // REQUIRED for startCall and agentNode! See below.
    },
    "measured": {"width": 320, "height": 180}
}

⚠️ startCall PROMPT RULES:
- The startCall node's "prompt" is spoken INSTANTLY when the call connects (using the configured TTS voice).
- It doubles as the greeting AND the system prompt for the first step.
- Start the prompt with a natural greeting, e.g. "Hello! Welcome to [Business]. How can I help you today?"
- After the greeting line, include the agent instructions for this step.

⚠️ CRITICAL: ALWAYS set "web_search_enabled": false unless SPECIFICALLY needed for live data!

=== KNOWLEDGE BASE FEATURE (INTELLIGENT ASSIGNMENT) ===
When business website content is provided, you MUST decide WHICH agents need KB access.
NOT all agents need KB - only agents that ANSWER QUESTIONS or need to LOOK UP specific details.

To ENABLE KB on an agent, set:
"knowledge_base": {
    "enabled": true,
    "llm_description": "Describe WHEN this agent should search the KB (be specific to this agent's role)",
    "query_override": "",
    "chunk_limit": 5
}

To DISABLE KB on an agent (default), set:
"knowledge_base": null

WHICH AGENTS NEED KB? (Be intelligent — this applies to ANY industry):
✅ ENABLE KB on agents that:
- Answer questions requiring specific factual knowledge (products, services, pricing, procedures, policies)
- Provide detailed information the caller might ask about (hours, locations, offerings, specs, eligibility)
- Handle inquiries where looking up accurate details matters

❌ DO NOT enable KB on agents that:
- Only collect user data (name, phone, date, appointment time)
- Just confirm or summarize what the user said
- Only route or transfer calls to the right department
- Handle simple yes/no decisions
- Are greeting or farewell agents

EXAMPLES across different industries:
• Restaurant: Booking agent=no KB (collects date/guests), Menu agent=KB ON (looks up dishes/prices)
• Medical clinic: Appointment agent=no KB (collects date/doctor), Services agent=KB ON (procedures/insurance info)
• Real estate: Lead qualification=no KB (collects budget/preferences), Property info=KB ON (listings/details)
• Customer support: Routing agent=no KB (asks department), Technical help=KB ON (troubleshooting/product docs)
• Hotel: Reservation agent=no KB (collects dates/rooms), Amenities agent=KB ON (facilities/policies/rates)
• Law firm: Intake agent=no KB (collects case details), Services agent=KB ON (practice areas/fees)

The rule is simple: if the agent needs to LOOK UP facts to answer → KB ON. If it just COLLECTS info from the caller → KB OFF.

⚠️ CRITICAL VALIDATION RULE:
- ALL startCall nodes MUST have exit_conditions with at least "greeting_complete"
- ALL agentNode nodes MUST have exit_conditions with at least "task_complete"
- Edges MUST have a "condition" that matches an exit_condition name on the source node

START NODE exit_conditions example:
"exit_conditions": [{"id": "exit-start", "name": "greeting_complete", "llm_description": "Greeting finished, proceed to next step"}]

AGENT NODE exit_conditions example:
"exit_conditions": [
    {"id": "exit-done", "name": "task_complete", "llm_description": "Task completed or user wants to end"},
    {"id": "exit-next", "name": "continue", "llm_description": "Continue to next step"}
]

=== WEB SEARCH FEATURE ===
⚠️ IMPORTANT: Set "web_search_enabled": FALSE for most agents!
Only set "web_search_enabled": true when the agent SPECIFICALLY needs live internet data.

KEEP web_search_enabled=false (DEFAULT) for:
- ALL agents using business knowledge from website content
- Greeting/routing nodes
- Data collection nodes
- Menu/services/pricing info (already in prompts)
- Confirmation/summary nodes
- End call nodes

Only set web_search_enabled=true for:
- Agents that need LIVE real-time data (weather, news, stock prices)
- Agents verifying external information not in the business data

EXIT CONDITIONS (CRITICAL - defines WHERE each node connects):
{
    "id": "exit-unique-id",
    "name": "condition_name",
    "llm_description": "When X happens, transition to the next step"
}

⚠️ EVERY agentNode MUST have these exit conditions:
1. **Task completion exit** → leads to End Call (e.g., "reservation_confirmed", "information_provided", "task_complete")
2. **User wants to end** → leads to End Call (e.g., "user_goodbye", "end_call", "user_done")
3. **Next step exits** → leads to next agent (if workflow continues)

The LLM will call the exit function when the condition is met. If the exit leads to End Call, the call ends gracefully.

EDGE STRUCTURE (connects nodes via exit conditions):
{
    "id": "edge-unique-id",
    "source": "source-node-id",
    "target": "target-node-id", 
    "type": "custom",
    "animated": true,
    "data": {"condition": "exit_name", "label": "Display Label"}  // condition MUST NOT be empty!
}

⚠️ EDGE VALIDATION RULES:
- Edge "condition" MUST match an exit_condition "name" on the source node
- Edges from startCall should use condition: "greeting_complete"
- Edges from agentNode should use condition: "task_complete", "continue", or custom exit names

=== WORKFLOW PATTERNS - CHOOSE BASED ON USE CASE ===

**PATTERN 1: SEQUENTIAL/HIERARCHICAL** (Use when tasks build on each other)
Best for: Lead qualification, onboarding, surveys, step-by-step processes, outbound sales
```
[Global Node]  [Start Call]
                    ↓
              [Step 1 Agent] → [Step 2 Agent] → [Step 3 Agent]
                    ↓                                  ↓
                [End Call] ←←←←←←←←←←←←←←←←←←←←←←←←←←←
```

**PATTERN 2: PARALLEL/BRANCHING** (Use for independent intents/services)
Best for: Customer service hotlines, restaurants with multiple services, support desks
```
[Global Node]    [Start Call / Router]
                /    |    |    |    \\
            [Intent1][Intent2][Intent3][Intent4]
                \\    |    |    |    /
                   [End Call]
```

**PATTERN 3: MIXED** (Complex workflows with both patterns)

DESIGN RULES:
1. **ALWAYS INCLUDE globalNode** - Contains persona and business context for all agents
2. **ANALYZE THE USE CASE** - Determine if tasks are dependent (sequential) or independent (parallel)
3. **SEQUENTIAL for processes** - Qualification, onboarding, surveys, sales pipelines
4. **PARALLEL for routing** - Multiple independent services, support categories, departments
5. **EACH AGENT = ONE CLEAR TASK** - Don't overload agents with multiple responsibilities
6. **add_global_prompt: true** - Set this on ALL nodes so they inherit the global context
7. **CALL MUST END** - Every agent MUST have an exit to End Call after completing its task
8. **END CALL PROMPT** - Should thank the user and say goodbye warmly

=== OUTBOUND vs INBOUND vs WEBSITE CALL DESIGN (CRITICAL!) ===

**INBOUND calls** (customer called us):
- Start node greeting: "Hello, thank you for calling [Business]. How can I help you today?"
- Agent waits for the caller to state their intent
- Router/branching pattern is common (caller picks what they need)
- Tone: Receptive, helpful, service-oriented

**OUTBOUND calls** (we are calling the customer):
- Start node greeting: "Hello, this is [Name/Business] calling regarding [purpose]. Do you have a moment?"
- Agent is PROACTIVE — drives the conversation, explains why they're calling
- Sequential/pipeline pattern is common (intro → qualify → pitch → close)

**WEBSITE calls** (visitor clicks widget on a website):
- Start node greeting: "Hi! Welcome to [Business]. I'm your virtual assistant. How can I help you today?"
- Agent is embedded on a website and helps visitors with questions about the site
- Uses knowledge base from the website content for real-time answers
- Router/branching pattern to handle different visitor intents (product info, support, pricing, etc.)
- Tone: Friendly, conversational, web-native — NOT phone-style
- MUST handle objections gracefully (not interested, busy, call back later)
- Agent should introduce the PURPOSE of the call immediately
- Tone: Professional, purposeful, respectful of their time
- Include a "not interested" exit condition on qualification/pitch agents → End Call politely

⚠️ NEVER generate an inbound-style greeting ("thank you for calling") for an OUTBOUND workflow!
⚠️ NEVER generate an outbound-style greeting ("I'm calling regarding") for an INBOUND workflow!
⚠️ For WEBSITE workflows, use web-friendly greetings ("Welcome!", "Hi there!") — NOT phone greetings!

POSITION LAYOUT:
- Global node (left side): x=-200
- Main flow (center): x=400
- Parallel branches spread horizontally: x=0, 200, 400, 600, 800
- Sequential steps stack vertically: y increases by 350-400 per step

Return ONLY the JSON object."""


async def generate_workflow_with_openai(
    call_type: str,
    use_case: str,
    activity_description: str,
    user_id: int,
    website_url: Optional[str] = None,
    knowledge_base_content: Optional[str] = None,
    knowledge_base_files: Optional[list] = None,
    organization_id: Optional[int] = None,
) -> dict:
    """
    Generate a workflow definition using OpenAI.
    
    Args:
        call_type: INBOUND or OUTBOUND
        use_case: Description of the use case (e.g., "Lead Qualification")
        activity_description: Detailed description of what the agent should do
        user_id: User ID to get their LLM configuration
        website_url: Optional URL to scrape for business context
        knowledge_base_content: Optional custom KB content provided by user
        knowledge_base_files: Optional list of KB file IDs to attach
        organization_id: Optional organization ID for creating KB documents
        
    Returns:
        dict with 'name' and 'workflow_definition' keys
    """
    # Determine the website/KB content to use
    website_content = None
    
    # Priority: user-provided KB content > fetch from website
    if knowledge_base_content and knowledge_base_content.strip():
        website_content = knowledge_base_content.strip()
        logger.info(f"Using user-provided knowledge base content ({len(website_content)} chars)")
    elif website_url:
        website_content = await fetch_website_content(website_url)
        if website_content:
            logger.info(f"Successfully fetched website content ({len(website_content)} chars)")
        else:
            logger.warning(f"Could not fetch content from {website_url}")
    # Get user's LLM configuration
    user_config = await db_client.get_user_configurations(user_id)
    
    # Check for API key: first from user config, then from environment variables
    api_key = None
    provider_name = "openai"  # Default provider
    model_value = None
    
    if user_config.llm and user_config.llm.api_key:
        # Use user's configured API key
        api_key = user_config.llm.api_key
        model_value = user_config.llm.model
        provider = user_config.llm.provider
        provider_name = provider.value if hasattr(provider, 'value') else str(provider) if provider else "openai"
    else:
        # Fallback to environment variables
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("GROQ_API_KEY")
        if os.getenv("OPENAI_API_KEY"):
            provider_name = "openai"
        elif os.getenv("ANTHROPIC_API_KEY"):
            provider_name = "anthropic"
        elif os.getenv("GROQ_API_KEY"):
            provider_name = "groq"
    
    if not api_key:
        raise ValueError("No LLM API key configured. Please configure your API keys in Settings → Service Configuration, or set OPENAI_API_KEY environment variable.")
    
    # Use gpt-5.1-nano for workflow generation (fast + intelligent)
    # Only use user's model if it's a high-quality model
    user_model = model_value.value if hasattr(model_value, 'value') else str(model_value) if model_value else ""
    
    # Use a faster OpenAI model for workflow generation
    if provider_name.lower() == "openai":
        model = "gpt-4.1-mini"  # Faster model for JSON generation
    elif provider_name.lower() == "groq":
        model = "llama-3.3-70b-versatile"  # Best Groq model for complex tasks
    else:
        model = user_model or "gpt-4.1-mini"
    
    logger.info(f"Generating workflow with {provider_name} using model {model}")
    
    # Configure client based on provider
    client_kwargs = {"api_key": api_key}
    
    # Handle different providers with OpenAI-compatible APIs
    if provider_name.lower() == "groq":
        client_kwargs["base_url"] = "https://api.groq.com/openai/v1"
    elif provider_name.lower() == "google":
        # Google Gemini uses a different API, fall back to basic template
        logger.warning("Google Gemini not supported for workflow generation, using template")
        return _create_basic_template(call_type, use_case, activity_description)
    elif hasattr(user_config.llm, 'base_url') and user_config.llm.base_url:
        client_kwargs["base_url"] = user_config.llm.base_url
    
    client = AsyncOpenAI(**client_kwargs)
    
    # Build the user message - explicitly request BRANCHING workflow
    # Include website content if available
    website_context = ""
    if website_content:
        website_context = f"""
**BUSINESS WEBSITE CONTENT (use this to understand the business and create relevant agents):**
---
{website_content}
---

IMPORTANT: Use the above website content to:
1. Understand what products/services this business offers
2. Extract key information like business name, hours, menu items, pricing, services, etc.
3. Create agents that can answer questions about THIS SPECIFIC business
4. Include real details from the website in agent prompts (menu items, prices, hours, etc.)

"""

    call_type_guidance = ""
    if call_type and call_type.upper() == "MEETING":
        call_type_guidance = """
⚠️ THIS IS A MEETING AGENT — it joins a live meeting and stays SILENT until addressed.
- Do NOT include "startCall" or "endCall" nodes. Use "meetingTrigger" as the entry point and "meetingSummary" as the final node.
- The meetingTrigger node listens passively and only activates when someone addresses the agent by name or wake word.
- The agent must NEVER introduce itself, greet anyone, or speak unprompted.
- Agent nodes should be concise and answer only what is asked, then return to silent listening.
- The meetingSummary node generates notes, action items, and key decisions at the end.
- Tone: Brief, professional, factual — like a knowledgeable colleague who only speaks when asked.
- Do NOT use any phone/call-related language (no "thank you for calling", no "goodbye", no "how can I help you today").
"""
    elif call_type and call_type.upper() == "WEBSITE":
        call_type_guidance = """
⚠️ THIS IS A WEBSITE VOICE AGENT — embedded on a webpage, NOT a phone call.
- The Start greeting should be web-friendly: "Hi! Welcome to [Business]. I'm your virtual assistant. How can I help you?"
- Do NOT use phone greetings like "Thank you for calling" — this is a website widget!
- The agent helps website visitors with information, support, and navigation
- Use knowledge base content from the website to provide accurate answers
- Tone: Friendly, casual, helpful — like a live chat but voice-powered
"""
    elif call_type and call_type.upper() == "OUTBOUND":
        call_type_guidance = """
⚠️ THIS IS AN OUTBOUND CALL WORKFLOW — the agent is CALLING the customer.
- The Start Call greeting MUST introduce who is calling and WHY (e.g., "Hello, this is [Name] from [Business] calling about [purpose]. Do you have a moment?")
- Do NOT use inbound-style greetings like "Thank you for calling" — WE are calling THEM!
- The agent should be PROACTIVE and drive the conversation forward
- Include exit conditions for "not_interested" or "call_back_later" on key agent nodes
- Use a SEQUENTIAL pattern (intro → qualify → pitch/collect → close → end)
"""
    else:
        call_type_guidance = """
THIS IS AN INBOUND CALL WORKFLOW — the customer is calling us.
- The Start Call greeting should welcome them (e.g., "Hello, thank you for calling [Business]. How can I help you today?")
- The agent should be RECEPTIVE and wait for the caller to state their intent
- Use PARALLEL/BRANCHING pattern if multiple services, or SEQUENTIAL for step-by-step processes
"""

    user_message = f"""Design an INTELLIGENT voice agent workflow with the APPROPRIATE structure:

**Call Type:** {call_type}
{call_type_guidance}
**Use Case:** {use_case}
**Requirements:** {activity_description}
{website_context}
CRITICAL: ANALYZE THE USE CASE AND CHOOSE THE RIGHT STRUCTURE:

**USE SEQUENTIAL/HIERARCHICAL PATTERN IF:**
- Tasks depend on each other (output of one feeds into next)
- It's a step-by-step process (qualification, onboarding, survey)
- Outbound calls with a sales/qualification pipeline
- Information gathering that builds progressively
Example: Start → Intro Agent → Qualification Agent → Assessment Agent → Scheduling Agent → End

**USE PARALLEL/BRANCHING PATTERN IF:**
- Handling multiple INDEPENDENT intents/services
- Customer service with separate departments
- Restaurant with reservations OR orders OR menu (independent choices)
- Support desk with different issue categories
Example: Start (router) → [Option A | Option B | Option C] → End

**USE MIXED PATTERN IF:**
- Complex workflows needing both
- Initial routing followed by sequential sub-processes

REQUIREMENTS:
1. **INCLUDE GLOBAL NODE** - Create a globalNode with persona/business context that applies to ALL agents
2. **ANALYZE FIRST** - Is this a process (sequential) or a service menu (parallel)?
3. **SPECIALIZED AGENTS** - Each agent handles ONE clear task
4. **CLEAR FLOW** - Sequential tasks flow one-to-next; parallel tasks branch from router
5. **EXIT CONDITIONS** - Define when to proceed to next step or end
6. **USE REAL DATA** - If website content provided, use real info from it in the global prompt

**GLOBAL PROMPT MUST INCLUDE:**
- Business identity and name (from website or use case)
- Tone and personality (friendly, professional, etc.)
- Key business info (hours, location, policies if known)
- Communication style guidelines
- Any context all agents need to know

EXAMPLE GLOBAL PROMPT for a Restaurant:
"You are a friendly AI assistant for Bella Italia Restaurant. We are an Italian restaurant located at 123 Main St. Our hours are 11am-10pm daily. Be warm, helpful, and knowledgeable about our menu. Always confirm details and offer alternatives when something isn't available."

EXAMPLE GLOBAL PROMPT for Lead Qualification:
"You are a professional sales representative for TechCorp Solutions. Be friendly but focused. Your goal is to qualify leads and schedule demos. Always be respectful of the caller's time. If they're not interested, politely end the call."

EXAMPLE - Lead Qualification (SEQUENTIAL):
```
[Global] + [Start] → [Greeting/Intro] → [Qualification Questions] → [Interest Assessment] → [Schedule Demo] → [End]
```

EXAMPLE - Restaurant Hotline (PARALLEL):
```
[Global] + [Start/Router] → [Reservations] OR [Orders] OR [Menu Info] → [End]
```

Return a workflow with the APPROPRIATE structure AND a relevant GLOBAL PROMPT for this specific use case!"""

    try:
        # Use higher temperature for more creative workflows, more tokens for comprehensive output
        create_kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": WORKFLOW_GENERATOR_PROMPT},
                {"role": "user", "content": user_message}
            ],
            "temperature": 0.8,  # Higher for more creative/comprehensive workflows
            "max_tokens": 8000,  # Allow for larger workflows
        }
        
        # Only add response_format for models that support it (OpenAI, some Groq models)
        if "gpt" in model.lower() or "llama" in model.lower():
            create_kwargs["response_format"] = {"type": "json_object"}
        
        response = await client.chat.completions.create(**create_kwargs)
        
        content = response.choices[0].message.content
        logger.debug(f"Raw LLM response: {content[:500]}...")
        
        # Clean up the response - remove markdown code blocks if present
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        # Parse the JSON response
        try:
            workflow_data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse workflow JSON: {e}")
            logger.error(f"Raw response: {content[:1000]}")
            # Try to extract JSON from the response
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                try:
                    workflow_data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    raise ValueError("Failed to generate valid workflow. Please try again.")
            else:
                raise ValueError("Failed to generate valid workflow. Please try again.")
        
        # Validate the response has required fields
        if "workflow_definition" not in workflow_data:
            # If the LLM returned just the definition, wrap it
            if "nodes" in workflow_data and "edges" in workflow_data:
                workflow_data = {
                    "name": use_case,
                    "workflow_definition": workflow_data
                }
            else:
                raise ValueError("Generated workflow is missing required fields.")
        
        workflow_data["name"] = use_case
        
        # Post-process the workflow to ensure proper structure
        workflow_def = workflow_data.get("workflow_definition", {})
        nodes = workflow_def.get("nodes", [])
        edges = workflow_def.get("edges", [])
        
        # Process nodes - ensure is_static is false and dimensions exist
        for node in nodes:
            if "data" in node:
                node["data"]["is_static"] = False
                # IMPORTANT: Disable web_search by default - only enable if absolutely needed
                if node["data"].get("web_search_enabled") is True:
                    # Only keep web_search enabled for specific use cases
                    node_name = node["data"].get("name", "").lower()
                    if not any(kw in node_name for kw in ["weather", "news", "stock", "live", "real-time"]):
                        node["data"]["web_search_enabled"] = False
            if "measured" not in node:
                node["measured"] = {"width": 320, "height": 180}
        
        # Log KB status - LLM should have already decided which agents get KB
        has_kb = bool(website_content) or bool(website_url) or bool(knowledge_base_content)
        kb_nodes = [n["data"].get("name", "?") for n in nodes if (n.get("data", {}).get("knowledge_base") or {}).get("enabled")]
        logger.info(f"KB status: has_kb_content={has_kb}, LLM assigned KB to: {kb_nodes if kb_nodes else 'none'}")
        
        # CRITICAL: Ensure all nodes have proper exit conditions for validation
        nodes = _ensure_exit_conditions(nodes)
        
        # Apply intelligent branching layout to nodes
        nodes = _apply_branching_layout(nodes, edges)
        workflow_data["workflow_definition"]["nodes"] = nodes
        
        # Post-process edges - preserve LLM's branching, only fix missing connections
        edges = _fix_edges(nodes, edges)
        workflow_data["workflow_definition"]["edges"] = edges
        
        # Ensure viewport exists
        if "viewport" not in workflow_def:
            workflow_data["workflow_definition"]["viewport"] = {"x": 0, "y": 0, "zoom": 1}
        
        # FINAL SAFETY CHECK: If KB content exists but LLM assigned NO KB at all, pick the best agents
        final_nodes = workflow_data["workflow_definition"]["nodes"]
        kb_count = sum(1 for n in final_nodes if (n.get("data", {}).get("knowledge_base") or {}).get("enabled"))
        agent_count = sum(1 for n in final_nodes if n.get("type") == "agentNode")
        logger.info(f"Final KB check: {kb_count}/{agent_count} agent nodes have KB enabled")
        
        # Only force-enable if LLM assigned ZERO KB despite having content
        if has_kb and kb_count == 0 and agent_count > 0:
            logger.warning(f"LLM assigned no KB! Selectively enabling on info-providing agents...")
            for node in final_nodes:
                if node.get("type") != "agentNode":
                    continue
                name_lower = node.get("data", {}).get("name", "").lower()
                prompt_lower = node.get("data", {}).get("prompt", "").lower()
                # Enable on agents that provide info, answer questions, or look up details
                is_info_agent = any(kw in name_lower or kw in prompt_lower for kw in [
                    "info", "menu", "product", "service", "price", "detail",
                    "question", "answer", "general", "event", "faq", "hour",
                    "location", "policy", "package", "offering", "help",
                    "support", "technical", "troubleshoot", "procedure",
                    "insurance", "eligibility", "property", "listing",
                    "amenity", "facility", "treatment", "spec", "feature",
                    "plan", "coverage", "catalog", "inventory", "guide"
                ])
                if is_info_agent:
                    node["data"]["knowledge_base"] = {
                        "enabled": True,
                        "llm_description": f"Search KB for {node['data'].get('name', 'this agent')}-related business details.",
                        "query_override": "",
                        "chunk_limit": 5
                    }
                    logger.info(f"📚 Fallback: enabled KB on '{node['data'].get('name')}'")
            workflow_data["workflow_definition"]["nodes"] = final_nodes
        
        logger.info(f"Successfully generated workflow: {workflow_data.get('name')} with {len(final_nodes)} nodes and {len(edges)} edges")
        
        # Return both the workflow and the KB content that was used
        return {
            **workflow_data,
            "_kb_content_used": website_content  # Internal field to pass KB content back
        }
        
    except Exception as e:
        logger.error(f"Error generating workflow with OpenAI: {e}")
        raise ValueError(f"Failed to generate workflow: {str(e)}")


async def generate_workflow_local(
    call_type: str,
    use_case: str, 
    activity_description: str,
    user_id: int,
    organization_id: Optional[int] = None,
    website_url: Optional[str] = None,
    knowledge_base_content: Optional[str] = None,
    knowledge_base_files: Optional[list] = None,
    workflow_id: Optional[int] = None,
) -> dict:
    """
    Main entry point for local workflow generation.
    Falls back to a basic template if AI generation fails.
    
    Args:
        call_type: INBOUND or OUTBOUND
        use_case: Description of the use case
        activity_description: Detailed description
        user_id: User ID
        organization_id: Optional organization ID
        website_url: Optional URL to scrape for business context
        knowledge_base_content: Optional custom KB content provided by user
        knowledge_base_files: Optional list of KB file IDs to attach
        workflow_id: Optional workflow ID to scope KB documents to
        
    Returns:
        dict with 'name' and 'workflow_definition' keys
    """
    try:
        logger.info(f"📚 generate_workflow_local called: website_url={website_url}, kb_content={bool(knowledge_base_content)}, org_id={organization_id}")
        
        result = await generate_workflow_with_openai(
            call_type=call_type,
            use_case=use_case,
            activity_description=activity_description,
            user_id=user_id,
            website_url=website_url,
            knowledge_base_content=knowledge_base_content,
            knowledge_base_files=knowledge_base_files,
            organization_id=organization_id,
        )
        
        # Get the actual KB content that was used (could be from website fetch or user-provided)
        kb_from_result = result.pop("_kb_content_used", None)
        actual_kb_content = kb_from_result or knowledge_base_content
        
        logger.info(f"📚 KB save check: from_result={bool(kb_from_result)} ({len(kb_from_result) if kb_from_result else 0} chars), from_param={bool(knowledge_base_content)}, org_id={organization_id}")
        
        # If we have KB content, save it to the organization's knowledge base
        if organization_id and actual_kb_content:
            try:
                logger.info(f"📚 Saving {len(actual_kb_content)} chars of KB content to org {organization_id}...")
                await _save_kb_content_for_organization(
                    organization_id=organization_id,
                    user_id=user_id,
                    use_case=use_case,
                    website_url=website_url,
                    knowledge_base_content=actual_kb_content,
                    workflow_id=workflow_id,
                )
                logger.info(f"📚 ✅ KB document saved successfully to organization {organization_id}")
            except Exception as kb_error:
                logger.error(f"📚 ❌ Failed to save KB content: {type(kb_error).__name__}: {kb_error}")
                import traceback
                logger.error(f"📚 Traceback: {traceback.format_exc()}")
        elif not organization_id:
            logger.warning(f"📚 No organization_id - cannot save KB content")
        elif not actual_kb_content:
            logger.warning(f"📚 No KB content to save (website fetch may have failed)")
        
        return result
    except ValueError as e:
        # Re-raise configuration errors
        raise
    except Exception as e:
        logger.warning(f"AI workflow generation failed, using template: {e}")
        # Fall back to basic template
        return _create_basic_template(call_type, use_case, activity_description)


async def _save_kb_content_for_organization(
    organization_id: int,
    user_id: int,
    use_case: str,
    website_url: Optional[str] = None,
    knowledge_base_content: Optional[str] = None,
    workflow_id: Optional[int] = None,
) -> None:
    """
    Save knowledge base content scoped to a specific workflow.
    This creates a KB document from the extracted/edited website content.
    """
    if not knowledge_base_content:
        return
    
    from api.db.knowledge_base_client import knowledge_base_client
    from api.routes.knowledge_base import chunk_text, chunk_text_for_retrieval
    
    doc_name = f"{use_case} - Business Knowledge"
    if website_url:
        doc_name = f"{use_case} - {website_url}"
    
    doc = await knowledge_base_client.create_document(
        organization_id=organization_id,
        name=doc_name[:255],
        content=knowledge_base_content,
        file_type="txt",
        description=f"Auto-generated knowledge base from business website for {use_case}",
        file_size_bytes=len(knowledge_base_content.encode('utf-8')),
        created_by=user_id,
        workflow_id=workflow_id,
    )
    
    # INTELLIGENT CHUNKING STRATEGY:
    # - Small/medium content (≤50K chars / ~12K tokens): Store as ONE single chunk.
    #   → The voice agent's LLM gets the FULL document in one retrieval call.
    #     This eliminates the entire class of "semantic search missed the
    #     specific fact the user asked about" failures, which is the most
    #     common cause of "the agent doesn't know what's on the website".
    # - Large content (>50K chars): Use retrieval-optimized chunks (2000 chars
    #   with 200-char overlap), each carrying a document-title prefix so
    #   embeddings stay self-contained. We also pre-compute embeddings so
    #   retrieval is instant at call time.
    #
    # 50K chars is comfortable for all our runtime LLMs (Cerebras gpt-oss-120b
    # has 128K context, Gemini 2.5 Flash has 1M, GPT-4.1 nano has 128K) so a
    # full deep-crawl of a typical small-business site sits in one chunk and
    # the agent has zero retrieval misses.

    SINGLE_CHUNK_MAX_CHARS = 50_000

    content_size = len(knowledge_base_content)

    if content_size <= SINGLE_CHUNK_MAX_CHARS:
        chunks = [{
            "content": knowledge_base_content.strip(),
            "token_count": len(knowledge_base_content.split()) * 4 // 3,
        }]
        logger.info(
            f"KB: Storing as single chunk ({content_size} chars) — "
            f"full context returned on every KB lookup, no retrieval misses"
        )
    else:
        chunks = chunk_text_for_retrieval(
            knowledge_base_content,
            document_name=doc_name[:255],
            chunk_size=2000,
            overlap=200,
        )
        logger.info(
            f"KB: Split into {len(chunks)} retrieval-optimized chunks "
            f"({content_size} chars total)"
        )

    if chunks:
        created_chunks = await knowledge_base_client.create_chunks(doc.id, chunks)
        await knowledge_base_client.update_document(
            doc.id,
            processing_status="completed",
            chunk_count=len(chunks),
        )
        # Pre-compute embeddings for multi-chunk documents so retrieval is
        # instant at call time. Single-chunk docs don't need embeddings —
        # they're returned in full on every query.
        if content_size > SINGLE_CHUNK_MAX_CHARS:
            try:
                from api.services.workflow.knowledge_base_retrieval import embed_and_store_chunks
                chunk_ids = [c.id for c in created_chunks]
                chunk_contents = [c.content for c in created_chunks]
                await embed_and_store_chunks(
                    chunk_ids, chunk_contents,
                    organization_id=organization_id,
                    document_id=doc.id,
                    workflow_id=doc.workflow_id,
                )
            except Exception as emb_err:
                logger.warning(f"Non-fatal: failed to pre-compute embeddings during workflow gen: {emb_err}")
    
    logger.info(f"Created KB document {doc.id} with {len(chunks)} chunk(s) for organization {organization_id}")


def _apply_branching_layout(nodes: list, edges: list) -> list:
    """
    Apply intelligent branching layout to nodes based on edge connections.
    Creates a tree-like structure with proper spacing.
    """
    if not nodes:
        return nodes
    
    # Build connection maps
    node_map = {n["id"]: n for n in nodes}
    outgoing = {}  # node_id -> [target_ids]
    incoming = {}  # node_id -> [source_ids]
    
    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src and tgt:
            outgoing.setdefault(src, []).append(tgt)
            incoming.setdefault(tgt, []).append(src)
    
    # Find start node (is_start=true or startCall type with no incoming)
    start_node = None
    for node in nodes:
        if node.get("data", {}).get("is_start") or node.get("type") == "startCall":
            start_node = node
            break
    
    if not start_node:
        # Just use first node
        start_node = nodes[0]
    
    # Assign layers using BFS
    layers = {}  # node_id -> layer_number
    visited = set()
    queue = [(start_node["id"], 0)]
    
    while queue:
        node_id, layer = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        layers[node_id] = layer
        
        for target in outgoing.get(node_id, []):
            if target not in visited:
                queue.append((target, layer + 1))
    
    # Assign unvisited nodes to appropriate layers
    for node in nodes:
        if node["id"] not in layers:
            # Find if it has incoming edges from visited nodes
            sources = incoming.get(node["id"], [])
            if sources:
                max_layer = max(layers.get(s, 0) for s in sources)
                layers[node["id"]] = max_layer + 1
            else:
                layers[node["id"]] = len(set(layers.values()))
    
    # Group nodes by layer
    layer_groups = {}
    for node_id, layer in layers.items():
        layer_groups.setdefault(layer, []).append(node_id)
    
    # Position nodes with branching layout
    VERTICAL_SPACING = 400
    HORIZONTAL_SPACING = 400
    CENTER_X = 400
    
    for layer, node_ids in layer_groups.items():
        y_pos = 80 + (layer * VERTICAL_SPACING)
        node_count = len(node_ids)
        
        if node_count == 1:
            # Single node - center it
            node_map[node_ids[0]]["position"] = {"x": CENTER_X, "y": y_pos}
        else:
            # Multiple nodes - spread horizontally
            total_width = (node_count - 1) * HORIZONTAL_SPACING
            start_x = CENTER_X - (total_width / 2)
            
            for i, node_id in enumerate(node_ids):
                x_pos = start_x + (i * HORIZONTAL_SPACING)
                node_map[node_id]["position"] = {"x": x_pos, "y": y_pos}
    
    return list(node_map.values())


def _ensure_exit_conditions(nodes: list) -> list:
    """
    Ensure all nodes have proper exit conditions for workflow validation.
    
    Validation requires:
    - Edges from startCall and agentNode MUST have a non-empty condition
    - The condition MUST match an exit_condition name on the source node
    """
    import uuid
    
    for node in nodes:
        # Defensive: skip invalid nodes
        if not isinstance(node, dict):
            logger.warning(f"Skipping invalid node (not a dict): {node}")
            continue
            
        node_type = node.get("type", "")
        node_data = node.get("data", {})
        node_id = node.get("id", "")
        
        # Handle case where node data is not a dict
        if not isinstance(node_data, dict):
            logger.warning(f"Node data is not a dict for node {node_id}, resetting to empty dict")
            node_data = {}
            node["data"] = node_data
        
        # Skip globalNode and endCall - they don't need exit conditions
        if node_type in ["globalNode", "endCall"] or node_data.get("is_end"):
            continue
        
        exit_conditions = node_data.get("exit_conditions", [])
        
        # Ensure exit_conditions is a list
        if not isinstance(exit_conditions, list):
            exit_conditions = []
        
        # Filter out non-dict exit conditions (LLM might return invalid data)
        exit_conditions = [ec for ec in exit_conditions if isinstance(ec, dict)]
        
        # STARTCALL: Must have at least one exit condition (greeting_complete/continue)
        if node_type == "startCall" or node_data.get("is_start"):
            has_start_exit = any(
                ec.get("name", "").lower() in ["greeting_complete", "continue", "start", "proceed", "begin"]
                for ec in exit_conditions
            )
            if not has_start_exit:
                exit_conditions.append({
                    "id": f"exit-start-{uuid.uuid4().hex[:6]}",
                    "name": "greeting_complete",
                    "llm_description": "The greeting is complete and ready to proceed to the next step"
                })
                logger.info(f"Added 'greeting_complete' exit condition to start node '{node_data.get('name', node_id)}'")
        
        # AGENTNODE: Must have at least task_complete and proper exit conditions
        elif node_type == "agentNode":
            # Check if any exit condition exists
            if not exit_conditions:
                # Add default exit conditions for agent nodes
                exit_conditions.append({
                    "id": f"exit-complete-{uuid.uuid4().hex[:6]}",
                    "name": "task_complete",
                    "llm_description": "The task is complete, user is satisfied, or user says goodbye"
                })
                exit_conditions.append({
                    "id": f"exit-next-{uuid.uuid4().hex[:6]}",
                    "name": "continue",
                    "llm_description": "Continue to the next step in the workflow"
                })
                logger.info(f"Added default exit conditions to agent node '{node_data.get('name', node_id)}'")
            else:
                # Ensure at least one completion exit exists
                has_complete_exit = any(
                    ec.get("name", "").lower() in ["task_complete", "end_call", "done", "goodbye", "complete", "finished"]
                    for ec in exit_conditions
                )
                if not has_complete_exit:
                    exit_conditions.append({
                        "id": f"exit-complete-{uuid.uuid4().hex[:6]}",
                        "name": "task_complete",
                        "llm_description": "The task is complete, user is satisfied, or user says goodbye"
                    })
                    logger.info(f"Added 'task_complete' exit condition to agent node '{node_data.get('name', node_id)}'")
        
        # Update node data with fixed exit conditions
        node_data["exit_conditions"] = exit_conditions
        node["data"] = node_data
    
    return nodes


def _fix_edges(nodes: list, edges: list) -> list:
    """
    Post-process edges - PRESERVE LLM's branching structure.
    Ensure all exit conditions have corresponding edges.
    """
    logger.debug(f"Processing edges: {len(nodes)} nodes, {len(edges)} edges")
    
    node_ids = {n["id"] for n in nodes}
    node_map = {n["id"]: n for n in nodes}
    final_edges = []
    
    # Track which (source, condition) pairs already have edges
    existing_edge_conditions = set()
    
    # Process existing edges from LLM - preserve the branching!
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        
        # Skip invalid edges
        if not source or not target:
            continue
        if source not in node_ids or target not in node_ids:
            logger.warning(f"Skipping edge with invalid node: {source} -> {target}")
            continue
        
        # Ensure edge has required fields
        edge_id = edge.get("id", f"edge-{uuid.uuid4().hex[:8]}")
        edge_data = edge.get("data", {})
        
        # Handle case where data is not a dict (LLM might return invalid data)
        if not isinstance(edge_data, dict):
            logger.warning(f"Edge data is not a dict for edge {edge_id}, resetting to empty dict")
            edge_data = {}
        
        condition = edge_data.get("condition", "")
        
        # Get source node type to determine appropriate default condition
        source_node = node_map.get(source, {})
        source_type = source_node.get("type", "")
        source_data = source_node.get("data", {})
        
        # CRITICAL: Ensure edges from startCall and agentNode have proper conditions
        if not condition or condition.strip() == "":
            if source_type == "startCall" or source_data.get("is_start"):
                # Use greeting_complete for start node edges
                condition = "greeting_complete"
            elif source_type == "agentNode":
                # Try to find a matching exit condition name
                exit_conditions = source_data.get("exit_conditions", [])
                if exit_conditions:
                    condition = exit_conditions[0].get("name", "continue")
                else:
                    condition = "continue"
            else:
                condition = "continue"
        
        # Clean up the edge - remove sourceHandle/targetHandle (causes floating edges)
        # Ensure condition is a string
        if not isinstance(condition, str):
            condition = str(condition) if condition else "continue"
        
        label = edge_data.get("label", "")
        if not isinstance(label, str):
            label = condition.replace("_", " ").title()
        elif not label:
            label = condition.replace("_", " ").title()
        
        clean_edge = {
            "id": edge_id,
            "source": source,
            "target": target,
            "type": "custom",
            "animated": True,
            "data": {
                "condition": condition,
                "label": label
            }
            # NOTE: Do NOT include sourceHandle/targetHandle - they cause floating edges
        }
        
        final_edges.append(clean_edge)
        existing_edge_conditions.add((source, condition.lower()))
        logger.debug(f"Preserved edge: {source} -> {target} (condition: {condition})")
    
    # Find end node for fallback connections
    end_node_id = None
    for node in nodes:
        if node.get("type") == "endCall" or node.get("data", {}).get("is_end"):
            end_node_id = node["id"]
            break
    
    # Check all nodes for exit_conditions without edges and create missing edges
    for node in nodes:
        node_id = node["id"]
        node_type = node.get("type", "")
        node_data = node.get("data", {})
        exit_conditions = node_data.get("exit_conditions", [])
        
        # Skip globalNode and endCall nodes
        if node_type == "globalNode" or node_type == "endCall" or node_data.get("is_end"):
            continue
        
        for exit_cond in exit_conditions:
            # Skip if exit_cond is not a dict
            if not isinstance(exit_cond, dict):
                logger.warning(f"Skipping invalid exit condition (not a dict): {exit_cond}")
                continue
            
            exit_id = exit_cond.get("id", "")
            exit_name = exit_cond.get("name", "")
            
            if not exit_name:
                continue
            
            # Check if this exit condition already has an edge
            condition_key = (node_id, exit_name.lower())
            if condition_key in existing_edge_conditions:
                continue
            
            # Also check by exit_id in case condition is stored differently
            condition_key_by_id = (node_id, exit_id.lower()) if exit_id else None
            if condition_key_by_id and condition_key_by_id in existing_edge_conditions:
                continue
            
            # This exit condition doesn't have an edge - create one to end node
            if end_node_id:
                logger.warning(f"Creating missing edge for exit condition '{exit_name}' on node '{node_id}'")
                new_edge = {
                    "id": f"edge-{uuid.uuid4().hex[:8]}",
                    "source": node_id,
                    "target": end_node_id,
                    "type": "custom",
                    "animated": True,
                    "data": {
                        "condition": exit_name,
                        "label": exit_name.replace("_", " ").title()
                    }
                }
                final_edges.append(new_edge)
                existing_edge_conditions.add(condition_key)
    
    # CRITICAL: Ensure every agent node has at least one exit to End Call
    # This prevents calls from hanging after task completion
    if end_node_id:
        for node in nodes:
            node_id = node["id"]
            node_type = node.get("type", "")
            node_data = node.get("data", {})
            
            # Skip globalNode, startCall, and endCall nodes
            if node_type in ["globalNode", "endCall"] or node_data.get("is_end") or node_data.get("is_start"):
                continue
            
            # Check if this node has any edge leading to end node
            has_end_edge = any(
                e.get("source") == node_id and e.get("target") == end_node_id 
                for e in final_edges
            )
            
            if not has_end_edge and node_type == "agentNode":
                # Add a "task_complete" exit condition if not exists
                exit_conditions = node_data.get("exit_conditions", [])
                has_complete_exit = any(
                    ec.get("name", "").lower() in ["task_complete", "end_call", "done", "goodbye", "complete"]
                    for ec in exit_conditions
                )
                
                if not has_complete_exit:
                    # Add exit condition to node data
                    complete_exit_id = f"exit-complete-{uuid.uuid4().hex[:6]}"
                    exit_conditions.append({
                        "id": complete_exit_id,
                        "name": "task_complete",
                        "llm_description": "The task is complete, user says goodbye, or user wants to end the call"
                    })
                    node_data["exit_conditions"] = exit_conditions
                    logger.info(f"Added 'task_complete' exit condition to node '{node_data.get('name', node_id)}'")
                
                # Create edge to end node
                new_edge = {
                    "id": f"edge-end-{uuid.uuid4().hex[:8]}",
                    "source": node_id,
                    "target": end_node_id,
                    "type": "custom",
                    "animated": True,
                    "data": {
                        "condition": "task_complete",
                        "label": "Task Complete"
                    }
                }
                final_edges.append(new_edge)
                logger.info(f"Added end call edge for node '{node_data.get('name', node_id)}'")
    
    # If LLM didn't generate any valid edges, fall back to sequential
    if not final_edges:
        logger.warning("No valid edges from LLM, creating sequential fallback")
        sorted_nodes = sorted(nodes, key=lambda n: n.get("position", {}).get("y", 0))
        
        for i in range(len(sorted_nodes) - 1):
            current = sorted_nodes[i]
            next_node = sorted_nodes[i + 1]
            
            final_edges.append({
                "id": f"edge-{uuid.uuid4().hex[:8]}",
                "source": current["id"],
                "target": next_node["id"],
                "type": "custom",
                "animated": True,
                "data": {
                    "condition": "continue",
                    "label": f"To {next_node.get('data', {}).get('name', 'Next')}"
                }
            })
    
    # CLEANUP: Remove duplicate edges (same source + target + condition)
    seen_edges = set()
    deduplicated_edges = []
    for edge in final_edges:
        edge_key = (edge["source"], edge["target"], edge.get("data", {}).get("condition", ""))
        if edge_key not in seen_edges:
            seen_edges.add(edge_key)
            deduplicated_edges.append(edge)
        else:
            logger.warning(f"Removing duplicate edge: {edge['source']} -> {edge['target']} (condition: {edge.get('data', {}).get('condition')})")
    
    # CLEANUP: Remove orphan edges (edges to/from non-existent nodes) - final check
    valid_edges = []
    for edge in deduplicated_edges:
        if edge["source"] in node_ids and edge["target"] in node_ids:
            # Final sanitization - remove any handle fields that cause floating edges
            sanitized_edge = {
                "id": edge.get("id", f"edge-{uuid.uuid4().hex[:8]}"),
                "source": edge["source"],
                "target": edge["target"],
                "type": "custom",
                "animated": True,
                "data": {
                    "condition": edge.get("data", {}).get("condition", "") or "",
                    "label": edge.get("data", {}).get("label", "") or ""
                }
            }
            valid_edges.append(sanitized_edge)
        else:
            logger.warning(f"Removing orphan edge: {edge['source']} -> {edge['target']}")
    
    logger.info(f"Final edge count: {len(valid_edges)} (removed {len(final_edges) - len(valid_edges)} invalid/duplicate edges)")
    return valid_edges


def _create_basic_template(call_type: str, use_case: str, activity_description: str) -> dict:
    """Create a basic workflow template when AI generation fails."""

    if call_type == "MEETING":
        trigger_id = f"trigger-{uuid.uuid4().hex[:8]}"
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        summary_id = f"summary-{uuid.uuid4().hex[:8]}"

        return {
            "name": use_case,
            "workflow_definition": {
                "nodes": [
                    {
                        "id": trigger_id,
                        "type": "meetingTrigger",
                        "position": {"x": 400, "y": 80},
                        "measured": {"width": 320, "height": 180},
                        "data": {
                            "name": "Wake Word Trigger",
                            "trigger_config": {"mode": "wake_word", "wake_words": ["hey agent"], "cooldown_seconds": 2},
                            "response_prompt": "Listening for questions..."
                        }
                    },
                    {
                        "id": agent_id,
                        "type": "agentNode",
                        "position": {"x": 400, "y": 380},
                        "measured": {"width": 320, "height": 180},
                        "data": {
                            "prompt": f"You are a passive meeting assistant for {use_case.lower()}. {activity_description}\n\nDo NOT introduce yourself or greet anyone. Only respond when directly addressed. Keep answers brief and factual.",
                            "name": "Meeting Assistant",
                            "is_static": False,
                            "allow_interrupt": True,
                            "add_global_prompt": True,
                            "exit_conditions": [
                                {
                                    "id": f"exit-{uuid.uuid4().hex[:6]}",
                                    "name": "question_answered",
                                    "llm_description": "The user's question has been answered, return to listening"
                                }
                            ]
                        }
                    },
                    {
                        "id": summary_id,
                        "type": "meetingSummary",
                        "position": {"x": 400, "y": 680},
                        "measured": {"width": 320, "height": 180},
                        "data": {
                            "name": "Meeting Summary",
                            "summary_config": {"mode": "end_of_meeting", "include_action_items": True, "include_decisions": True, "include_key_points": True},
                            "output_format": "markdown"
                        }
                    }
                ],
                "edges": [
                    {
                        "id": f"edge-{uuid.uuid4().hex[:8]}",
                        "source": trigger_id,
                        "target": agent_id,
                        "type": "custom",
                        "animated": True,
                        "data": {"condition": "", "label": "Wake Word Detected"}
                    },
                    {
                        "id": f"edge-{uuid.uuid4().hex[:8]}",
                        "source": agent_id,
                        "target": summary_id,
                        "type": "custom",
                        "animated": True,
                        "data": {"condition": "question_answered", "label": "Done"}
                    }
                ],
                "viewport": {"x": 0, "y": 0, "zoom": 1}
            }
        }

    if call_type == "WEBSITE":
        greeting = f"Hi! Welcome! I'm your virtual assistant and I can help you with {use_case.lower()}. What would you like to know?"
    elif call_type == "INBOUND":
        greeting = f"Hello! Thank you for calling. I'm here to help you with {use_case.lower()}. How can I assist you today?"
    else:
        greeting = f"Hello! I'm calling regarding {use_case.lower()}. Do you have a moment to talk?"
    
    start_id = f"start-{uuid.uuid4().hex[:8]}"
    agent_id = f"agent-{uuid.uuid4().hex[:8]}"
    end_id = f"end-{uuid.uuid4().hex[:8]}"
    exit_id = f"exit-{uuid.uuid4().hex[:8]}"
    
    return {
        "name": use_case,
        "workflow_definition": {
            "nodes": [
                {
                    "id": start_id,
                    "type": "startCall",
                    "position": {"x": 400, "y": 80},
                    "measured": {"width": 320, "height": 180},
                    "data": {
                        "prompt": greeting,
                        "name": "Start Call",
                        "is_start": True,
                        "is_static": False,
                        "allow_interrupt": True,
                        "add_global_prompt": True,
                        "exit_conditions": [
                            {
                                "id": f"exit-start-{uuid.uuid4().hex[:6]}",
                                "name": "greeting_complete",
                                "llm_description": "The greeting is complete and ready to proceed"
                            }
                        ]
                    }
                },
                {
                    "id": agent_id,
                    "type": "agentNode",
                    "position": {"x": 400, "y": 430},
                    "measured": {"width": 320, "height": 180},
                    "data": {
                        "prompt": f"You are a helpful voice assistant for {use_case.lower()}. {activity_description}\n\nBe conversational, friendly, and helpful. Ask clarifying questions when needed. Keep responses concise since this is a voice conversation.",
                        "name": "Main Conversation",
                        "is_static": False,
                        "allow_interrupt": True,
                        "add_global_prompt": True,
                        "exit_conditions": [
                            {
                                "id": exit_id,
                                "name": "task_complete",
                                "llm_description": "The user's request has been fully addressed, they say goodbye, or they want to end the call"
                            }
                        ]
                    }
                },
                {
                    "id": end_id,
                    "type": "endCall",
                    "position": {"x": 400, "y": 780},
                    "measured": {"width": 320, "height": 180},
                    "data": {
                        "prompt": "Thank you for your time! Have a great day. Goodbye!",
                        "name": "End Call",
                        "is_end": True,
                        "is_static": False,
                        "allow_interrupt": False
                    }
                }
            ],
            "edges": [
                {
                    "id": f"edge-{uuid.uuid4().hex[:8]}",
                    "source": start_id,
                    "target": agent_id,
                    "type": "custom",
                    "animated": True,
                    "data": {"condition": "greeting_complete", "label": "Greeting Complete"}
                },
                {
                    "id": f"edge-{uuid.uuid4().hex[:8]}",
                    "source": agent_id,
                    "target": end_id,
                    "type": "custom",
                    "animated": True,
                    "data": {"condition": "task_complete", "label": "Task Complete"}
                }
            ],
            "viewport": {"x": 0, "y": 0, "zoom": 1}
        }
    }

