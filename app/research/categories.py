"""Stage 1 -- the category leaderboard.

Hit a button (optionally with a broad theme) and the model brainstorms concrete
product categories, rating each for saturation and ranking the LEAST saturated
first. Fast and organic: one model call, no keyword lists, no network. Grounding
in real Reddit evidence + per-category keywords happens on drill-down.

Pass an `emit` callback (see app/progress.py) to stream the work -- named steps
plus the model's live thinking -- so the UI can show it happening.
"""
import logging

from ..config import get_settings
from ..llm import get_heavy_llm, parse_json
from ..progress import Steps
from . import saturation as sat

log = logging.getLogger(__name__)

_SYS = """You are a product-opportunity scout for a dropshipping/print-on-demand
operator sourcing from CJdropshipping. Brainstorm concrete PRODUCT CATEGORIES
worth building a storefront around, and rank them by how UNSATURATED they are --
least crowded first, because open lanes are where a new store can win.

Rate saturation 0-100 (0 = wide open, 100 = brutally crowded/commoditized) using
your knowledge of the market:
- HIGH saturation: generic mass-market goods, categories dominated by Amazon/big
  brands, anything a thousand dropshippers already run (phone cases, basic tees).
- LOW saturation: specific enthusiast sub-cultures, emerging trends, oddly
  particular use-cases, communities underserved by generic sellers.
Favor categories with a real, identifiable audience AND breathing room.

Output JSON only:
{
  "categories": [
    {
      "name": "the product category (specific, not 'home decor')",
      "audience": "who buys it -- a real, describable group",
      "saturation": 0-100,
      "saturation_reasoning": "one honest sentence on why that number",
      "angle": "the wedge -- why a new store can win here right now",
      "keyword_seed": "a SHORT 1-3 word shopping term for autocomplete (e.g. 'standing desk', not the long category name)",
      "subreddits": ["3-5 REAL subreddit names (no r/ prefix) where this audience actually gathers"]
    }
  ]
}
Return the requested count, least saturated first."""


# Schema-constrained output -> valid JSON by construction (no empty/broken results).
_SCHEMA = {
    "type": "object",
    "properties": {
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "audience": {"type": "string"},
                    "saturation": {"type": "integer"},
                    "saturation_reasoning": {"type": "string"},
                    "angle": {"type": "string"},
                    "keyword_seed": {"type": "string"},
                    "subreddits": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "audience", "saturation", "angle",
                             "keyword_seed", "subreddits"],
            },
        }
    },
    "required": ["categories"],
}


def _clamp(v) -> int:
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return 50


async def find_categories(theme: str = "", model: str | None = None, n: int = 12, emit=None) -> dict:
    """Return {theme, categories:[...]} ranked least-saturated first. Streams via `emit`.

    Runs on the HEAVY node (bigger model) when one is configured -- category and
    subreddit brainstorming is where model knowledge matters most. Falls back to
    the workhorse otherwise. Drills stay on the fast node.
    """
    llm = get_heavy_llm()
    # When a heavy node is configured, its model does stage 1 (ignore the drill
    # model picker here); otherwise honor the picked/default model.
    if get_settings().ollama_heavy_base_url:
        model = None
    s = Steps(emit) if emit else None
    scope = f"Focus on this space: {theme}." if theme.strip() else (
        "No theme given -- range broadly across consumer product categories."
    )
    user = f"{scope}\nReturn {n} categories."
    messages = [{"role": "system", "content": _SYS}, {"role": "user", "content": user}]

    label = f"Brainstorming {n} product categories"
    try:
        if s:
            await s.done(f"Connected to edge-ai ({model or llm.default_model})")
            await s.running(label)
            raw = ""
            async for chunk in llm.chat_stream(messages, model=model, temperature=0.6, fmt=_SCHEMA):
                raw += chunk
                await s.thought(chunk)
            data = parse_json(raw)
            await s.done(label)
        else:
            data = await llm.chat([{"role": "system", "content": _SYS},
                                   {"role": "user", "content": user}],
                                  model=model, temperature=0.6, fmt=_SCHEMA)
            data = parse_json(data)
    except Exception as e:
        log.warning("category scout failed (%s)", e)
        data = {"categories": []}

    cats = []
    for c in data.get("categories", []) if isinstance(data, dict) else []:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        c["saturation"] = _clamp(c.get("saturation"))
        if not isinstance(c.get("subreddits"), list):
            c["subreddits"] = []
        # Short seed for keyword autocomplete; long category names return nothing.
        if not c.get("keyword_seed"):
            c["keyword_seed"] = c["name"]
        c["saturation_method"] = "estimated"
        c["saturation_supply"] = {}
        cats.append(c)

    # Measure real supply per category (concurrently) so the leaderboard ranks on
    # data, not the model's guess. Degrades per-category to the estimate.
    settings = get_settings()
    if cats and (settings.has_cj or settings.has_ebay):
        if s:
            await s.running(f"Measuring supply for {len(cats)} categories (real saturation)")
        results = await sat.measure_batch([c["keyword_seed"] for c in cats])
        measured = 0
        for c, r in zip(cats, results):
            if r["measured"]:
                c["saturation"] = r["saturation"]
                c["saturation_method"] = "measured"
                c["saturation_supply"] = r["supply"]
                measured += 1
        if s:
            await s.done(f"Measured saturation for {measured}/{len(cats)} categories")

    cats.sort(key=lambda c: c["saturation"])  # least saturated first
    if s:
        await s.done(f"Ranked {len(cats)} categories by saturation")
    return {"theme": theme, "model": model or llm.default_model, "categories": cats}
