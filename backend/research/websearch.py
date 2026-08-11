"""General web search via a local, keyless SearXNG instance (docker-compose.yml
runs it: services `searxng` + `redis`). This is the supply side of the
web-research agent's one tool (see agents/web-research.md /
backend/research/webresearch.py) -- everything here is a plain HTTP call, no
LLM involved.

Fail-soft like every other provider in this codebase: unconfigured,
unreachable, or erroring just yields an empty result list, never raises. A
private, non-internet-exposed instance (no host port published in
docker-compose.yml -- only `app` can reach it, over the compose network).
"""
import logging

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


async def search(query: str, count: int = 5) -> list[dict]:
    """Real, current web results for `query` -> [{title, url, snippet}], best
    first. Empty list if SearXNG isn't configured/reachable/returned nothing."""
    s = get_settings()
    if not s.has_searxng:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{s.searxng_base_url}/search",
                params={"q": query, "format": "json"},
            )
            r.raise_for_status()
            results = r.json().get("results", [])
    except Exception as e:
        log.warning("SearXNG search failed for %r (%s)", query, e)
        return []
    return [
        {
            "title": (row.get("title") or "").strip(),
            "url": row.get("url") or "",
            "snippet": (row.get("content") or "").strip(),
        }
        for row in results[:count]
        if row.get("title") and row.get("url")
    ]


async def health() -> dict:
    """Is SearXNG configured + a live query probe (for the diagnostics
    endpoint, same shape as reddit.health() / saturation.health())."""
    s = get_settings()
    row = {"name": "searxng", "configured": s.has_searxng}
    if s.has_searxng:
        results = await search("desk mat", count=1)
        row["ok"] = bool(results)
    return row
