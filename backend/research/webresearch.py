"""General web evidence for a category, via a tool-calling agent over a local
SearXNG instance (backend/research/websearch.py does the actual HTTP call;
this module is the agent that decides what to search for and synthesizes the
results). Prompt + tool def + schema: agents/web-research.md. Feeds drill()
as a third evidence source alongside Reddit -- see drilldown.py.

Same fail-soft posture as everything else here: no SearXNG configured, or the
model never finds anything worth keeping, just means an empty findings list,
not an error.
"""
import json
import logging

from ..agent import ToolAgent
from ..progress import Steps
from . import websearch

log = logging.getLogger(__name__)


async def _web_search_tool(arguments: dict) -> str:
    """The `web_search` tool's implementation -- real HTTP, no LLM involved.
    Stringified for the "tool" role message the model reads back."""
    query = str(arguments.get("query", "")).strip()
    if not query:
        return "error: no query given"
    results = await websearch.search(query)
    if not results:
        return "no results"
    return json.dumps(results)


# Prompt + tool def + schema: agents/web-research.md.
_agent = ToolAgent("web-research", tools={"web_search": _web_search_tool}, max_rounds=4)


async def research(seed: str, category: str, audience: str = "",
                   model: str | None = None, emit=None) -> dict:
    """Category -> real web findings + a short synthesis. Degrades to an empty
    findings list (source "unavailable") if SearXNG isn't configured/reachable
    or the agent never calls the tool successfully."""
    s = Steps(emit) if emit else None
    user = f"CATEGORY: {category}\nSEED PHRASE: {seed}\nAUDIENCE: {audience or '(unspecified)'}"

    label = f"Searching the open web for “{seed}”"
    try:
        if s:
            await s.running(label)
            data = await _agent.run(user, on_chunk=s.thought, model=model, temperature=0.4)
            await s.done(label)
        else:
            data = await _agent.run(user, model=model, temperature=0.4)
    except Exception as e:
        log.warning("web research failed for %r (%s)", seed, e)
        data = {}

    findings = [f for f in (data.get("findings") or []) if isinstance(f, dict) and f.get("url")]
    return {
        "findings": findings,
        "synthesis": data.get("synthesis", "") if isinstance(data, dict) else "",
        "source": "searxng" if findings else "unavailable",
    }
