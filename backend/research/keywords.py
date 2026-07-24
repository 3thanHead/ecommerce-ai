"""Keyword expansion via Google Suggest -- free, keyless. Now scoped PER CATEGORY
(seeded by the category/product name) rather than one global list, so each
category carries its own long-tail demand terms.

Suggest answers one prefix at a time (~10 phrases); we re-ask under buyer-intent
modifiers and pool the results. `freq` (how many prefixes surfaced a phrase) is
an honest popularity proxy -- no free source gives real search volume.
"""
import asyncio
import logging
from collections import Counter

import httpx

log = logging.getLogger(__name__)

_MODIFIERS = [
    "{s}",
    "best {s}",
    "{s} for",
    "{s} gifts",
    "{s} ideas",
    "cheap {s}",
    "custom {s}",
    "{s} online",
]


async def _suggest(client: httpx.AsyncClient, prefix: str) -> list[str]:
    try:
        r = await client.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "q": prefix},
        )
        r.raise_for_status()
        return list(r.json()[1])  # [query, [suggestions...], ...]
    except Exception as e:
        log.debug("suggest failed for %r: %s", prefix, e)
        return []


async def expand_keywords(seed: str, limit: int = 20) -> list[dict]:
    """Return [{phrase, freq}] for one category seed, ranked by prefix frequency."""
    prefixes = [m.format(s=seed) for m in _MODIFIERS]
    counts: Counter[str] = Counter()
    async with httpx.AsyncClient(timeout=10.0) as client:
        results = await asyncio.gather(*(_suggest(client, p) for p in prefixes))
    for phrases in results:
        for phrase in phrases:
            counts[phrase.lower().strip()] += 1
    return [{"phrase": p, "freq": f} for p, f in counts.most_common(limit) if p]
