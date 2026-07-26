"""Stage 1, CJ-first: real products in, store concepts out.

The previous engine ran backwards -- a model invented niches, then we spent the
whole scan discovering CJ couldn't back them ("0 of 8 grounded"). Nothing you
can't source is worth finding, so the catalog goes first and the model goes last:

  1. HUNTING GROUND  pick real leaf categories from CJ's tree (540 of them).
                     A theme picks the ones whose names match it; "surprise me"
                     rotates through categories recent runs haven't touched, so
                     the pick needs no model at all and can't be blocked by one.
  2. PULL            real products from those categories -- pid, title, price,
                     image, and how many CJ sellers already list each one.
  3. SCORE           saturation comes from that per-product seller count (exact,
                     free, already on the row), demand from buyer-intent
                     autocompletes for the category. opportunity = demand x
                     openness, so a product nobody competes on AND nobody wants
                     scores near zero -- an empty aisle is not an opportunity.
  4. CLUSTER         the winning REAL products get grouped into store-shaped
                     concepts (name, audience, angle, subreddits). This is the
                     one job the model is actually good at, and it can only work
                     with products that already exist. If the fleet is down we
                     fall back to CJ's own category grouping -- the board still
                     comes out, just with plainer names.

Everything the board shows is a real CJ row, so promoting a concept is a data
copy, not another search. `emit` streams the work (see backend/progress.py).
"""
import asyncio
import logging
import math
import re
import statistics

from ..llm import get_heavy_llm, parse_json
from ..progress import Steps
from . import catalog
from .keywords import demand_batch
from .saturation import _tokens

log = logging.getLogger(__name__)

# A concept is only interesting under this ceiling. Saturation here is the
# per-product seller count, so 65 ~= 45 sellers already on the same product.
DEFAULT_MAX_SATURATION = 65
# Sellers-per-product that reads as fully saturated on the log scale. Sampled CJ
# categories run median 4 (Decor Paintings) to 105 (Evening Dresses), with hot
# individual products in the 300-700s -- so 300 is "everyone already sells it".
_LISTING_CEILING = 300
_MIN_PER_STORE = 2            # a concept needs at least this many real products
_MAX_PER_STORE = 8            # ...and stops being a store past this many
_CLUSTER_POOL = 44            # winners put in front of the clustering model
_SEARCH_PAGES = 3             # pages pulled for a theme's catalog search
_THIN_SCAN = 90               # under this many real products, widen the hunt
_TITLE_CHARS = 72             # CJ titles are keyword soup; trim for the prompt

# Category names carry shop-speak that ruins an autocomplete probe.
_CATEGORY_NOISE = {"other", "others", "accessories", "supplies", "products",
                   "tools", "sets", "set", "parts", "general", "misc"}


def _saturation(listings: int) -> int:
    """0-100 from how many CJ sellers already list this exact product."""
    if listings <= 0:
        return 0
    score = math.log10(listings + 1) / math.log10(_LISTING_CEILING) * 100
    return max(0, min(100, round(score)))


# How much we trust a product that NOBODY is selling yet. Ranking on openness
# alone hands the whole board to zero-seller products, and zero is ambiguous: it
# means "uncontested" and "unproven -- possibly nobody wants this, or CJ just
# listed it" in equal measure. A handful of sellers is the sweet spot: demand is
# demonstrated, the lane is still open. So openness is discounted until a product
# has shown it can sell at all.
_PROOF = {0: 0.55, 1: 0.75, 2: 0.9}   # sellers -> confidence; 3+ is fully proven


def _opportunity(demand: int | None, saturation: int, listings: int = 3) -> int:
    """demand x openness x proof-of-sale.

    Unknown demand (Google Suggest went quiet) falls back to openness alone, so a
    Suggest outage degrades the ranking instead of zeroing it."""
    openness = (100 - saturation) * _PROOF.get(listings, 1.0)
    return round(openness if demand is None else demand * openness / 100)


def _demand_phrase(name: str) -> str:
    """A category name a shopper would actually type ('Woman Gloves & Mittens'
    -> 'woman gloves mittens'), for the autocomplete demand probe.

    Deliberately NOT the singularizing tokenizer used for matching -- people
    search "gloves", not "glove", and Suggest answers the real phrasing."""
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower())
             if w.rstrip("s") not in _CATEGORY_NOISE and w not in _CATEGORY_NOISE]
    return " ".join(words[:4]) or name.lower()


_VARIANT_TOKENS = 4   # leading title words that identify "the same product"


def _dedupe_variants(rows: list[dict]) -> list[dict]:
    """Collapse a product's size/colour variants into one shelf slot.

    CJ lists "Outdoor Chaise Lounge Cushion 72in" and "...80in" as separate
    products, so an undeduped shelf can be one item four times. Rows arrive
    ranked, so the first of a family is the best-scoring one."""
    seen, out = set(), []
    for r in rows:
        key = " ".join(_tokens(r["title"])[:_VARIANT_TOKENS])
        if key and key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _theme_weights(theme_tokens: set[str], rows: list[dict]) -> dict[str, float]:
    """How much each word of the theme actually discriminates, measured on what
    CJ returned.

    Not every theme word carries the same meaning. Searching "coffee brewing",
    CJ's OR-search floods the page with coffee TABLES and coffee-COLOURED
    earrings -- "coffee" appears everywhere and says almost nothing, while
    "brewing" appears rarely and says everything. Classic inverse-document-
    frequency over the scanned titles, so the rare word decides the ranking."""
    n = max(1, len(rows))
    weights = {}
    for t in theme_tokens:
        df = sum(1 for r in rows if t in set(_tokens(r["title"])))
        weights[t] = math.log(1 + n / (1 + df))
    return weights


def _match_score(leaf: dict, want: set[str]) -> int:
    """How well a leaf category answers the typed theme. The leaf's own name
    counts double -- 'Curtains' under Home Textiles beats every leaf in a
    department that merely mentions the word."""
    name = set(_tokens(leaf["name"]))
    path = set(_tokens(leaf["l1"] + " " + leaf["l2"]))
    return 2 * len(name & want) + len(path & want)


# The one model call in stage 1 -- and it only ever sees products that exist.
_CLUSTER_SYS = """You are a dropshipping operator reviewing REAL products pulled
live from CJdropshipping's catalog. Group them into STOREFRONT CONCEPTS -- each
one a small, coherent shop a specific audience would buy from.

You are NOT inventing products. Every product in the list exists and is
sourceable; your only job is deciding which ones belong in the same store and
what that store is.

HARD RULES:
- A concept is a SHOP, not a department: "Aquascaping tank tools", not "Pets".
- Its audience is an identifiable sub-culture with its own vocabulary and its own
  subreddits -- van-lifers, aquascapers, hammock campers, ferret owners, disc
  golfers, EDC collectors, tarot readers, beekeepers.
- Only group products that genuinely sell to the SAME buyer. Leave a product out
  rather than stretch a concept around it.
- These products came from a keyword search, so some merely SHARE A WORD with
  what the operator wants -- a coffee TABLE and a coffee-COLOURED earring are not
  coffee brewing. Discard those; do not build a store around them.
- Use each product index at most ONCE, and only indexes from the list.
- Between 2 and 8 products per concept.

Output JSON only:
{
  "stores": [
    {
      "name": "the storefront name -- what it sells, plainly",
      "audience": "who buys here -- a real, describable sub-culture",
      "angle": "the wedge -- why this shop wins right now",
      "keyword_seed": "the 2-4 word phrase this audience would search to buy",
      "subreddits": ["3-5 REAL subreddit names, no r/ prefix"],
      "products": [<indexes from the list>]
    }
  ]
}"""

_CLUSTER_SCHEMA = {
    "type": "object",
    "properties": {
        "stores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "audience": {"type": "string"},
                    "angle": {"type": "string"},
                    "keyword_seed": {"type": "string"},
                    "subreddits": {"type": "array", "items": {"type": "string"}},
                    "products": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["name", "audience", "angle", "keyword_seed",
                             "subreddits", "products"],
            },
        }
    },
    "required": ["stores"],
}


_AISLE_SYS = """You map a shopper's theme onto a dropship supplier's REAL category
list. You are given the supplier's actual aisles, numbered. Pick the ones whose
products that theme's buyers would shop -- including the non-obvious ones (a
"desk setup" buyer shops cable management, desk mats, lighting, and stationery).

You may ONLY return numbers from the list. Never invent a category.

Output JSON only: {"aisles": [<numbers, most relevant first>]}"""

_AISLE_SCHEMA = {
    "type": "object",
    "properties": {"aisles": {"type": "array", "items": {"type": "integer"}}},
    "required": ["aisles"],
}


async def _aisles_by_model(theme: str, groups: list[str], model: str | None) -> list[str]:
    """Ask the model which REAL aisles a theme shops. Returns group names (never
    anything invented -- it answers with indexes into the list we gave it)."""
    listing = "\n".join(f"{i}. {g}" for i, g in enumerate(groups))
    user = f"THEME: {theme}\n\nSUPPLIER AISLES:\n{listing}"
    try:
        data = parse_json(await get_heavy_llm().chat(
            [{"role": "system", "content": _AISLE_SYS}, {"role": "user", "content": user}],
            model=model, temperature=0.2, fmt=_AISLE_SCHEMA))
        picks = data.get("aisles", []) if isinstance(data, dict) else []
        return [groups[i] for i in picks if isinstance(i, int) and 0 <= i < len(groups)]
    except Exception as e:
        log.warning("aisle mapping failed for %r (%s)", theme, e)
        return []


async def _choose_grounds(theme: str, all_leaves: list[dict], k: int,
                          s: Steps | None) -> list[dict]:
    """Where to hunt, decided WITHOUT the model: a theme searches CJ's catalog
    for itself plus any categories whose names match; no theme rotates through
    leaves recent runs haven't visited. Widening (which does ask the model) only
    happens later, and only if this comes back thin."""
    if not theme.strip():
        picks = catalog.sample_fresh(all_leaves, k)
        if s:
            await s.done(f"Surprise me → rotating into {len(picks)} categories CJ "
                         "actually stocks, skipping recently scanned ones")
        return picks

    # Search the catalog for the theme itself FIRST. Plenty of real inventory
    # sits in no aisle you could guess: "ladders" has 816 products on CJ and no
    # ladder category, so browsing alone would never reach them (and asking a
    # model which aisle a ladder buyer shops gets you pet supplies).
    picks = [catalog.search_ground(theme)]
    want = set(_tokens(theme))
    scored = sorted(((_match_score(l, want), l) for l in all_leaves),
                    key=lambda t: -t[0])
    named = [l for score, l in scored if score > 0][:max(0, k - 1)]
    picks += named
    if s:
        await s.done(f"Searching CJ's catalog for “{theme}”"
                     + (f" + {len(named)} categor{'y' if len(named) == 1 else 'ies'} "
                        "matching it by name" if named else ""))
    return picks


async def _widen(theme: str, all_leaves: list[dict], have: list[dict], k: int,
                 model: str | None, s: Steps | None) -> list[dict]:
    """More ground for a theme whose own search came back thin.

    Most themes share no words with a supplier's aisle names, so the model maps
    the theme onto the REAL aisle list -- by index, so it can't conjure an aisle
    with nothing behind it. Its picks are still guesses, which is exactly why
    this runs only when CJ's own catalog didn't answer."""
    if k <= 0:
        return []
    groups = sorted({f"{l['l1']} > {l['l2']}" for l in all_leaves})
    if s:
        await s.running(f"Thin so far — asking which of CJ's real aisles "
                        f"“{theme}” buyers shop", key="aisles")
    chosen = await _aisles_by_model(theme, groups, model)
    want = set(_tokens(theme))
    pool = [l for l in all_leaves
            if f"{l['l1']} > {l['l2']}" in set(chosen) and l not in have]
    pool.sort(key=lambda l: -_match_score(l, want))
    extra = pool[:k]
    if not extra:  # no match, no model -> anything fresh beats an empty scan
        extra = catalog.sample_fresh([l for l in all_leaves if l not in have], k)
        if s:
            await s.done(f"Couldn't map “{theme}” onto CJ's aisles — sweeping "
                         f"{len(extra)} fresh categories instead", key="aisles")
    elif s:
        await s.done(f"Widened into {len(extra)} categories from {len(chosen)} "
                     f"aisles CJ really has", key="aisles")
    return extra


def _cluster_fallback(winners: list[dict], n: int, why: str = "") -> list[dict]:
    """Group by CJ's own category instead of by concept. Used twice: when the
    model is unavailable (a scan should never come back empty because the fleet
    is down) and to backfill the concepts it declined to build. Plainer names,
    same real products."""
    groups: dict[str, list[dict]] = {}
    for p in winners:
        groups.setdefault(p["category"], []).append(p)
    out = []
    for name, items in groups.items():
        if len(items) < _MIN_PER_STORE:
            continue
        out.append({
            "name": name,
            "audience": f"shoppers browsing {name.lower()}",
            "angle": why or "grouped straight from CJ's category — no concept "
                            "was shaped around these",
            "keyword_seed": _demand_phrase(name),
            "subreddits": [],
            "products": items[:_MAX_PER_STORE],
            "grouped_by": "category",
        })
    return out[:n]


async def _cluster(products: list[dict], n: int, model: str | None,
                   s: Steps | None, theme: str = "") -> list[dict]:
    """Group real products into store concepts (model), or fall back to CJ's
    categories. Returns concepts whose `products` are the real rows."""
    listing = "\n".join(
        f'{i}. {p["title"][:_TITLE_CHARS]} — ${p["price"] if p["price"] is not None else "?"}'
        f' · {p["listings"]} sellers · {p["category"]}'
        for i, p in enumerate(products)
    )
    asked = f'The operator is looking for stores around: {theme}.\n' if theme.strip() else ""
    user = (f"{asked}Group these {len(products)} real CJdropshipping products into "
            f"about {n} storefront concepts. Leave out anything that doesn't "
            f"fit.\n\n{listing}")
    messages = [{"role": "system", "content": _CLUSTER_SYS},
                {"role": "user", "content": user}]
    label = f"Grouping {len(products)} real products into store concepts"
    data = {}
    try:
        llm = get_heavy_llm()
        if s:
            await s.running(label)
            raw = ""
            async for chunk in llm.chat_stream(messages, model=model, temperature=0.4,
                                               fmt=_CLUSTER_SCHEMA):
                raw += chunk
                await s.thought(chunk)
            data = parse_json(raw)
            await s.done(label)
        else:
            data = parse_json(await llm.chat(messages, model=model, temperature=0.4,
                                             fmt=_CLUSTER_SCHEMA))
    except Exception as e:
        log.warning("clustering failed (%s)", e)
        if s:
            await s.done(f"{label} — failed ({e}); grouping by CJ category instead")
        return _cluster_fallback(products, n, "grouped by CJ category — the model "
                                              "wasn't available to shape a concept")

    out, used = [], set()
    for st in data.get("stores", []) if isinstance(data, dict) else []:
        if not isinstance(st, dict) or not st.get("name"):
            continue
        picked = []
        for i in st.get("products", []) if isinstance(st.get("products"), list) else []:
            if isinstance(i, int) and 0 <= i < len(products) and i not in used:
                used.add(i)
                picked.append(products[i])
            if len(picked) >= _MAX_PER_STORE:
                break
        if len(picked) < _MIN_PER_STORE:
            continue  # a shop with one product isn't a shop
        subs = st.get("subreddits")
        out.append({
            "name": str(st["name"]).strip(),
            "audience": str(st.get("audience", "")).strip(),
            "angle": str(st.get("angle", "")).strip(),
            "keyword_seed": str(st.get("keyword_seed") or st["name"]).strip(),
            "subreddits": [str(x).lstrip("r/") for x in subs] if isinstance(subs, list) else [],
            "products": picked,
        })
    return out or _cluster_fallback(products, n)


async def prospect(theme: str = "", model: str | None = None, n: int = 8,
                   pool: int = 0, max_saturation: int = DEFAULT_MAX_SATURATION,
                   emit=None) -> dict:
    """Scan CJ's catalog and return `n` storefront concepts made of real products.

    `pool` is roughly how many real products to scan (rounded to whole
    categories, ~1 request each). Returns the same envelope the old engine did --
    {theme, model, categories, scan} -- so the drill/promote paths are unchanged;
    each "category" is now a store concept carrying its real CJ products.
    """
    s = Steps(emit) if emit else None
    n = max(1, min(20, n))
    max_saturation = max(1, min(100, max_saturation))
    grounds_wanted = max(2, min(24, round((pool or n * 100) / catalog.PAGE)))

    all_leaves = await catalog.leaves()
    if not all_leaves:
        if s:
            await s.done("No CJ catalog — set CJ_EMAIL/CJ_API_KEY in .env. "
                         "Nothing to prospect without a supplier.")
        return {"theme": theme, "model": model or "", "categories": [],
                "error": "CJdropshipping is not configured (CJ_EMAIL/CJ_API_KEY)",
                "scan": {"scanned": 0, "categories_scanned": 0, "grounds": [],
                         "kept": 0, "requested": n, "measured": False,
                         "max_saturation": max_saturation}}
    if s:
        await s.done(f"CJ catalog: {len(all_leaves)} real leaf categories")

    grounds = await _choose_grounds(theme, all_leaves, grounds_wanted, s)

    # --- Pull real products, ground by ground (each page = 1 CJ request) ------
    scanned: list[dict] = []
    totals: dict[str, int] = {}
    off_topic = 0
    theme_tokens = set(_tokens(theme))

    async def pull(these: list[dict]) -> None:
        nonlocal off_topic
        for i, leaf in enumerate(these, 1):
            if s:
                await s.running(f"Pulling real products — {leaf['path']} "
                                f"({i}/{len(these)})", key="pull")
            # A keyword search is one ground but the richest one, and its
            # relevance filter throws a lot away -- go deeper on it.
            rows, total, dropped = await catalog.products(
                leaf, pages=_SEARCH_PAGES if leaf.get("query") else 1)
            totals[leaf["id"]] = total
            off_topic += dropped
            # A search ground IS the theme; a widened aisle only counts as
            # on-theme where the product's own name says so. Widening is filler,
            # and filler must never outrank what the operator actually asked for.
            for r in rows:
                # Provisional; re-scored against the whole scan below.
                r["on_theme"] = bool(theme_tokens & set(_tokens(r["title"])))
            scanned.extend(rows)

    await pull(grounds)
    if theme.strip() and len(scanned) < _THIN_SCAN:
        # CJ's own catalog didn't have much under this theme. NOW it's worth
        # asking the model where else to look.
        extra = await _widen(theme, all_leaves, grounds, grounds_wanted - len(grounds),
                             model, s)
        grounds += extra
        await pull(extra)
    catalog.remember_explored([l["id"] for l in grounds])
    if not scanned:
        if s:
            await s.done("CJ returned no products for those categories — try again "
                         "or pick a different theme", key="pull")
        return {"theme": theme, "model": model or "", "categories": [],
                "error": "no products returned by CJ",
                "scan": {"scanned": 0, "categories_scanned": len(grounds),
                         "grounds": [l["path"] for l in grounds], "kept": 0,
                         "requested": n, "measured": True,
                         "max_saturation": max_saturation}}

    # Score how well each product answers the theme, now that we can see how
    # common each theme word is in what CJ actually returned.
    if theme_tokens:
        w = _theme_weights(theme_tokens, scanned)
        for p in scanned:
            hit = theme_tokens & set(_tokens(p["title"]))
            p["theme_score"] = round(sum(w[t] for t in hit), 3)
            p["on_theme"] = p["theme_score"] > 0

    med = statistics.median(p["listings"] for p in scanned)
    if s:
        await s.done(f"Scanned {len(scanned)} real CJ products across {len(grounds)} "
                     f"categories — median {med:.0f} sellers already on each"
                     + (f" ({off_topic} off-category rows dropped)" if off_topic else ""),
                     key="pull")

    # --- Demand: one buyer-intent probe per category (free, ~no wall-clock) ----
    if s:
        await s.running(f"Probing buyer demand for {len(grounds)} categories", key="demand")
    phrases = [_demand_phrase(l["name"]) for l in grounds]
    scores = await demand_batch(phrases)
    demand_by_cat = {l["id"]: d for l, d in zip(grounds, scores)}
    live = [(l["name"], d) for l, d in zip(grounds, scores) if d]
    if s:
        top = ", ".join(f"{nm} {d}" for nm, d in sorted(live, key=lambda t: -t[1])[:3])
        await s.done(f"Demand measured for {len(live)}/{len(grounds)} categories"
                     + (f" — strongest: {top}" if top else ""), key="demand")

    # --- Score every real product: openness x demand --------------------------
    for p in scanned:
        p["saturation"] = _saturation(p["listings"])
        p["demand"] = demand_by_cat.get(p["category_id"])
        p["opportunity"] = _opportunity(p["demand"], p["saturation"], p["listings"])
        p["band"] = "crowded" if p["saturation"] > max_saturation else "open"

    open_lane = [p for p in scanned if p["band"] == "open"]
    crowded = len(scanned) - len(open_lane)
    # On-theme first, then by opportunity. Ask for ladders and you get ladders:
    # anything the widening dragged in only fills the seats they don't.
    ranked = sorted(open_lane or scanned,
                    key=lambda p: (-p.get("theme_score", 0), -p["opportunity"]))
    dropped_filler = 0
    if theme.strip():
        # Only build stores out of products that answer the theme. Widening is
        # there to FIND more of them, not to pad the board with whatever else was
        # in the aisle -- ask for ladders and a pet-bowl store is just noise.
        on = [p for p in ranked if p.get("on_theme")]
        if len(on) >= _MIN_PER_STORE:
            dropped_filler = len(ranked) - len(on)
            ranked = on
    winners = _dedupe_variants(ranked)[:_CLUSTER_POOL]
    if s:
        await s.done(f"{len(open_lane)} products under the saturation ceiling "
                     f"({max_saturation}) · {crowded} too crowded → taking the "
                     f"{len(winners)} best distinct products to build stores from"
                     + (f" (set aside {dropped_filler} that don't match “{theme}”)"
                        if dropped_filler else ""))

    # --- Cluster the winners into storefront concepts -------------------------
    concepts = await _cluster(winners, n, model, s, theme)
    if len(concepts) < n:
        # The model routinely groups fewer stores than asked and leaves good
        # products on the floor. Those products are real and already scored, so
        # shelve the leftovers by CJ category rather than throw the scan away.
        used = {p["pid"] for c in concepts for p in c["products"]}
        left = [p for p in winners if p["pid"] not in used]
        extra = _cluster_fallback(left, n - len(concepts))
        if extra and s:
            await s.done(f"Backfilled {len(extra)} more concept"
                         f"{'' if len(extra) == 1 else 's'} from {sum(len(c['products']) for c in extra)} "
                         "products the model left ungrouped")
        concepts += extra

    # --- Concept-level demand (its own shopper phrase) + ranking --------------
    if concepts:
        seeds = [c["keyword_seed"] for c in concepts]
        cd = await demand_batch(seeds)
        for c, d in zip(concepts, cd):
            # Best opportunity first, so the shelf reads top-down like the board.
            items = c["products"] = sorted(c["products"], key=lambda p: -p["opportunity"])
            c["saturation"] = round(statistics.mean(p["saturation"] for p in items))
            c["listings"] = round(statistics.mean(p["listings"] for p in items))
            # Two readings of demand: the concept's own shopper phrase, and the
            # aisles its products came from. Take the stronger -- a quiet
            # autocomplete on the model's phrasing isn't evidence that nobody
            # shops the category the products actually live in.
            aisle = max((p["demand"] or 0) for p in items)
            c["demand"] = max(d or 0, aisle) or None
            c["opportunity"] = _opportunity(c["demand"], c["saturation"], c["listings"])
            c["band"] = "crowded" if c["saturation"] > max_saturation else "open"
            c["saturation_method"] = "measured"
            c["saturation_supply"] = {"cjdropshipping": sum(
                totals.get(p["category_id"], 0) for p in items) // max(1, len(items))}
            c["supply_count"] = c["listings"]
            c["saturation_reasoning"] = (
                f"{c['listings']} CJ sellers on an average product in this concept")
            c["theme_score"] = round(
                statistics.mean(p.get("theme_score", 0) for p in items), 3)
            c["category_paths"] = sorted({p["category_path"] for p in items})
            prices = [p["price"] for p in items if p["price"] is not None]
            c["price_range"] = [min(prices), max(prices)] if prices else None
        # With a theme, relevance outranks score: a jewellery store that merely
        # shares the word "coffee" must not sit above the actual brewing shop,
        # however good its numbers are. Opportunity breaks ties within a
        # relevance tier, and orders the whole board when there's no theme.
        concepts.sort(key=lambda c: (-c.get("theme_score", 0), -c["opportunity"])
                      if theme.strip() else -c["opportunity"])
        concepts = concepts[:n]

    if s:
        kept = sum(len(c["products"]) for c in concepts)
        await s.done(f"Built {len(concepts)} storefront concept"
                     f"{'' if len(concepts) == 1 else 's'} from {kept} real CJ products")

    return {
        "theme": theme,
        "model": model or get_heavy_llm().default_model,
        "categories": concepts,
        "scan": {
            "scanned": len(scanned),
            "categories_scanned": len(grounds),
            # Only the grounds that actually put a product on the board. Listing
            # every aisle we touched reads as "this is what you got" when a
            # widened aisle may have contributed nothing at all.
            "grounds": [l["path"] for l in grounds
                        if l["id"] in {p["category_id"] for c in concepts
                                       for p in c["products"]}],
            "open": len(open_lane),
            "crowded": crowded,
            "kept": sum(len(c["products"]) for c in concepts),
            "concepts": len(concepts),
            "requested": n,
            "measured": True,
            "median_listings": round(med),
            "max_saturation": max_saturation,
        },
    }
