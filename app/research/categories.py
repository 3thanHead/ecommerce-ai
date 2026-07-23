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
            async for chunk in llm.chat_stream(messages, model=model, temperature=0.6):
                raw += chunk
                await s.thought(chunk)
            data = parse_json(raw)
            await s.done(label)
        else:
            data = await llm.json(_SYS, user, model=model, temperature=0.6)
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
        cats.append(c)
    cats.sort(key=lambda c: c["saturation"])  # least saturated first
    if s:
        await s.done(f"Ranked {len(cats)} categories by saturation")
    return {"theme": theme, "model": model or llm.default_model, "categories": cats}
