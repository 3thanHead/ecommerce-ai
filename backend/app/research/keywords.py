"""Keyword expansion via Google Suggest -- free, keyless, and the only way to
the long tail people actually type.

Suggest answers ONE prefix at a time (~10 phrases). We re-ask the same endpoint
under many prefixes -- the seed plus buyer-intent modifiers ("best <seed>",
"<seed> for", "<seed> gifts", ...) -- and pool the results. `freq` (how many
prefixes surfaced a phrase) is an honest popularity proxy; no free source gives
real search volume, so we don't pretend to.
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
    "cute {s}",
    "cheap {s}",
    "{s} accessories",
    "personalized {s}",
    "{s} online",
]


async def _suggest(client: httpx.AsyncClient, prefix: str) -> list[str]:
    try:
        r = await client.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "q": prefix},
        )
        r.raise_for_status()
        # Response is [query, [suggestions...], ...]
        return list(r.json()[1])
    except Exception as e:
        log.debug("suggest failed for %r: %s", prefix, e)
        return []


async def expand_keywords(seed: str, limit: int = 40) -> list[dict]:
    """Return [{phrase, freq}] ranked by how many prefixes surfaced each phrase."""
    prefixes = [m.format(s=seed) for m in _MODIFIERS]
    counts: Counter[str] = Counter()
    async with httpx.AsyncClient(timeout=10.0) as client:
        results = await asyncio.gather(*(_suggest(client, p) for p in prefixes))
    for phrases in results:
        for phrase in phrases:
            counts[phrase.lower().strip()] += 1
    ranked = counts.most_common(limit)
    return [{"phrase": p, "freq": f} for p, f in ranked if p]
