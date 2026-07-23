"""Stage 2 -- drill a category into real Reddit signal, then surface products +
the subreddits you could actually post them in.

Grounding chains two free archives (see subreddits.py): PullPush finds which
subreddits discuss the niche + real engagement; Arctic Shift profiles those subs
(subscribers + rules). The model then, from that evidence:
  - classifies each subreddit's product-posting friendliness (from its rules +
    submission type + the model's own knowledge),
  - names concrete PRODUCTS to source, each with a `cj_search_seed` for CJ,
  - re-rates saturation.

Plus per-category long-tail keywords. Everything degrades: dead archives -> the
model reasons from the category + its suggested subreddits, and the UI says so.
Pass `emit` to stream the work.
"""
import asyncio
import logging

from ..llm import get_llm, parse_json
from ..progress import Steps
from . import subreddits as sr
from .keywords import expand_keywords

log = logging.getLogger(__name__)

_SYS = """You are a product researcher for a dropshipping operator sourcing from
CJdropshipping. You are given a product category, the SUBREDDITS its buyers use
(with subscriber counts, submission type, and each sub's own description/rules),
REAL post titles from those communities, and long-tail keywords.

Do three things:
1. For EACH subreddit, judge whether the operator could post their own products
   there -- "yes", "limited" (only via specific threads/flairs/days), or "no"
   (rules ban self-promo). Base it on the sub's rules/description + submission
   type + your knowledge of the community. One-line reason each.
2. Name concrete PRODUCTS to source. For each, a `cj_search_seed`: the short
   phrase to search on CJdropshipping (e.g. "linen cable organizer", not "cozy
   vibes"). Ground picks in the posts/keywords.
3. Re-rate the category's saturation 0-100 (0 = wide open, 100 = crowded).

Output JSON only:
{
  "saturation": 0-100,
  "saturation_reasoning": "one sentence",
  "subreddits": [
    {"name": "exact name given", "product_friendly": "yes|limited|no", "reason": "why"}
  ],
  "opportunities": [
    {"product": "...", "rationale": "...", "evidence": ["thread theme/keyword"],
     "cj_search_seed": "...", "demand_signal": 0-100}
  ]
}
Return 3-6 opportunities, strongest first."""


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
    llm = get_llm()
    s = Steps(emit) if emit else None
    seed = keyword_seed or category
    phrases = list(dict.fromkeys([seed, category]))  # dedup, keep order

    # Grounding (throttled archives) + keywords (separate host) in parallel.
    grounding, keywords = await asyncio.gather(
        sr.ground(phrases, model_subreddits=subreddits, emit=emit),
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

    user = (
        f"Category: {category}\nAudience: {audience or '(unspecified)'}\n\n"
        f"SUBREDDITS (with rules):\n{sub_block or '(none found)'}\n\n"
        f"REAL POSTS:\n{post_block or '(archives quiet/down)'}\n\n"
        f"KEYWORDS: {kw_block or '(none)'}"
    )
    messages = [{"role": "system", "content": _SYS}, {"role": "user", "content": user}]

    label = "Reasoning over the signals to find products + posting fit"
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

    return {
        "category": category,
        "audience": audience,
        "reddit_source": grounding["source"],  # pullpush+arctic | arctic-only | model-only
        "saturation": _clamp(data.get("saturation")) if isinstance(data, dict) else 50,
        "saturation_reasoning": data.get("saturation_reasoning", "") if isinstance(data, dict) else "",
        "subreddits": subs_out,
        "opportunities": opps,
        "keywords": keywords,
        "posts_sampled": grounding["posts"][:25],
    }
