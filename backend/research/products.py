"""Grounding a product idea in a REAL CJdropshipping product.

The core primitive of the "CJ at the core" reframe: given a product idea (a seed
phrase + its audience), find the actual CJ product that genuinely IS that thing --
or return None so the caller drops it instead of inventing something. Used both to
ground the stage-1 leaderboard (categories.py) and to resolve storefront products.

Why a model judges: CJ's search ORs the query words and doesn't rank by relevance,
so a token match ("kit" + "plant") happily returns a kids' craft kit for "air
plant terrarium kit". The judge reads the real product names and picks the one
that's genuinely the product, or rejects them all. Two CJ calls (list + detail)
plus one small judgment, reusing saturation.py's token + throttle.
"""
import logging
import re

import httpx

from ..agent import Agent
from . import catalog
from .saturation import (
    _cj_query_throttle,
    _cj_token_value,
    _content_tokens,
    _matches,
    _tokens,
)

log = logging.getLogger(__name__)

_LIST_URL = "https://developers.cjdropshipping.com/api2.0/v1/product/list"

# Prompt + schema: agents/product-judge.md. Judged on the heavy node when
# configured -- relevance judgment is exactly where the bigger model earns
# its keep (falls back to the workhorse).
_judge_agent = Agent("product-judge", heavy=True)

_JUDGE_POOL = 12  # how many CJ names to put in front of the judge


def _images(summary: dict, detail: dict) -> list[str]:
    imgs = detail.get("productImageSet") or detail.get("productImages") or []
    if isinstance(imgs, str):
        imgs = [u for u in re.split(r"[,\s]+", imgs) if u.startswith("http")]
    imgs = [u for u in imgs if isinstance(u, str) and u.startswith("http")]
    main = summary.get("productImage") or detail.get("productImage")
    if main and main not in imgs:
        imgs.insert(0, main)
    return imgs


async def _list(client: httpx.AsyncClient, token: str, seed: str, size: int = 100) -> list[dict]:
    await _cj_query_throttle.wait()
    r = await client.get(_LIST_URL, headers={"CJ-Access-Token": token},
                         params={"pageNum": 1, "pageSize": size, "productNameEn": seed})
    r.raise_for_status()
    return (r.json().get("data") or {}).get("list") or []


def _candidates(items: list[dict], seed: str, k: int = _JUDGE_POOL) -> list[dict]:
    """The CJ products to put in front of the judge: token-matched ones first
    (most likely genuine), then fill with the rest, deduped by pid."""
    want = _content_tokens(seed)
    def name(it): return it.get("productNameEn") or it.get("productName") or ""
    matched = [it for it in items if _matches(set(_tokens(name(it))), want)]
    rest = [it for it in items if it not in matched]
    picked, seen = [], set()
    for it in matched + rest:
        pid = it.get("pid")
        if pid and pid not in seen:
            seen.add(pid)
            picked.append(it)
        if len(picked) >= k:
            break
    return picked


async def _judge(idea: str, audience: str, names: list[str], model: str | None) -> int:
    """Which CJ name genuinely is the idea? Returns index, or -1 for none."""
    listing = "\n".join(f"{i}. {n}" for i, n in enumerate(names))
    user = (f"PRODUCT IDEA: {idea}\nAUDIENCE: {audience or '(unspecified)'}\n\n"
            f"CJ PRODUCTS:\n{listing}")
    try:
        data = await _judge_agent.chat(user, model=model, temperature=0)
        idx = int(data.get("index", -1)) if isinstance(data, dict) else -1
        return idx if 0 <= idx < len(names) else -1
    except Exception as e:
        log.warning("product judge failed for %r (%s)", idea, e)
        return -1


async def ground_product(seed: str, idea: str = "", audience: str = "",
                         model: str | None = None) -> dict | None:
    """Resolve a seed to a REAL, model-verified CJ product, or None if CJ has
    nothing genuine (the caller then drops it -- no invented products)."""
    seed = (seed or "").strip()
    if not seed:
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await _cj_token_value(client)
            if not token:
                return None
            cands = _candidates(await _list(client, token, seed), seed)
            if not cands:
                return None
            names = [c.get("productNameEn") or c.get("productName") or "" for c in cands]
            idx = await _judge(idea or seed, audience, names, model)
            if idx < 0:  # nothing genuinely matches -> not real, drop it
                return None
            chosen = cands[idx]
            detail = await catalog.detail(chosen["pid"])
            video = detail.get("productVideo") or detail.get("video") or ""
            return {
                "cj_product_id": chosen["pid"],
                "title": names[idx],
                "price": catalog.price_of(detail.get("sellPrice") or chosen.get("sellPrice")),
                "images": _images(chosen, detail),
                "videos": [video] if video else [],
                "seed": seed,
            }
    except Exception as e:
        log.warning("ground_product failed for %r (%s)", seed, e)
        return None


async def hydrate(pid: str, fallback_image: str = "") -> dict | None:
    """Full data for a product we ALREADY have the CJ id for -- the stage-1 board
    now hands over real pids, so there's nothing to search or judge: just fetch
    the gallery, video and current price. Returns None if CJ has nothing."""
    detail = await catalog.detail(pid)
    if not detail:
        return None
    video = detail.get("productVideo") or detail.get("video") or ""
    images = _images({"productImage": fallback_image} if fallback_image else {}, detail)
    return {
        "cj_product_id": pid,
        "title": (detail.get("productNameEn") or detail.get("productName") or "").strip(),
        "price": catalog.price_of(detail.get("sellPrice")),
        "images": images,
        "videos": [video] if video else [],
        "seed": "",
    }
