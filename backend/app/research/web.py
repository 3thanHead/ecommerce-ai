"""Secondary research path: a keyless web search + a page-to-markdown reader.

This is the "agent-native" angle -- it finds relevant discussion beyond the
subreddits we thought to query, and hands the LLM clean text. Both providers are
keyless defaults (DuckDuckGo lite HTML + r.jina.ai) and both DEGRADE: a failure
returns an empty list/string, never an exception, so research just gets thinner.
"""
import logging
import re

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

_RESULT_RE = re.compile(r'<a[^>]*class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


async def web_search(query: str, limit: int = 8) -> list[dict]:
    """Keyless web search via DuckDuckGo's lite endpoint -> [{title, url}]."""
    try:
        async with httpx.AsyncClient(
            timeout=15.0, headers={"User-Agent": "Mozilla/5.0 (storefront-ai research)"}
        ) as client:
            r = await client.post("https://lite.duckduckgo.com/lite/", data={"q": query})
            r.raise_for_status()
        out = []
        for href, label in _RESULT_RE.findall(r.text):
            title = _TAG_RE.sub("", label).strip()
            if href.startswith("http") and title:
                out.append({"title": title, "url": href})
            if len(out) >= limit:
                break
        return out
    except Exception as e:
        log.warning("web_search failed (%s)", e)
        return []


async def read_url(url: str, max_chars: int = 6000) -> str:
    """Fetch a page as LLM-ready markdown via r.jina.ai. Empty string on failure."""
    base = get_settings().jina_reader_base.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(f"{base}/{url}")
            r.raise_for_status()
        return r.text[:max_chars]
    except Exception as e:
        log.warning("read_url failed for %s (%s)", url, e)
        return ""
