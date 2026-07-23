"""Stage 1 -- the category leaderboard.

Hit a button (optionally with a broad theme) and the model brainstorms concrete
product categories, rating each for saturation and ranking the LEAST saturated
first. This is fast and organic: one model call, no keyword expansion, no network
-- just the model's judgment of where the crowded-vs-open space is. Grounding in
real Reddit evidence happens later, on drill-down (see [drilldown.py]).

Each category carries the subreddits to dig into next, so stage 2 knows where to
look without asking the model again.
"""
import logging

from ..llm import get_llm

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


async def find_categories(theme: str = "", model: str | None = None, n: int = 12) -> dict:
    """Return {theme, categories:[...]} ranked least-saturated first."""
    llm = get_llm()
    scope = f"Focus on this space: {theme}." if theme.strip() else (
        "No theme given -- range broadly across consumer product categories."
    )
    user = f"{scope}\nReturn {n} categories."

    try:
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
        cats.append(c)
    cats.sort(key=lambda c: c["saturation"])  # least saturated first
    return {"theme": theme, "model": model or llm.default_model, "categories": cats}
