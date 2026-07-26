"""Storefront generation -- turn a niche + its sourced products into an actual
store: branding (tagline, hero, accent colour) and a benefit-led sales pitch per
product. The customer-facing page (api/render.py) renders from what this writes.

One workhorse LLM call, schema-constrained so the copy is always valid JSON. The
per-product pitch is keyed by the real Product id so callers can write it back.
"""
import logging

from ..llm import get_llm, parse_json
from ..progress import Steps

log = logging.getLogger(__name__)

_SYS = """You are a direct-to-consumer brand copywriter. Given a niche store and
its products, write tight, specific, benefit-led copy aimed at THIS audience --
speak their language, not generic marketing filler.

Output JSON only:
{
  "tagline": "the store's hook, <= 8 words",
  "hero": "1-2 sentences: what the store is and why this audience should care",
  "accent": "#RRGGBB hex colour that fits the vibe",
  "products": [
    {"id": <the product's id, unchanged>, "pitch": "1-2 sentence sales pitch, benefit-led"}
  ]
}
Return a pitch for every product id given. Keep it real -- no hype, no emojis."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "tagline": {"type": "string"},
        "hero": {"type": "string"},
        "accent": {"type": "string"},
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "pitch": {"type": "string"},
                },
                "required": ["id", "pitch"],
            },
        },
    },
    "required": ["tagline", "hero", "accent", "products"],
}


def _hex(v) -> str:
    s = str(v or "").strip()
    if s and not s.startswith("#"):
        s = "#" + s
    # accept #RGB or #RRGGBB; otherwise fall back to the default mint accent
    if len(s) in (4, 7) and all(c in "0123456789abcdefABCDEF" for c in s[1:]):
        return s
    return "#6ee7b7"


async def generate_store(store: dict, products: list[dict], model: str | None = None,
                         emit=None) -> dict:
    """Return {tagline, hero, accent, pitches: {product_id: pitch}} for a store.

    `products` is [{id, title, price}]. Fail-soft: on error, returns a plain
    fallback built from the store's own fields so generation never hard-blocks."""
    llm = get_llm()
    s = Steps(emit) if emit else None
    lines = "\n".join(
        f'- id={p["id"]}: {p["title"]}' + (f' (~${p["price"]})' if p.get("price") else "")
        for p in products
    )
    user = (
        f"Store: {store.get('name','')}\n"
        f"Category: {store.get('category','')}\n"
        f"Audience: {store.get('audience','')}\n"
        f"Angle: {store.get('description','')}\n\n"
        f"Products:\n{lines or '(none yet)'}"
    )
    messages = [{"role": "system", "content": _SYS}, {"role": "user", "content": user}]

    label = f"Writing store copy for “{store.get('name','')}”"
    data = {}
    try:
        if s:
            await s.running(label)
            raw = ""
            async for chunk in llm.chat_stream(messages, model=model, temperature=0.7, fmt=_SCHEMA):
                raw += chunk
                await s.thought(chunk)
            data = parse_json(raw)
            await s.done(label)
        else:
            data = parse_json(await llm.chat(messages, model=model, temperature=0.7, fmt=_SCHEMA))
    except Exception as e:
        log.warning("store generation failed (%s)", e)
        if s:
            await s.done(f"{label} — failed ({e}); using a plain fallback")

    if not isinstance(data, dict):
        data = {}
    ids = {p["id"] for p in products}
    pitches = {}
    for p in data.get("products", []) if isinstance(data.get("products"), list) else []:
        if isinstance(p, dict) and p.get("id") in ids and p.get("pitch"):
            pitches[p["id"]] = p["pitch"].strip()

    return {
        "tagline": (data.get("tagline") or store.get("category") or store.get("name") or "").strip(),
        "hero": (data.get("hero") or store.get("description") or "").strip(),
        "accent": _hex(data.get("accent")),
        "pitches": pitches,
    }
