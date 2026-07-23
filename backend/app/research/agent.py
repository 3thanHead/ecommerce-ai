"""The niche research agent -- multifactor, model-in-the-loop.

Flow (mechanics are code, judgment is the model):
  1. plan     [LLM]  prompt + audience -> subreddits, search phrases, a seed kw
  2. gather   [code] pull popular threads from Reddit (top + search) and pool
                     their engagement signals (score, comments, upvote ratio)
  3. keywords [code] Google Suggest expansion on the seed -> long-tail demand
  4. context  [code] optional keyless web search for discussion we didn't think
                     to query (degrades to nothing)
  5. judge    [LLM]  reason over threads + keywords -> niche candidates, each
                     with a demand score AND a saturation rating + reasoning

Every source degrades independently: a dead Reddit path or cold web search just
means a thinner round, never a failure. The model never sees which Reddit
backend ran. Returns plain data; persistence is the API layer's job.
"""
import asyncio
import json
import logging

from ..llm import get_llm
from .keywords import expand_keywords
from .reddit import Thread, get_reddit
from .web import web_search

log = logging.getLogger(__name__)

MAX_THREADS = 40

_PLAN_SYS = """You are a product-niche research planner for a dropshipping operator.
Given a category or free-text prompt and a target audience, decide where on Reddit
to look. Output JSON only:
{
  "audience": "one concise phrase describing who buys here",
  "subreddits": ["3-6 real subreddit names, no r/ prefix, communities this audience actually uses"],
  "phrases": ["4-8 search phrases a buyer or enthusiast would discuss"],
  "seed_keyword": "the single best 1-3 word shopping keyword for this category"
}"""

_JUDGE_SYS = """You are a product-niche analyst for a dropshipping operator. You are given:
- the operator's prompt and target audience
- popular Reddit threads (with score, comment count, upvote ratio) showing what this audience cares about
- long-tail keywords from autocomplete, with a `freq` popularity proxy

Identify concrete PRODUCT niches this operator could build a storefront around.
For each niche, rate two things on a 0-100 scale and JUSTIFY the saturation rating:
- demand: how much genuine buyer interest the signals show (engagement + keyword breadth)
- saturation: how crowded/competitive the niche looks. Reason from cues in the
  data -- generic mass-market terms and big brands imply HIGH saturation; specific,
  enthusiast, or emerging angles imply LOW saturation. Be honest that this is an
  estimate from proxies, not measured competition.

Prefer niches with high demand and lower saturation. Output JSON only:
{
  "summary": "2-3 sentence read on the opportunity landscape",
  "candidates": [
    {
      "name": "the niche",
      "audience": "who buys it",
      "rationale": "why the signals support it (cite thread themes / keywords)",
      "demand": 0-100,
      "saturation": 0-100,
      "saturation_reasoning": "why that saturation number",
      "example_products": ["3-6 specific product ideas to source on CJdropshipping"],
      "keywords": ["4-8 target keywords from the list above"]
    }
  ]
}
Return 3-6 candidates, best opportunity first."""


def _summarize_threads(threads: list[Thread]) -> str:
    """Compact the threads into a token-cheap signal block for the model."""
    lines = []
    for t in sorted(threads, key=lambda x: x.score, reverse=True)[:MAX_THREADS]:
        lines.append(
            f"[r/{t.subreddit} | score {t.score} | {t.num_comments} comments | "
            f"ratio {t.upvote_ratio:.2f}] {t.title}"
        )
    return "\n".join(lines)


async def _plan(llm, prompt: str, audience: str, model: str | None) -> dict:
    user = f"Prompt: {prompt}\nTarget audience: {audience or '(not specified)'}"
    try:
        plan = await llm.json(_PLAN_SYS, user, model=model)
    except Exception as e:
        log.warning("plan step failed (%s); using naive fallback", e)
        plan = {}
    plan.setdefault("audience", audience)
    plan.setdefault("subreddits", [])
    plan.setdefault("phrases", [prompt])
    plan.setdefault("seed_keyword", prompt)
    return plan


MIN_DIRECT_THREADS = 5  # below this, the direct path is considered blocked/thin


async def _gather_reddit(reddit, plan: dict) -> tuple[list[Thread], str]:
    """Return (threads, source_note). Tries direct Reddit; if that's thin/blocked,
    does ONE bounded web-discovery pass (capped Jina reads)."""
    tasks = []
    for sub in plan["subreddits"][:6]:
        tasks.append(reddit.top(sub, time_filter="year", limit=15))
    for phrase in plan["phrases"][:6]:
        tasks.append(reddit.search(phrase, sort="top", time_filter="year", limit=15))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    pooled: dict[str, Thread] = {}
    for res in results:
        if isinstance(res, Exception):
            continue
        for t in res:
            if t.id:
                pooled[t.id] = t  # dedup across subreddit+search overlap

    if len(pooled) >= MIN_DIRECT_THREADS:
        return list(pooled.values()), "direct"

    # Direct path blocked or thin -> one consolidated discovery pass (Jina reads
    # a few Reddit listing/search pages server-side; bounded number of reads).
    subs = plan["subreddits"][:5] or [plan["seed_keyword"]]
    for t in await reddit.discover(subs, max_pages=5):
        pooled.setdefault(t.id, t)
    return list(pooled.values()), ("discovery" if pooled else "none")


async def research(
    prompt: str,
    audience: str = "",
    model: str | None = None,
    use_web: bool = True,
) -> dict:
    """Run one research round. Returns a dict ready to persist and show."""
    llm = get_llm()
    reddit = get_reddit()

    plan = await _plan(llm, prompt, audience, model)
    log.info("research plan: subs=%s phrases=%s", plan["subreddits"], plan["phrases"])

    reddit_result, keywords, web = await asyncio.gather(
        _gather_reddit(reddit, plan),
        expand_keywords(plan["seed_keyword"], limit=40),
        web_search(f"{prompt} reddit", limit=6) if use_web else _noop_list(),
    )
    threads, reddit_source = reddit_result

    thread_block = _summarize_threads(threads)
    kw_block = "\n".join(f"{k['phrase']} (freq {k['freq']})" for k in keywords[:40])
    web_block = "\n".join(f"- {w['title']} ({w['url']})" for w in web)

    judge_user = (
        f"Operator prompt: {prompt}\n"
        f"Target audience: {plan['audience'] or '(unspecified)'}\n\n"
        f"POPULAR REDDIT THREADS ({len(threads)} pooled):\n{thread_block or '(none found)'}\n\n"
        f"LONG-TAIL KEYWORDS (autocomplete):\n{kw_block or '(none)'}\n\n"
        f"WEB DISCUSSION:\n{web_block or '(none)'}"
    )

    try:
        judged = await llm.json(_JUDGE_SYS, judge_user, model=model, temperature=0.3)
    except Exception as e:
        log.warning("judge step failed (%s)", e)
        judged = {"summary": "Model synthesis failed; raw signals only.", "candidates": []}

    return {
        "prompt": prompt,
        "audience": plan["audience"],
        "model": model or llm.default_model,
        "reddit_via_api": reddit.using_api,
        "reddit_source": reddit_source,  # direct | discovery | none
        "plan": plan,
        "summary": judged.get("summary", ""),
        "candidates": _clamp_candidates(judged.get("candidates", [])),
        "threads_sampled": [t.dict() for t in sorted(threads, key=lambda x: x.score, reverse=True)[:MAX_THREADS]],
        "keywords": keywords,
        "web": web,
    }


async def _noop_list() -> list:
    return []


def _clamp_candidates(cands: list) -> list:
    out = []
    for c in cands if isinstance(cands, list) else []:
        if not isinstance(c, dict):
            continue
        c["demand"] = _clamp(c.get("demand", 0))
        c["saturation"] = _clamp(c.get("saturation", 0))
        for key in ("example_products", "keywords"):
            if not isinstance(c.get(key), list):
                c[key] = []
        out.append(c)
    return out


def _clamp(v) -> int:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return 0
