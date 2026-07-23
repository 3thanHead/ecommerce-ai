"""Keyless-capable page reader. Both backends fetch a URL SERVER-SIDE and return
clean markdown, so this box's IP block on Reddit doesn't matter.

- Firecrawl (preferred when FIRECRAWL_API_KEY is set): rotating IPs, renders JS,
  reliably reads sites that block scrapers -- exactly Reddit's situation. Free
  tier is 1,000 credits/month (1 credit/page), no card. ~200 drills/month free.
- Jina r.jina.ai (fallback, keyless but rate-limited/often blocked on Reddit).

read_url() prefers Firecrawl, falls back to Jina, and degrades to "" on failure.
active_reader() reports which one is in play (for the diagnostic).
"""
import logging

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


def active_reader() -> str:
    return "firecrawl" if get_settings().firecrawl_api_key else "jina"


async def _firecrawl(url: str, key: str, max_chars: int) -> str:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                "https://api.firecrawl.dev/v1/scrape",
                headers={"Authorization": f"Bearer {key}"},
                json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            )
            r.raise_for_status()
            md = r.json().get("data", {}).get("markdown", "")
        return (md or "")[:max_chars]
    except Exception as e:
        log.warning("firecrawl read failed for %s (%s)", url, e)
        return ""


async def _jina(url: str, base: str, max_chars: int) -> str:
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(f"{base.rstrip('/')}/{url}")
            r.raise_for_status()
        return r.text[:max_chars]
    except Exception as e:
        log.warning("jina read failed for %s (%s)", url, e)
        return ""


async def read_url(url: str, max_chars: int = 6000) -> str:
    """Fetch a page as markdown. Firecrawl if keyed, else Jina. "" on failure."""
    s = get_settings()
    if s.firecrawl_api_key:
        md = await _firecrawl(url, s.firecrawl_api_key, max_chars)
        if md:
            return md
        # Firecrawl empty (rare) -> still try the keyless reader.
    return await _jina(url, s.jina_reader_base, max_chars)
