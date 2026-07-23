"""Stage 2 -- drill a category down into real Reddit discussion, then surface
concrete product opportunities grounded in what people actually talk about.

This is where the flow touches the network (so stage 1 stays instant): pull real
threads from the category's subreddits, then have the model read them and name
specific products to source -- each with a `cj_search_seed`, the phrase Feature 2
will throw at CJdropshipping to correlate an actual product (info/images/videos).

The model also re-checks the category's saturation now that it has real evidence,
so the leaderboard number can be refined from a guess to an informed read.
"""
import asyncio
import logging

from ..llm import get_llm
from .reddit import Thread, get_reddit

log = logging.getLogger(__name__)

MAX_THREADS = 30

_SYS = """You are a product researcher for a dropshipping operator sourcing from
CJdropshipping. You are given a product category and REAL Reddit threads from the
communities that category's buyers hang out in. Read what people actually want,
complain about, and show off, then surface concrete PRODUCTS to source.

For each opportunity, give a `cj_search_seed`: the short phrase to search on
CJdropshipping to find a matching product (e.g. "linen cable organizer", not
"cozy vibes"). Ground every pick in the threads -- cite the thread themes.

Also re-rate the category's saturation 0-100 now that you've seen real demand
signal (0 = wide open, 100 = crowded), and say what changed your mind, if anything.

Output JSON only:
{
  "saturation": 0-100,
  "saturation_reasoning": "what the threads tell you about crowding",
  "opportunities": [
    {
      "product": "the specific product to sell",
      "rationale": "why the threads support it",
      "evidence": ["short quote or thread theme that backs it"],
      "cj_search_seed": "phrase to search on CJdropshipping",
      "demand_signal": 0-100
    }
  ]
}
Return 3-6 opportunities, strongest first."""


def _clamp(v) -> int:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return 50


async def _gather(reddit, subreddits: list[str]) -> tuple[list[Thread], str]:
    """Real threads for these subreddits: direct where possible, else the Jina
    page-read floor. Returns (threads, source_note)."""
    subs = [s for s in subreddits if s][:5]
    pooled: dict[str, Thread] = {}
    if reddit.using_api:
        results = await asyncio.gather(
            *(reddit.top(s, time_filter="year", limit=15) for s in subs),
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, Exception):
                continue
            for t in res:
                pooled[t.id] = t
        if len(pooled) >= 5:
            return list(pooled.values()), "direct"
    # keyless floor (works even when this box's IP is blocked)
    for t in await reddit.discover(subs, max_pages=5):
        pooled.setdefault(t.id, t)
    return list(pooled.values()), ("discovery" if pooled else "none")


def _thread_block(threads: list[Thread]) -> str:
    lines = []
    for t in sorted(threads, key=lambda x: x.score, reverse=True)[:MAX_THREADS]:
        sig = f" [{t.score} pts]" if t.score else ""
        body = f" -- {t.selftext[:160]}" if t.selftext else ""
        lines.append(f"[r/{t.subreddit}]{sig} {t.title}{body}")
    return "\n".join(lines)


async def drill(
    category: str,
    subreddits: list[str],
    audience: str = "",
    model: str | None = None,
) -> dict:
    """Turn one category into Reddit-grounded product opportunities."""
    llm = get_llm()
    reddit = get_reddit()

    threads, source = await _gather(reddit, subreddits)
    block = _thread_block(threads)

    user = (
        f"Category: {category}\n"
        f"Audience: {audience or '(unspecified)'}\n\n"
        f"REAL REDDIT THREADS ({len(threads)} from r/{', r/'.join(subreddits[:5])}):\n"
        f"{block or '(none retrieved -- infer cautiously from the category alone)'}"
    )
    try:
        data = await llm.json(_SYS, user, model=model, temperature=0.4)
    except Exception as e:
        log.warning("drill failed (%s)", e)
        data = {}

    opps = []
    for o in data.get("opportunities", []) if isinstance(data, dict) else []:
        if not isinstance(o, dict) or not o.get("product"):
            continue
        o["demand_signal"] = _clamp(o.get("demand_signal"))
        for k in ("evidence",):
            if not isinstance(o.get(k), list):
                o[k] = []
        o.setdefault("cj_search_seed", o["product"])
        opps.append(o)

    return {
        "category": category,
        "audience": audience,
        "reddit_source": source,
        "saturation": _clamp(data.get("saturation")) if isinstance(data, dict) else 50,
        "saturation_reasoning": data.get("saturation_reasoning", "") if isinstance(data, dict) else "",
        "opportunities": opps,
        "threads_sampled": [t.dict() for t in sorted(threads, key=lambda x: x.score, reverse=True)[:MAX_THREADS]],
    }
