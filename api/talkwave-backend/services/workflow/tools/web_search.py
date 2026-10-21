"""Provider-agnostic realtime web search for voice agents.

The agent-facing ``search_web`` function tool works with ANY LLM provider
(Cerebras, OpenAI, Groq, Gemini, ...) because it is a plain function call —
unlike OpenAI's ``web_search_preview`` or Gemini's ``google_search`` native
tools, which only work on their own APIs.

Providers are tried in order of configuration:

1. Tavily  (``TAVILY_API_KEY``)  — purpose-built for LLMs, returns a direct answer.
2. Serper  (``SERPER_API_KEY``)  — Google results, very fast.
3. Brave   (``BRAVE_SEARCH_API_KEY``) — independent index.

Results are compacted for voice: a short answer plus a few trimmed snippets so
the LLM can respond in one turn without flooding its context.
"""

import os
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

# Keep the search fast — a voice caller is waiting. Providers usually answer
# in <2s; anything slower is worse than saying "I couldn't find that".
_SEARCH_TIMEOUT_SECONDS = 6.0
_MAX_SNIPPET_CHARS = 400

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    """Shared client so repeated searches in a call reuse connections."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_SEARCH_TIMEOUT_SECONDS)
    return _client


def _trim(text: str, limit: int = _MAX_SNIPPET_CHARS) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def _search_tavily(query: str, max_results: int) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return None
    resp = await _get_client().post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": True,
            "search_depth": "basic",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    results = [
        {"title": r.get("title", ""), "snippet": _trim(r.get("content", "")), "url": r.get("url", "")}
        for r in (data.get("results") or [])[:max_results]
    ]
    return {"answer": data.get("answer") or "", "results": results, "provider": "tavily"}


async def _search_serper(query: str, max_results: int) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        return None
    resp = await _get_client().post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "num": max_results},
    )
    resp.raise_for_status()
    data = resp.json()

    answer = ""
    answer_box = data.get("answerBox") or {}
    if answer_box:
        answer = answer_box.get("answer") or answer_box.get("snippet") or ""
    kg = data.get("knowledgeGraph") or {}
    if not answer and kg.get("description"):
        answer = kg["description"]

    results = [
        {"title": r.get("title", ""), "snippet": _trim(r.get("snippet", "")), "url": r.get("link", "")}
        for r in (data.get("organic") or [])[:max_results]
    ]
    return {"answer": answer, "results": results, "provider": "serper"}


async def _search_brave(query: str, max_results: int) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return None
    resp = await _get_client().get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": max_results},
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()
    web_results = ((data.get("web") or {}).get("results")) or []
    results = [
        {"title": r.get("title", ""), "snippet": _trim(r.get("description", "")), "url": r.get("url", "")}
        for r in web_results[:max_results]
    ]
    return {"answer": "", "results": results, "provider": "brave"}


def is_web_search_configured() -> bool:
    """True when at least one search provider API key is set."""
    return bool(
        os.getenv("TAVILY_API_KEY")
        or os.getenv("SERPER_API_KEY")
        or os.getenv("BRAVE_SEARCH_API_KEY")
    )


async def search_web(query: str, max_results: int = 4) -> Dict[str, Any]:
    """Search the internet and return a compact, voice-friendly result dict.

    Returns ``{"answer": str, "results": [{title, snippet, url}], "provider": str}``
    or ``{"error": str}`` when no provider is configured / all providers fail.
    """
    query = (query or "").strip()
    if not query:
        return {"error": "Empty search query"}

    providers = (
        ("tavily", _search_tavily),
        ("serper", _search_serper),
        ("brave", _search_brave),
    )

    configured_any = False
    for name, fn in providers:
        try:
            result = await fn(query, max_results)
        except Exception as e:
            configured_any = True
            logger.warning(f"🌐 [WEB SEARCH] Provider '{name}' failed: {e}")
            continue
        if result is None:
            continue  # provider not configured
        configured_any = True
        logger.info(
            f"🌐 [WEB SEARCH] '{query[:80]}' answered by {name} "
            f"({len(result.get('results', []))} results)"
        )
        return result

    if not configured_any:
        logger.warning(
            "🌐 [WEB SEARCH] No search provider configured — set TAVILY_API_KEY, "
            "SERPER_API_KEY or BRAVE_SEARCH_API_KEY"
        )
        return {
            "error": (
                "Web search is not configured on this server. Answer from your "
                "own knowledge and be transparent about uncertainty."
            )
        }
    return {"error": "All web search providers failed. Try rephrasing the query."}


def get_web_search_tool() -> Dict[str, Any]:
    """OpenAI-style function schema for the ``search_web`` tool."""
    return {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Search the internet for real-time, up-to-date information "
                "(news, prices, weather, facts, business info, anything outside "
                "your training data). Keep queries short and specific."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query, e.g. 'current gold price USD'",
                    }
                },
                "required": ["query"],
            },
        },
    }
