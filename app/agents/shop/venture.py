"""The venture: one store project moving down an approval-gated stage ladder.

Nothing routes downstream on the model's say-so -- every stage generates and
then WAITS. The user approves (`approve [notes]`), regenerates with notes
(`revise <notes>`), or picks among candidates (`pick <n>`).
The whole venture lives in one db document (collection "ventures", key
"active"), so approvals survive restarts and the chat can resume anywhere.

Stage ladder (STAGES): niche -> brand -> catalog -> assembly -> marketing.
Everything is live except brand (still a stub passing through with a
placeholder). assembly writes the site's supporting pages; marketing writes
per-product social plans -- the public site itself is BUILT LOCALLY from
/store/export (site/build.py) through the single template (shop/render.py)
and deployed to S3/CloudFront, and the product videos are rendered locally
by ffmpeg (site/media.py): this box only generates content.

The catalog stage is the bulk-volume node (free local inference): a small
LangGraph -- plan (one LLM call proposes the product set) -> write (one LLM
call per product for full listing copy + image/mockup prompts). Everything
the model returns is normalized here before it is stored; SKUs, slugs and
prices are minted in code.
"""
import hashlib
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable, TypedDict

from langgraph.graph import END, StateGraph

from ... import db
from ..base import load_prompt
from . import platforms, stripe_client

LlmJson = Callable[[str, str], Awaitable[dict]]

VENTURES, PRODUCTS, POSTS = "ventures", "products", "posts"

STAGES = (
    {"key": "niche",     "title": "Niche & product pick",  "live": True,
     "gate": "pick <n> to choose a candidate"},
    {"key": "brand",     "title": "Brand identity",        "live": False,
     "gate": "approve, or revise <notes>"},
    {"key": "catalog",   "title": "Catalog generation",    "live": True,
     "gate": "approve the batch, or revise <notes>"},
    {"key": "assembly",  "title": "Store assembly",        "live": True,
     "gate": "approve, or revise <notes>"},
    {"key": "marketing", "title": "Marketing engine",      "live": True,
     "gate": "approve, or revise <notes>"},
)
STAGE_KEYS = tuple(s["key"] for s in STAGES)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(text: str, max_len: int = 48) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "item"


def sku_for(title: str) -> str:
    return f"{slug(title, 32)}-{hashlib.sha1(title.encode()).hexdigest()[:6]}"


# -- venture record -----------------------------------------------------------

async def get() -> dict | None:
    v = await db.find(VENTURES, where={"key": "active"}, limit=1)
    return v[0] if v else None


async def save(v: dict) -> None:
    await db.replace(VENTURES, "active", v)


def new(seed: str) -> dict:
    return {"key": "active", "seed": seed, "created_at": _now(),
            "stages": {k: {"status": "todo"} for k in STAGE_KEYS}}


def current_stage(v: dict) -> dict:
    """The first stage that isn't approved yet -- where the venture stands."""
    for s in STAGES:
        if v["stages"][s["key"]]["status"] != "approved":
            return s
    return STAGES[-1]


def stage_brief(v: dict) -> list[dict]:
    return [{"stage": s["key"], "title": s["title"],
             "status": v["stages"][s["key"]]["status"],
             "live": s["live"]} for s in STAGES]


# -- stage generators ----------------------------------------------------------
# Each returns the stage output dict; the caller stores it as status=pending.

async def gen_niche(v: dict, llm_json: LlmJson, notes: str = "") -> dict:
    user = f"Seed topic: {v['seed']}"
    if notes:
        user += f"\nDirection notes from the owner (follow these): {notes}"
    out = await llm_json(load_prompt("shop_niche"), user)
    candidates = []
    for c in (out.get("candidates") or [])[:5]:
        name = str(c.get("niche") or "").strip()
        if not name:
            continue
        candidates.append({
            "niche": name,
            "product": str(c.get("product") or ""),
            "angle": str(c.get("angle") or ""),
            "audience": str(c.get("audience") or ""),
            "why_now": str(c.get("why_now") or ""),
            "kind": c.get("kind") if c.get("kind") in ("digital", "pod") else "digital",
            "score": _int(c.get("score"), 0, 100),
        })
    if not candidates:
        return {"error": "the model returned no usable candidates"}
    return {"candidates": candidates}


async def gen_brand(v: dict, llm_json: LlmJson, notes: str = "") -> dict:
    """STUB -- returns the planned shape plus code-derived placeholders so
    downstream stages (catalog voice, the storefront brand) have something
    to work with."""
    picked = v["stages"]["niche"].get("picked") or {}
    name = (picked.get("niche") or v["seed"]).title()
    return {
        "stub": True,
        "planned": {"name": "store name options", "domains": "domain options",
                    "positioning": "voice + positioning statement",
                    "colors": "palette + logo direction", "tagline": "tagline"},
        "placeholder": {"name": name,
                        "tagline": picked.get("angle") or "Made with care (and AI).",
                        "accent": "#2563eb"},
        "note": "brand stage not built yet -- approve to continue with the "
                "placeholder, or revise later once it's live",
    }


class CatalogState(TypedDict, total=False):
    concepts: list
    entries: list


async def gen_catalog(v: dict, llm_json: LlmJson, notes: str = "") -> dict:
    """The bulk node, as a LangGraph: plan -> write (one LLM call per
    product). Entries are stored to the products collection as drafts."""
    picked = v["stages"]["niche"].get("picked") or {}
    brand = brand_of(v)

    async def plan(state: CatalogState) -> dict:
        user = ("NICHE:\n" + _brief(picked) +
                f"\nBRAND VOICE: {brand.get('tagline', '')}")
        if notes:
            user += f"\nOwner notes (follow these): {notes}"
        out = await llm_json(load_prompt("shop_catalog_plan"), user)
        concepts = [{"concept": str(c.get("concept") or ""),
                     "kind": c.get("kind") if c.get("kind") in ("digital", "pod")
                             else picked.get("kind", "digital")}
                    for c in (out.get("products") or []) if c.get("concept")]
        return {"concepts": concepts[:4]}

    async def write(state: CatalogState) -> dict:
        entries = []
        for c in state.get("concepts", []):
            out = await llm_json(load_prompt("shop_catalog"),
                                 "PRODUCT CONCEPT:\n" + c["concept"] +
                                 f"\nkind: {c['kind']}\nNICHE:\n" + _brief(picked))
            entry = _normalize_entry(out, c["kind"], picked.get("niche", ""))
            if entry:
                await db.replace(PRODUCTS, entry["sku"], entry)
                entries.append(entry)
        return {"entries": entries}

    g = StateGraph(CatalogState)
    g.add_node("plan", plan)
    g.add_node("write", write)
    g.set_entry_point("plan")
    g.add_edge("plan", "write")
    g.add_edge("write", END)
    result = await g.compile().ainvoke({})
    entries = result.get("entries", [])
    if not entries:
        return {"error": "no catalog entries came out usable"}
    return {"skus": [e["sku"] for e in entries],
            "entries": [{k: e[k] for k in ("sku", "title", "kind", "price_usd")}
                        for e in entries]}


async def gen_assembly(v: dict, llm_json: LlmJson, notes: str = "") -> dict:
    """LLM writes the supporting pages (about/FAQ/policies) for THIS store;
    they ship inside /store/export and the static builder renders them.
    Platform payloads (Shopify/Woo CSV) remain planned."""
    picked = v["stages"]["niche"].get("picked") or {}
    brand = brand_of(v)
    catalog = await db.find(PRODUCTS, order_by="created_at", desc=True, limit=10)
    user = (f"BRAND: {brand.get('name')} -- {brand.get('tagline')}\n"
            "NICHE:\n" + _brief(picked) + "\nCATALOG:\n"
            + "\n".join(f"- {p['title']} ({p['kind']}, ${p['price_usd']})"
                        for p in catalog))
    if notes:
        user += f"\nOwner notes (follow these): {notes}"
    out = await llm_json(load_prompt("shop_pages"), user)
    pages = []
    for p in (out.get("pages") or [])[:8]:
        body = str(p.get("body_markdown") or "").strip()
        if not body:
            continue
        pages.append({"slug": slug(str(p.get("slug") or p.get("title") or "page")),
                      "title": str(p.get("title") or "Page")[:60],
                      "body_markdown": body})
    if not pages:
        return {"error": "the model returned no usable pages"}
    return {"pages": pages,
            "planned": {"payloads": ["shopify products CSV",
                                     "woocommerce products CSV"]},
            "note": "pages ship via /store/export -> apps/storefront/build.py"}


async def gen_marketing(v: dict, llm_json: LlmJson, notes: str = "") -> dict:
    """One social plan per catalog product (hook/caption/hashtags/overlays/
    script) plus a code-built posting calendar. The videos themselves are
    rendered locally by apps/storefront/media.py (ffmpeg, no AI)."""
    brand = brand_of(v)
    catalog = await db.find(PRODUCTS, order_by="created_at", desc=True, limit=6)
    if not catalog:
        return {"error": "no catalog products to market -- approve the "
                         "catalog stage first"}
    plans = []
    for p in catalog:
        user = (f"BRAND: {brand.get('name')} -- {brand.get('tagline')}\n"
                f"PRODUCT:\ntitle: {p['title']}\nsubtitle: {p.get('subtitle')}\n"
                f"kind: {p.get('kind')}\nprice: ${p.get('price_usd')}\n"
                f"bullets: {'; '.join(p.get('bullets', []))}")
        if notes:
            user += f"\nOwner notes (follow these): {notes}"
        out = await llm_json(load_prompt("shop_marketing"), user)
        if not str(out.get("hook") or "").strip():
            continue
        plans.append({
            "sku": p["sku"], "title": p["title"],
            "hook": str(out["hook"])[:80],
            "caption": str(out.get("caption") or "")[:400],
            "hashtags": [slug(str(h), 30) for h in (out.get("hashtags") or [])][:8],
            "overlay_texts": [str(t)[:60] for t in (out.get("overlay_texts") or [])][:4],
            "script": [str(s)[:120] for s in (out.get("script") or [])][:4],
            "ad_angle": str(out.get("ad_angle") or "")[:120],
        })
    if not plans:
        return {"error": "no usable social plans came back"}
    # The calendar is arithmetic, not judgment: rotate products, alternate
    # platforms, one post per weekday.
    platforms_cycle = ("tiktok", "reels")
    calendar = [{"day": day + 1,
                 "sku": plans[day % len(plans)]["sku"],
                 "platform": platforms_cycle[day % 2],
                 "hook": plans[day % len(plans)]["hook"]}
                for day in range(10)]
    return {"plans": plans, "calendar": calendar,
            "note": "render videos locally: python apps/storefront/media.py "
                    "--plan (uses /store/export)"}


GENERATORS = {"niche": gen_niche, "brand": gen_brand,
              "catalog": gen_catalog, "assembly": gen_assembly,
              "marketing": gen_marketing}


# -- venture-wide helpers -------------------------------------------------------

def brand_of(v: dict) -> dict:
    """The working brand: the real brand stage (once built) > the brand
    stub's placeholder > defaults."""
    brand = v["stages"]["brand"].get("output") or {}
    if brand.get("brand"):
        return brand["brand"]
    return brand.get("placeholder") or \
        {"name": "The Shop", "tagline": "", "accent": "#2563eb"}


def reset_downstream(v: dict, of_key: str) -> None:
    """A re-pick upstream invalidates everything after it -- back to todo
    (stage outputs are regenerated for the new direction on `next`)."""
    past = False
    for k in STAGE_KEYS:
        if past:
            v["stages"][k] = {"status": "todo"}
        if k == of_key:
            past = True


# -- product utilities (code-only or single-call; used by chat commands) --------

async def write_post(product: dict, llm_json: LlmJson) -> dict:
    """One blog post for a product -- stored + served at /blog/<slug>."""
    out = await llm_json(load_prompt("shop_blog"),
                         "PRODUCT:\n" + f"title: {product.get('title')}\n"
                         f"subtitle: {product.get('subtitle')}\n"
                         f"description: {product.get('description')}\n"
                         "buy link: " + (product.get("payment_url")
                                         or platforms.storefront_url(f"/shop/{product['sku']}")))
    body = str(out.get("body_markdown") or "").strip()
    if not body:
        return {"error": "the model returned no post body"}
    post_slug = slug(str(out.get("slug_hint") or out.get("title") or product["title"]))
    post = {"slug": post_slug,
            "title": str(out.get("title") or product["title"]),
            "excerpt": str(out.get("excerpt") or "")[:300],
            "body_markdown": body,
            "tags": [slug(str(t), 24) for t in (out.get("tags") or [])][:8],
            "sku": product["sku"],
            "url": platforms.storefront_url(f"/blog/{post_slug}"),
            "published_at": _now()}
    await db.replace(POSTS, post_slug, post)
    product["post_slug"] = post_slug
    await db.replace(PRODUCTS, product["sku"], product)
    return post


# -- product utilities (code-only; used by publish/pay chat commands) ----------

async def publish_product(product: dict) -> list[dict]:
    results = await platforms.publish_all(product)
    product["publish"] = results
    if any(r.get("ok") for r in results):
        product["status"] = "published"
    await db.replace(PRODUCTS, product["sku"], product)
    return results


async def payment_link(product: dict) -> dict:
    pay = await stripe_client.product_payment_link(
        product["title"], product["price_usd"], product["sku"])
    if pay.get("payment_url"):
        product["payment_url"] = pay["payment_url"]
    product["payment"] = pay
    await db.replace(PRODUCTS, product["sku"], product)
    return pay


# -- normalization ---------------------------------------------------------------

def _int(val, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(val)))
    except (TypeError, ValueError):
        return lo


def _price(val) -> float:
    try:
        return round(max(1.0, min(500.0, float(val))), 2)
    except (TypeError, ValueError):
        return 9.0


def _normalize_entry(out: dict, kind: str, niche: str) -> dict | None:
    title = str(out.get("title") or "").strip()
    if not title:
        return None
    return {
        "sku": sku_for(title),
        "title": title,
        "subtitle": str(out.get("subtitle") or ""),
        "description": str(out.get("description") or ""),
        "bullets": [str(b) for b in (out.get("bullets") or [])][:6],
        "backend_keywords": [str(k) for k in (out.get("backend_keywords") or [])][:15],
        "tags": [slug(str(t), 24) for t in (out.get("tags") or [])][:10],
        "image_prompts": [str(p) for p in (out.get("image_prompts") or [])][:4],
        "kind": out.get("kind") if out.get("kind") in ("digital", "pod") else kind,
        "price_usd": _price(out.get("price_usd")),
        "asset_spec": str(out.get("asset_spec") or ""),
        "niche": niche, "status": "draft", "created_at": _now(),
    }


def _brief(c: dict) -> str:
    return (f"niche: {c.get('niche')}\nwinning product: {c.get('product')}\n"
            f"angle: {c.get('angle')}\naudience: {c.get('audience')}\n"
            f"kind: {c.get('kind', 'digital')}")
