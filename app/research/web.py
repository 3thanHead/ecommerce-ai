"""Keyless page reader. `r.jina.ai` fetches a URL server-side and returns clean,
LLM-ready markdown -- which is how the Reddit client reads listing pages even
when this box's IP is blocked from Reddit directly. Degrades to "" on failure.
"""
import logging

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


async def read_url(url: str, max_chars: int = 6000) -> str:
    """Fetch a page as markdown via r.jina.ai. Empty string on failure."""
    base = get_settings().jina_reader_base.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(f"{base}/{url}")
            r.raise_for_status()
        return r.text[:max_chars]
    except Exception as e:
        log.warning("read_url failed for %s (%s)", url, e)
        return ""
