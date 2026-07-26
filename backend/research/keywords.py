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


# ------------------------- demand probe (for stage 1) ---------------------
# A cheap, keyless proxy for "do people actually search to BUY this?" -- how many
# distinct autocompletes a seed produces under buyer-intent prefixes. A product
# nobody shops for returns almost nothing; a real one autocompletes richly. It's
# breadth, not volume (no free source gives volume), but it's enough to keep the
# descent from bottoming out in niches nobody buys.
_DEMAND_PREFIXES = ["{s}", "best {s}", "{s} for", "buy {s}", "{s} reviews"]
# ~this many distinct buyer-intent autocompletes reads as full demand. Tuned to
# NICHE product phrases, which rarely autocomplete richly -- ~12-20 distinct is a
# genuinely-shopped niche, so it should read as strong demand, not middling. (Was
# 40, which pinned even good niches down near 30.)
_DEMAND_FULL = 22


async def _demand_count(client: httpx.AsyncClient, seed: str) -> int | None:
    try:
        results = await asyncio.gather(
            *(_suggest(client, m.format(s=seed)) for m in _DEMAND_PREFIXES)
        )
    except Exception as e:
        log.debug("demand probe failed for %r: %s", seed, e)
        return None
    return len({p.lower().strip() for r in results for p in r if p})


def _score_demand(count: int) -> int:
    return max(0, min(100, round(count / _DEMAND_FULL * 100)))


async def demand_batch(seeds: list[str], concurrency: int = 8) -> list[int | None]:
    """Demand score (0-100) per seed, or None where Google Suggest didn't answer.

    Suggest is fast and unthrottled compared to the supplier lookups, so this runs
    in parallel with them and adds ~no wall-clock. None -> caller falls back to
    openness alone for that item (so a Suggest outage degrades, not breaks)."""
    sem = asyncio.Semaphore(concurrency)

    async def one(client, seed):
        async with sem:
            cnt = await _demand_count(client, seed)
        return None if cnt is None else _score_demand(cnt)

    async with httpx.AsyncClient(timeout=10.0) as client:
        return await asyncio.gather(*(one(client, s) for s in seeds))
