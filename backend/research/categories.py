"""Stage 1 -- the leaderboard, built by DESCENDING into niches.

The old flow asked the model for N categories and measured exactly those N. Left
to itself the model reaches for the broad and obvious ("customized coffee mugs"),
and a broad seed is doomed twice over: it measures crowded on CJ, AND it drills
into a broad subreddit (r/yoga), so the products it surfaces are broad too.
Ranking can't fix candidates that are too high-level to begin with.

So we don't rank categories -- we descend into niches. Measure a batch of seed
directions, then keep DRILLING the least-saturated *sourceable* lanes into
narrower sub-niches ("yoga mat" -> "aerial yoga hammock" -> ...) and measuring
those, until narrowing stops lowering saturation (the floor, where tighter means
no supplier stocks it) or the budget runs out. The leaderboard is the niches we
land on -- each with its own specific seed + its own MICRO-community subreddits,
so the Reddit drill keys off the actual product, not a department.

Two ways to be useless, not one: too crowded (nothing to win) and too thin (no
supplier stocks it, so there's nothing to sell). The descent walks the band
between them, downhill.

Pass an `emit` callback (see app/progress.py) to stream the work -- named steps
plus the model's live thinking -- so the UI can show it happening.
"""
import asyncio
import logging

from ..config import get_settings
from ..llm import get_heavy_llm, parse_json
from ..progress import Steps
from . import saturation as sat
from .keywords import demand_batch

log = logging.getLogger(__name__)

# --- Descent policy -------------------------------------------------------
# A niche is only interesting inside a BAND. Above the ceiling it's a commodity
# fight; below the floor no supplier carries it, which looks wide-open on the
# saturation scale but is really a dead end. The descent walks between them.
DEFAULT_MAX_SATURATION = 65   # ~400 phrase-matched products on the log scale
# Genuine phrase-matched products (out of a 200-item CJ sample) a seed needs to
# count as sourceable. 1 let flukes through (a single lucky hit -> "supplier
# exists"); 3 demands real catalog depth. Trade-off: because CJ's page isn't
# relevance-ranked, some genuine-but-under-sampled niches also matched only 1-2
# and will now drop out -> a sturdier but smaller board.
MIN_SOURCEABLE_MATCHES = 3
_ROUND_MIN = 12               # candidates asked for in the seed round
_BEAM = 4                     # how many lanes to drill deeper each descent round
_MAX_POOL = 200               # hard cap -- supply lookups are rate-limited (~1/sec)

_SYS = """You are a product-opportunity scout for a dropshipping/print-on-demand
operator sourcing from CJdropshipping. Name SPECIFIC PRODUCTS an underserved
audience already wants -- not departments, not broad categories.

Every candidate you return is measured against CJdropshipping's real catalog.
Broad categories always come back saturated: "coffee mug" returns ~40,000
products and is worthless to this operator. Your value is finding the narrow
lanes a lazy keyword search would never surface.

HARD RULES:
- A product, not a department. "Yoga mats" is a department. "Cork travel yoga
  mat with alignment lines" is a product.
- The audience must be an identifiable sub-culture with its own vocabulary and
  its own subreddits -- van-lifers, aquascapers, hammock campers, ferret owners,
  disc golfers, bouldering gyms, EDC collectors, tarot readers, beekeepers.
- NEVER return these -- they are the most saturated products on earth: phone
  cases/covers, coffee mugs, t-shirts, tote bags, water bottles, generic
  jewelry, mouse pads, or "customized/personalized <mass-market item>".
- It must still be sourceable from a Chinese dropship catalog: physical, small,
  shippable, unlicensed, not bespoke or made-to-order.

Rate saturation 0-100 (0 = wide open, 100 = brutally crowded) as your best prior
-- real supply counts will overrule you, so an honest guess beats a flattering one.

Output JSON only:
{
  "categories": [
    {
      "name": "the specific product (what you'd put on a product page)",
      "audience": "who buys it -- a real, describable sub-culture",
      "saturation": 0-100,
      "saturation_reasoning": "one honest sentence on why that number",
      "angle": "the wedge -- why a new store can win here right now",
      "keyword_seed": "the 2-5 word phrase you'd type into a SUPPLIER CATALOG to find exactly this product (e.g. 'cork yoga mat alignment', not 'yoga' and not the whole sentence)",
      "subreddits": ["3-5 REAL subreddit names (no r/ prefix) where this audience actually gathers"]
    }
  ]
}
Return the requested count. Every one distinct -- no two variants of the same product."""


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


def _norm(seed: str) -> str:
    return " ".join(str(seed or "").lower().split())


def _opportunity(demand: int | None, saturation: int) -> int:
    """Best-of-both-worlds score: high demand AND low saturation.

    opportunity = demand × openness, where openness = (100 - saturation)/100. The
    product form is deliberate -- a niche nobody searches for (demand≈0) scores ≈0
    no matter how wide open, so the descent can't bottom out in unsellable niches;
    a saturated product scores low even if demand is high. When demand is unknown
    (Suggest didn't answer) we fall back to openness alone."""
    openness = 100 - saturation
    return openness if demand is None else round(demand * openness / 100)


# The descent step: turn already-measured lanes into NARROWER ones. This is what
# pushes saturation down -- a broad seed's job is to point at a direction, then
# we drill INTO it for a niche a smaller community wants and fewer sellers serve.
_NARROW_SYS = """You are refining product ideas for a dropshipping operator
sourcing from CJdropshipping. You are given specific products already measured
against the REAL CJ catalog -- each with its saturation (0 = wide open, 100 =
brutally crowded) and how many supplier products carry it.

For EACH product, output 2-3 NARROWER sub-niches -- same lane, tighter focus --
so saturation drops but a supplier still stocks it. Narrow by adding ONE concrete
axis:
- a sub-community: "yoga mat" -> "aerial yoga hammock", "hot yoga towel mat"
- a material/spec: "dog bed" -> "orthopedic memory-foam dog bed", "cooling gel dog mat"
- a use-case/constraint: "desk organizer" -> "cable organizer for standing desks"

HARD RULES:
- Go NARROWER than the parent, never broader, and never drift to a different product.
- Each sub-niche names a SPECIFIC product a supplier would actually list -- a
  2-4 word `keyword_seed` (e.g. "aerial yoga hammock", not "yoga").
- Its audience is a MICRO-community with its OWN subreddits -- name the NICHE
  subs (r/aerialists, r/hotyoga), NOT the broad parent sub (r/yoga).
- Still sourceable from a Chinese dropship catalog: physical, small, shippable,
  unlicensed, not bespoke.

The most crowded parents have the most room to improve -- narrow those hardest.

Output JSON only (same schema): a "categories" list of the sub-niches, most
promising (lowest expected saturation, still sourceable) first."""


def _clean_candidates(data) -> list[dict]:
    """Normalize a model `categories` payload into unmeasured candidate dicts."""
    out = []
    for c in data.get("categories", []) if isinstance(data, dict) else []:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        c["saturation"] = _clamp(c.get("saturation"))
        if not isinstance(c.get("subreddits"), list):
            c["subreddits"] = []
        # Short seed for the supplier lookup; the full name matches nothing.
        if not c.get("keyword_seed"):
            c["keyword_seed"] = c["name"]
        c["saturation_method"] = "estimated"
        c["saturation_supply"] = {}
        c["supply_count"] = None
        c["band"] = "unmeasured"
        out.append(c)
    return out


async def _generate(llm, model, messages, temperature, label, s) -> list[dict]:
    """Run one generation call (seed or narrow) and return cleaned candidates."""
    try:
        if s:
            await s.running(label)
            raw = ""
            async for chunk in llm.chat_stream(messages, model=model,
                                               temperature=temperature, fmt=_SCHEMA):
                raw += chunk
                await s.thought(chunk)
            data = parse_json(raw)
            await s.done(label)
        else:
            data = parse_json(await llm.chat(messages, model=model,
                                             temperature=temperature, fmt=_SCHEMA))
    except Exception as e:
        log.warning("category generation failed (%s)", e)
        if s:
            await s.done(f"{label} — failed ({e})")
        return []
    return _clean_candidates(data)


async def _brainstorm(llm, model, theme: str, count: int, s: Steps | None) -> list[dict]:
    """The SEED round -- directions to descend into, not the final answer."""
    scope = f"Focus on this space: {theme}." if theme.strip() else (
        "No theme given -- range widely across consumer sub-cultures."
    )
    user = (f"{scope}\nReturn {count} candidate products. These are STARTING "
            "POINTS -- we will measure each and then drill into narrower niches, "
            "so lean specific but it's fine if some are still a bit broad.")
    messages = [{"role": "system", "content": _SYS}, {"role": "user", "content": user}]
    return await _generate(llm, model, messages, 0.6, f"Seeding {count} directions", s)


async def _narrow(llm, model, parents: list[dict], s: Steps | None, depth: int) -> list[dict]:
    """The DESCENT round -- narrower sub-niches of measured parents."""
    block = "\n".join(
        f'- "{p["name"]}" (seed "{p["keyword_seed"]}", audience: {p.get("audience","?")}) '
        f'-> measured saturation {p["saturation"]}/100, ~{p.get("supply_count","?")} '
        f'supplier products'
        for p in parents
    )
    user = ("Narrow each of these measured products into 2-3 lower-saturation "
            f"sub-niches:\n{block}\n\nReturn them all in one list.")
    messages = [{"role": "system", "content": _NARROW_SYS}, {"role": "user", "content": user}]
    # Hotter as we go deeper -- the obvious narrowing is the first one it reaches for.
    temperature = min(0.9, 0.6 + 0.1 * depth)
    return await _generate(llm, model, messages, temperature,
                           f"Narrowing {len(parents)} lanes into niches (depth {depth})", s)


async def find_categories(theme: str = "", model: str | None = None, n: int = 8,
                          pool: int = 0, max_saturation: int = DEFAULT_MAX_SATURATION,
                          emit=None) -> dict:
    """Seed broad directions, then DESCEND into niches, returning the `n` lowest-
    saturation sourceable products -- each carrying its own niche seed + niche
    subreddits, so the Reddit drill keys off the specific product, not a category.

    The engine is a saturation-guided descent: measure a seed batch, then keep
    drilling the least-saturated *sourceable* lanes into narrower sub-niches and
    measuring those, until narrowing stops lowering saturation (we've hit the
    floor where going tighter means no supplier stocks it) or the `pool` budget
    runs out. Broad seeds are never the answer -- only the direction.

    `pool` is the total candidate budget (defaults to 5x n; CJ lookups are
    rate-limited, so this bounds wall-clock). With no supply source it degrades
    to a single estimated seed round.

    Runs on the HEAVY node (bigger model) when one is configured -- generation is
    where model knowledge matters most. Drills stay on the fast node.
    """
    settings = get_settings()
    llm = get_heavy_llm()
    # When a heavy node is configured, its model does stage 1 (ignore the drill
    # model picker here); otherwise honor the picked/default model.
    if settings.ollama_heavy_base_url:
        model = None
    s = Steps(emit) if emit else None

    can_measure = settings.has_cj
    n = max(1, min(50, n))
    pool = min(max(n, pool or n * 5), _MAX_POOL) if can_measure else n
    max_saturation = max(1, min(100, max_saturation))

    if s:
        await s.done(f"Connected to edge-ai ({model or llm.default_model})")
        if can_measure:
            await s.done(
                f"Seed then descend: scan up to {pool} candidates, drilling the "
                f"best-opportunity lanes into narrower niches; keep the {n} with "
                f"the best demand-vs-saturation"
            )
        else:
            await s.done("No supply source configured — using the model's estimate")

    seen: set[str] = set()
    sourceable: list[dict] = []   # matched >= MIN (open or crowded) -> sellable & narrowable
    thin: list[dict] = []         # no supplier carries it -> nothing to sell
    scanned = 0
    rounds = 0

    def _fresh(cands: list[dict]) -> list[dict]:
        out = []
        for c in cands:
            k = _norm(c["keyword_seed"])
            if k and k not in seen:
                seen.add(k)
                out.append(c)
        return out

    async def measure(cands: list[dict], label: str) -> list[dict]:
        """Measure a batch, classify by band, file into sourceable/thin. Returns
        the sourceable subset (the frontier the descent narrows next)."""
        nonlocal scanned
        key = f"measure-{rounds}"
        done_n = 0

        async def progress(_i, _kw, _r):
            nonlocal done_n
            done_n += 1
            if s and done_n % 4 == 0:
                await s.running(f"{label} — {done_n}/{len(cands)}", key=key)

        if s:
            await s.running(label, key=key)
        seeds_kw = [c["keyword_seed"] for c in cands]
        # Supply (CJ, throttled) and demand (Google Suggest, fast) in parallel --
        # demand adds ~no wall-clock since it finishes long before the CJ batch.
        results, demand_scores = await asyncio.gather(
            sat.measure_batch(seeds_kw, on_result=progress),
            demand_batch(seeds_kw),
        )
        fresh_sourceable = []
        r_open = r_crowded = r_thin = 0
        for c, r, d in zip(cands, results, demand_scores):
            if not r["measured"]:
                continue  # provider errored for this one -- drop it (keep the seed set clean)
            c["saturation"] = r["saturation"]  # from extrapolated supply (smooth)
            c["saturation_method"] = "measured"
            c["saturation_supply"] = r["supply"]
            c["supply_count"] = r["supply"]["cjdropshipping"]
            c["demand"] = d  # 0-100 buyer-intent breadth, or None if Suggest was quiet
            # matched = products we DIRECTLY saw carry the phrase; the sourceable
            # gate ("does a supplier stock this at all?") uses it, not the estimate.
            if r["sourceable"] < MIN_SOURCEABLE_MATCHES:
                c["band"] = "thin"
                thin.append(c)
                r_thin += 1
            else:
                c["opportunity"] = _opportunity(d, c["saturation"])
                c["band"] = "crowded" if c["saturation"] > max_saturation else "open"
                sourceable.append(c)
                fresh_sourceable.append(c)
                r_open, r_crowded = (r_open + 1, r_crowded) if c["band"] == "open" \
                    else (r_open, r_crowded + 1)
        scanned += len(cands)
        if s:
            await s.done(
                f"{label} — {r_open} open, {r_crowded} still crowded, "
                f"{r_thin} not sourceable",
                key=key,
            )
        return fresh_sourceable

    # --- Seed round: directions to descend into --------------------------------
    rounds += 1
    want = min(max(_ROUND_MIN, n * 2), pool)
    seeds = _fresh(await _brainstorm(llm, model, theme, want, s))

    if not can_measure:  # no supply source -> the seed set IS the answer (estimated)
        cats = sorted(seeds, key=lambda c: c["saturation"])[:n]
        if s:
            await s.done(f"Ranked {len(cats)} products (model estimate)")
        return {"theme": theme, "model": model or llm.default_model, "categories": cats,
                "scan": {"scanned": 0, "rounds": rounds, "pool": pool, "open": 0,
                         "crowded": 0, "thin": 0, "measured": False,
                         "max_saturation": max_saturation,
                         "min_matches": MIN_SOURCEABLE_MATCHES}}

    if seeds:
        await measure(seeds, f"Measuring {len(seeds)} seed products")

    # --- Descent: drill the best-opportunity lanes into tighter niches ---------
    expanded: set[str] = set()
    best = max((c["opportunity"] for c in sourceable), default=-1)
    stall = 0
    while scanned < pool and stall < 2:
        # Frontier: sourceable lanes not yet drilled, BEST OPPORTUNITY first --
        # refine the winners, since narrowing trades saturation (down) against
        # demand (down too), and we only want narrower when the balance improves.
        frontier = sorted(
            (c for c in sourceable if _norm(c["keyword_seed"]) not in expanded),
            key=lambda c: -c["opportunity"],
        )
        parents = frontier[:_BEAM]
        if not parents:
            break
        for p in parents:
            expanded.add(_norm(p["keyword_seed"]))
        rounds += 1
        kids = _fresh(await _narrow(llm, model, parents, s, rounds - 1))[: pool - scanned]
        if not kids:
            break
        fresh = await measure(kids, f"Measuring {len(kids)} narrower niches")
        new_best = max((c["opportunity"] for c in fresh), default=-1)
        if new_best > best:
            best, stall = new_best, 0
        else:
            stall += 1  # narrowing no longer improves opportunity -> good enough

    # --- Rank: best opportunity first (demand × low saturation) -----------------
    sourceable.sort(key=lambda c: -c["opportunity"])
    open_lanes = [c for c in sourceable if c["band"] == "open"]
    crowded = [c for c in sourceable if c["band"] == "crowded"]
    cats = sourceable[:n]

    if s:
        await s.done(
            f"Scanned {scanned} candidates over {rounds} rounds → "
            f"{len(open_lanes)} open niches (best opportunity {best if best >= 0 else '—'}), "
            f"{len(crowded)} still crowded, {len(thin)} not sourceable"
        )
        await s.done(f"Ranked {len(cats)} products by opportunity (demand × low saturation)")

    return {
        "theme": theme,
        "model": model or llm.default_model,
        "categories": cats,
        "scan": {
            "scanned": scanned,
            "rounds": rounds,
            "pool": pool,
            "open": len(open_lanes),
            "crowded": len(crowded),
            "thin": len(thin),
            "measured": can_measure,
            "max_saturation": max_saturation,
            "min_matches": MIN_SOURCEABLE_MATCHES,
        },
    }
