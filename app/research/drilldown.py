"""Stage 2 -- drill a category into real Reddit discussion + its own long-tail
keywords, then surface concrete product opportunities grounded in both.

This is where the flow touches the network (so stage 1 stays instant): pull real
threads from the category's subreddits, expand keywords for the category, then
have the model read it all and name specific products to source -- each with a
`cj_search_seed` (the phrase Feature 2 throws at CJdropshipping). It also
re-rates saturation now that it has evidence.

Pass an `emit` callback (app/progress.py) to stream the work as named steps plus
the model's live thinking, so the UI shows it happening.
"""
import asyncio
import logging

from ..llm import get_llm, parse_json
from ..progress import Steps
from .keywords import expand_keywords
from .reddit import Thread, get_reddit

log = logging.getLogger(__name__)

MAX_THREADS = 30

_SYS = """You are a product researcher for a dropshipping operator sourcing from
CJdropshipping. You are given a product category, REAL Reddit threads from the
communities its buyers use, and long-tail keywords people search. Read what
people actually want, complain about, and show off, then surface concrete
PRODUCTS to source.

For each opportunity, give a `cj_search_seed`: the short phrase to search on
CJdropshipping to find a matching product (e.g. "linen cable organizer", not
"cozy vibes"). Ground every pick in the threads/keywords.

Also re-rate the category's saturation 0-100 now that you've seen real signal
(0 = wide open, 100 = crowded), and say what changed your mind, if anything.

Output JSON only:
{
  "saturation": 0-100,
  "saturation_reasoning": "what the signals tell you about crowding",
  "opportunities": [
    {
      "product": "the specific product to sell",
      "rationale": "why the signals support it",
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
    keyword_seed: str = "",
    emit=None,
) -> dict:
    """Turn one category into Reddit-grounded product opportunities + keywords."""
    llm = get_llm()
    reddit = get_reddit()
    s = Steps(emit) if emit else None
    subs_label = ", ".join(f"r/{x}" for x in subreddits[:5]) or "(none)"
    seed = keyword_seed or category  # short seed -> real autocomplete hits

    # Reddit + keywords in parallel.
    if s:
        await s.running(f"Reading Reddit: {subs_label}")
        await s.running(f"Expanding keywords for “{seed}”")
    (threads, source), keywords = await asyncio.gather(
        _gather(reddit, subreddits),
        expand_keywords(seed, limit=20),
    )
    if s:
        note = f"{len(threads)} threads" if threads else "blocked — reasoning from the category"
        await s.done(f"Reading Reddit: {subs_label} → {note}")
        await s.done(f"Expanding keywords for “{seed}” → {len(keywords)} phrases")

    block = _thread_block(threads)
    kw_block = ", ".join(k["phrase"] for k in keywords[:20])
    user = (
        f"Category: {category}\nAudience: {audience or '(unspecified)'}\n\n"
        f"REAL REDDIT THREADS ({len(threads)}):\n{block or '(none retrieved)'}\n\n"
        f"LONG-TAIL KEYWORDS: {kw_block or '(none)'}"
    )
    messages = [{"role": "system", "content": _SYS}, {"role": "user", "content": user}]

    label = "Reasoning over the signals to find products"
    try:
        if s:
            await s.running(label)
            raw = ""
            async for chunk in llm.chat_stream(messages, model=model, temperature=0.4):
                raw += chunk
                await s.thought(chunk)
            data = parse_json(raw)
            await s.done(label)
        else:
            data = await llm.json(_SYS, user, model=model, temperature=0.4)
    except Exception as e:
        log.warning("drill failed (%s)", e)
        data = {}

    opps = []
    for o in data.get("opportunities", []) if isinstance(data, dict) else []:
        if not isinstance(o, dict) or not o.get("product"):
            continue
        o["demand_signal"] = _clamp(o.get("demand_signal"))
        if not isinstance(o.get("evidence"), list):
            o["evidence"] = []
        o.setdefault("cj_search_seed", o["product"])
        opps.append(o)

    return {
        "category": category,
        "audience": audience,
        "reddit_source": source,
        "saturation": _clamp(data.get("saturation")) if isinstance(data, dict) else 50,
        "saturation_reasoning": data.get("saturation_reasoning", "") if isinstance(data, dict) else "",
        "opportunities": opps,
        "keywords": keywords,
        "threads_sampled": [t.dict() for t in sorted(threads, key=lambda x: x.score, reverse=True)[:MAX_THREADS]],
    }
