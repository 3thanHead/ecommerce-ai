"""Stage 2 -- drill a category into real Reddit + open-web signal, then surface
products + the subreddits you could actually post them in.

Grounding chains three free sources:
  - reddit.py: PullPush finds which subreddits discuss the niche + real
    engagement; Arctic Shift profiles those subs (subscribers + rules).
  - webresearch.py: a tool-calling agent that searches the open web (via a
    local SearXNG instance) for real, current evidence -- supplementary
    context, not a platform to judge posting-fit on.
  - keywords.py: per-category long-tail buyer-intent phrases.

The drill agent then, from all of that evidence:
  - classifies each subreddit's product-posting friendliness (from its rules +
    submission type + the model's own knowledge),
  - names concrete PRODUCTS to source, each with a `cj_search_seed` for CJ,
  - re-rates saturation.

Everything degrades: dead sources just thin the evidence -- reddit_source /
web_source in the result say what actually answered. Pass `emit` to stream
the work.
"""
import asyncio
import logging

from ..agent import Agent
from ..progress import Steps
from . import reddit, webresearch
from .keywords import expand_keywords

log = logging.getLogger(__name__)

# Prompt + schema: agents/drill.md.
_agent = Agent("drill")


def _clamp(v) -> int:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return 50


def _friendly(v: str) -> str:
    v = str(v or "").lower()
    return v if v in ("yes", "limited", "no") else "limited"


async def drill(
    category: str,
    subreddits: list[str],
    audience: str = "",
    model: str | None = None,
    keyword_seed: str = "",
    emit=None,
) -> dict:
    """Category -> grounded products + product-friendly subreddits + keywords."""
    s = Steps(emit) if emit else None
    seed = keyword_seed or category
    phrases = list(dict.fromkeys([seed, category]))  # dedup, keep order

    # Grounding (throttled archives), the web-research agent (its own model
    # call, tool-calling), and keywords (separate host) all in parallel.
    grounding, web, keywords = await asyncio.gather(
        reddit.ground(phrases, model_subreddits=subreddits, emit=emit),
        webresearch.research(seed, category, audience, model=model, emit=emit),
        expand_keywords(seed, limit=20),
    )
    if s:
        await s.done(f"Expanded keywords for “{seed}” → {len(keywords)} phrases")

    profiles = {p["name"]: p for p in grounding["subreddits"]}
    sub_block = "\n".join(
        f"- r/{p['name']} ({p['subscribers'] or '?'} subs, submission_type={p['submission_type'] or '?'}): "
        f"{(p['description'] or '(no description)')[:200]}"
        for p in grounding["subreddits"]
    )
    post_block = "\n".join(
        f"[r/{p['subreddit']} {p['score']}pts {p['num_comments']}c] {p['title']}"
        for p in grounding["posts"][:25]
    )
    kw_block = ", ".join(k["phrase"] for k in keywords[:20])
    web_block = "\n".join(
        f"[{f['title']}]({f['url']}) {f['snippet'][:200]}" for f in web["findings"]
    )

    user = (
        f"Category: {category}\nAudience: {audience or '(unspecified)'}\n\n"
        f"SUBREDDITS (with rules):\n{sub_block or '(none found)'}\n\n"
        f"REAL POSTS:\n{post_block or '(archives quiet/down)'}\n\n"
        f"WEB FINDINGS (supplementary evidence, not a channel to judge):\n"
        f"{web_block or '(none found)'}"
        + (f"\n{web['synthesis']}" if web["synthesis"] else "") + "\n\n"
        f"KEYWORDS: {kw_block or '(none)'}"
    )
    label = "Reasoning over the signals to find products + posting fit"
    try:
        if s:
            await s.running(label)
            data = await _agent.chat_stream(user, on_chunk=s.thought, model=model, temperature=0.4)
            await s.done(label)
        else:
            data = await _agent.chat(user, model=model, temperature=0.4)
    except Exception as e:
        log.warning("drill failed (%s)", e)
        data = {}

    # Merge the model's product-friendliness verdicts back onto the real profiles.
    verdicts = {}
    for v in data.get("subreddits", []) if isinstance(data, dict) else []:
        if isinstance(v, dict) and v.get("name"):
            verdicts[v["name"].lstrip("r/").strip()] = v
    subs_out = []
    for name, prof in profiles.items():
        v = verdicts.get(name, {})
        subs_out.append({
            **prof,
            "product_friendly": _friendly(v.get("product_friendly")),
            "reason": v.get("reason", ""),
        })
    subs_out.sort(key=lambda p: (p["subscribers"] or 0), reverse=True)

    opps = []
    for o in data.get("opportunities", []) if isinstance(data, dict) else []:
        if not isinstance(o, dict) or not o.get("product"):
            continue
        o["demand_signal"] = _clamp(o.get("demand_signal"))
        if not isinstance(o.get("evidence"), list):
            o["evidence"] = []
        o.setdefault("cj_search_seed", o["product"])
        opps.append(o)

    # The concept-level saturation shown on the board (prospect.py) is already
    # measured from real CJ listing counts; this is just the model's own
    # re-rating from what the drill turned up, free as part of the same call.
    saturation = _clamp(data.get("saturation")) if isinstance(data, dict) else 50
    saturation_reasoning = data.get("saturation_reasoning", "") if isinstance(data, dict) else ""

    return {
        "category": category,
        "audience": audience,
        "reddit_source": grounding["source"],  # pullpush+arctic | arctic-only | model-only
        "web_source": web["source"],  # searxng | unavailable
        "saturation": saturation,
        "saturation_reasoning": saturation_reasoning,
        "subreddits": subs_out,
        "opportunities": opps,
        "keywords": keywords,
        "posts_sampled": grounding["posts"][:25],
        "web_findings": web["findings"],
    }
