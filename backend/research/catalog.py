"""CJdropshipping's catalog -- the ground truth stage 1 starts from.

The old flow asked a model to invent niches and then went looking for products to
back them, so most of the work was spent discovering that nothing sourceable
existed. This module inverts that: everything begins with real CJ rows.

Two primitives, both straight off CJ's API:

  leaves()          the real category tree (14 departments -> 85 -> 540 leaves).
                    Anything picked from here is sourceable by construction.
  products(leaf)    real products in a leaf category -- pid, title, price, image,
                    and `listedNum`: how many CJ sellers already list THAT EXACT
                    product. That last one is the saturation signal the old flow
                    was trying to approximate with keyword phrase-matching, only
                    it's exact, per-product, and free (it ships with the row).

Observed spread on `listedNum` (100-product samples): Decor Paintings median 4,
Evening Dresses median 105, single products 0 -> 734. Real competition, not a guess.

The tree is cached on disk (it changes rarely, and the call is rate-limited);
`explored`/`remember_explored` persist which leaves recent runs already picked so
"Surprise me" rotates through the catalog instead of re-hunting the same aisles.
"""
import asyncio
import json
import logging
import os
import random
import re
import time

import httpx

from ..config import get_settings
from .saturation import (
    _STOPWORDS,
    _cj_query_throttle,
    _cj_token_value,
    _content_tokens,
    _matches,
    _tokens,
)

log = logging.getLogger(__name__)

_BASE = "https://developers.cjdropshipping.com/api2.0/v1"
_TREE_FILE = "data/.cj_categories.json"   # mounted volume -> survives restarts
_TREE_TTL = 7 * 24 * 3600                 # the tree moves slowly; refetch weekly
_EXPLORED_FILE = "data/.explored_categories.json"
_EXPLORED_KEEP = 150                      # leaves to remember before recycling
PAGE = 100                                # products per CJ list call (1 request)


def price_of(raw) -> float | None:
    """CJ sell prices come as '1.50', 'US$1.50', or a '1.50 -- 3.20' range."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    nums = re.findall(r"\d+\.?\d*", str(raw))
    return float(nums[0]) if nums else None


async def _get(client: httpx.AsyncClient, token: str, path: str, params: dict) -> dict:
    """One throttled CJ GET, with a single retry on their 429."""
    for attempt in range(2):
        await _cj_query_throttle.wait()
        r = await client.get(f"{_BASE}{path}", headers={"CJ-Access-Token": token},
                             params=params)
        if r.status_code == 429 and attempt == 0:
            await asyncio.sleep(2.5)
            continue
        r.raise_for_status()
        return r.json().get("data") or {}
    return {}


# ------------------------------- the tree --------------------------------

def _flatten(tree: list) -> list[dict]:
    """CJ's 3-level tree -> flat leaf list, each carrying its full path."""
    out = []
    for first in tree if isinstance(tree, list) else []:
        l1 = first.get("categoryFirstName") or ""
        for second in first.get("categoryFirstList") or []:
            l2 = second.get("categorySecondName") or ""
            for leaf in second.get("categorySecondList") or []:
                cid, name = leaf.get("categoryId"), leaf.get("categoryName") or ""
                if cid and name:
                    out.append({"id": cid, "name": name, "l1": l1, "l2": l2,
                                "path": f"{l1} > {l2} > {name}"})
    return out


def _read_cache(path: str, ttl: float) -> list | None:
    try:
        st = os.stat(path)
        if time.time() - st.st_mtime > ttl:
            return None
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(path: str, data) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception as e:
        log.debug("could not cache %s (%s)", path, e)


async def leaves() -> list[dict]:
    """Every leaf category CJ actually sells into. [] when CJ isn't configured."""
    cached = _read_cache(_TREE_FILE, _TREE_TTL)
    if cached:
        return cached
    if not get_settings().has_cj:
        return []
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            token = await _cj_token_value(client)
            if not token:
                return []
            tree = await _get(client, token, "/product/getCategory", {})
    except Exception as e:
        log.warning("CJ category tree failed (%s)", e)
        return []
    flat = _flatten(tree if isinstance(tree, list) else [])
    if flat:
        _write_cache(_TREE_FILE, flat)
    return flat


# --------------------------- rotation memory ------------------------------

def explored() -> set[str]:
    """Leaf ids recent runs already hunted (so a fresh run picks elsewhere)."""
    return set(_read_cache(_EXPLORED_FILE, ttl=float("inf")) or [])


def remember_explored(ids: list[str]) -> None:
    seen = list(dict.fromkeys(list(explored()) + [i for i in ids if i]))
    _write_cache(_EXPLORED_FILE, seen[-_EXPLORED_KEEP:])


def search_ground(query: str) -> dict:
    """A hunting ground that is NOT a category: CJ's own keyword search.

    Plenty of real inventory lives in no aisle you can name. "ladder" has 816
    products on CJ -- telescoping ladders, step stools, work platforms -- but no
    ladder category; they're scattered across Furniture, Tools Storage, Garden
    Tools. A themed hunt has to search the catalog, not just browse it."""
    q = " ".join(str(query or "").split())
    return {"id": f"search:{q.lower()}", "name": q, "l1": "Search", "l2": "",
            "path": f"search “{q}”", "query": q}


def sample_fresh(all_leaves: list[dict], k: int) -> list[dict]:
    """k random leaves, preferring ones recent runs haven't touched. When the
    unexplored pool runs dry the memory is simply out-voted -- never empty."""
    done = explored()
    fresh = [l for l in all_leaves if l["id"] not in done]
    pool = fresh if len(fresh) >= k else all_leaves
    return random.sample(pool, min(k, len(pool)))


# ------------------------------- products ---------------------------------

def _row(p: dict, leaf: dict) -> dict:
    """One CJ list row -> the fields the prospector scores and the UI shows."""
    # Browsing an aisle, the aisle IS the category. Searching, the row's own
    # category is the honest one -- a keyword hit can come from anywhere.
    if leaf.get("query"):
        name = p.get("categoryName") or leaf["name"]
        path = " > ".join(x for x in (p.get("oneCategoryName"), p.get("twoCategoryName"),
                                      p.get("categoryName")) if x) or leaf["path"]
    else:
        name, path = leaf["name"], leaf["path"]
    return {
        "pid": p.get("pid") or "",
        "title": (p.get("productNameEn") or p.get("productName") or "").strip(),
        "price": price_of(p.get("sellPrice")),
        "image": p.get("productImage") or "",
        # How many CJ sellers already list this exact product = competition.
        "listings": int(p.get("listedNum") or p.get("listingCount") or 0),
        "category": name,
        "category_path": path,
        "category_id": leaf["id"],   # the GROUND it came from (keys demand)
        "has_video": bool(p.get("isVideo")),
        "supplier": p.get("supplierName") or "",
    }


# CJ's category filter is not always a filter. For SMALL categories their backend
# falls back to a fuzzy name search, and the substring hits are wild: "Basketball
# Shoes" (total 132) came back 42% laundry BASKETS -- real products, wrong aisle,
# and they'd inherit that aisle's demand score. Big categories are filtered
# properly and legitimately hold products whose names share no word with the
# category (Decor Paintings: easels, display shelves), so the guard fires only
# where the fallback does: a small category whose page is substantially off-topic.
_SMALL_CATEGORY = 500     # under this total, CJ may be name-searching instead
_CONTAMINATED = 0.25      # ...and it shows as this share of the page off-topic


def _on_topic(rows: list[dict], leaf: dict, total: int) -> tuple[list[dict], int]:
    """Drop rows CJ smuggled in via a fuzzy name match. Returns (kept, dropped)."""
    if not rows:
        return rows, 0
    if leaf.get("query"):
        # Search ORs the query words and doesn't rank by relevance, so a page of
        # "ladder" hits includes an inflatable tent. Here the filter is never
        # optional -- but it must stay LENIENT: a theme is not a product phrase,
        # and demanding every word ("coffee brewing") throws away every French
        # press coffee maker. Keep anything carrying a theme word; the caller
        # ranks by how many words hit, so full matches still come first.
        want = set(_content_tokens(leaf["query"]))
        keep = [r for r in rows if want & set(_tokens(r["title"]))]
        return keep, len(rows) - len(keep)
    if total > _SMALL_CATEGORY:
        return rows, 0
    want = {t for t in _tokens(leaf["path"]) if t not in _STOPWORDS and len(t) > 2}
    if not want:
        return rows, 0
    keep = [r for r in rows if want & set(_tokens(r["title"]))]
    dropped = len(rows) - len(keep)
    if dropped / len(rows) < _CONTAMINATED:
        return rows, 0  # ordinary naming variety, not a broken filter
    return keep, dropped


async def products(leaf: dict, pages: int = 1,
                   size: int = PAGE) -> tuple[list[dict], int, int]:
    """Real products in a leaf category -> (rows, CJ's total for it, dropped).

    Fail-soft: a category that errors returns ([], 0, 0) so one bad leaf can't
    sink a scan. Rows come back deduped by pid, named, and on-topic."""
    if not get_settings().has_cj:
        return [], 0, 0
    rows: list[dict] = []
    total = 0
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            token = await _cj_token_value(client)
            if not token:
                return [], 0, 0
            for page in range(1, max(1, pages) + 1):
                params = {"pageNum": page, "pageSize": size}
                # A ground is either an aisle to browse or a phrase to search.
                if leaf.get("query"):
                    params["productNameEn"] = leaf["query"]
                else:
                    params["categoryId"] = leaf["id"]
                data = await _get(client, token, "/product/list", params)
                total = int(data.get("total") or total)
                batch = data.get("list") or []
                rows += [_row(p, leaf) for p in batch]
                if len(batch) < size:
                    break  # last page
    except Exception as e:
        log.warning("CJ product list failed for %s (%s)", leaf.get("path"), e)
        return rows, total, 0
    seen, out = set(), []
    for r in rows:
        if r["pid"] and r["title"] and r["pid"] not in seen:
            seen.add(r["pid"])
            out.append(r)
    out, dropped = _on_topic(out, leaf, total)
    if dropped:
        log.info("dropped %d off-category rows from %s (CJ name-search fallback)",
                 dropped, leaf.get("path"))
    return out, total, dropped


async def detail(pid: str) -> dict:
    """Full product record for one pid (images, video, variants) -- fetched only
    for products that make it into a store, not for everything scanned."""
    if not (pid and get_settings().has_cj):
        return {}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            token = await _cj_token_value(client)
            if not token:
                return {}
            return await _get(client, token, "/product/query", {"pid": pid})
    except Exception as e:
        log.warning("CJ product detail failed for %s (%s)", pid, e)
        return {}
