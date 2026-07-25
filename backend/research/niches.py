"""Niche-space discovery -- the AI picks the obscure sub-cultures so you don't
have to.

The descent (categories.py) needs a SPECIFIC starting point to be productive, but
a blank theme leaves it unanchored and a typed theme puts the niche-inventing back
on you. So one cheap model call proposes specific enthusiast communities, and the
app anchors the descent to a few FRESH ones -- spaces it hasn't explored recently.
That approximates "keep searching for new niches" without any background/polling
cost: each button press just advances the coverage.

Explored spaces persist to a small JSON file in the mounted data/ volume, so the
rotation is real across restarts and sessions.
"""
import json
import logging
import os

from ..config import get_settings
from ..llm import get_heavy_llm, parse_json
from ..progress import Steps

log = logging.getLogger(__name__)

_EXPLORED_FILE = "data/.explored_niches.json"
_EXPLORED_CAP = 400  # keep the last N so rotation eventually wraps, not grows forever

_SYS = """You are a scout for a dropshipping operator sourcing from CJdropshipping
(a mass Chinese dropship catalog). Name SPECIFIC, UNDERSERVED enthusiast
sub-cultures -- communities with their own vocabulary, their own subreddits, and
a habit of buying physical GEAR online.

CRITICAL -- the community must buy MASS-PRODUCED physical accessories a Chinese
dropship catalog actually stocks: tools, organizers, mounts, storage, lighting,
apparel accessories, care/cleaning kits, cases, stands. If their passion is about
vintage media, handmade/artisanal goods, licensed collectibles, food, or bespoke
one-offs, a dropship supplier makes NONE of it -- skip those (they're underserved
because nobody can source them, a dead end).

Be surprising and precise, never a broad market. Good picks -- niche BUT swimming
in sourceable gear:
- "cold plunge / ice bath enthusiasts" (tubs, chillers, thermometers, mats)
- "mechanical keyboard builders" (keycaps, switches, tools, mats, cases)
- "overlanders" (recovery gear, storage, lighting, mounts)
- "reef aquarium keepers" (dosing gear, frag tools, lighting mounts)
- "indoor bouldering gyms" (brushes, chalk gear, grip trainers, mats)
- "home baristas", "hydroponic growers", "disc golfers", "van-lifers"
Avoid: vintage/retro media, quilting/handmade, LARP/cosplay armor, trading
cards, anything a factory doesn't mass-produce.

Output JSON only:
{
  "niches": [
    {"space": "the sub-culture, 3-6 words", "why": "one line: the mass-produced gear they buy + why underserved"}
  ]
}
Return the requested count, each distinct."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "niches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "space": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["space", "why"],
            },
        }
    },
    "required": ["niches"],
}


def _norm(space: str) -> str:
    return " ".join(str(space or "").lower().split())


def load_explored() -> list[str]:
    try:
        with open(_EXPLORED_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def record_explored(spaces: list[str]) -> None:
    """Append newly-descended niche-spaces so later runs pick different ones."""
    cur = load_explored()
    seen = set(cur)
    for sp in spaces:
        k = _norm(sp)
        if k and k not in seen:
            cur.append(k)
            seen.add(k)
    cur = cur[-_EXPLORED_CAP:]
    try:
        os.makedirs(os.path.dirname(_EXPLORED_FILE) or ".", exist_ok=True)
        with open(_EXPLORED_FILE, "w") as f:
            json.dump(cur, f)
    except Exception as e:
        log.debug("could not persist explored niches (%s)", e)


async def suggest(model: str | None = None, k: int = 20, emit=None) -> list[dict]:
    """Ask the model for `k` obscure niche-spaces, biased away from explored ones.

    Does NOT record anything -- only descending into a space (pick_fresh) marks it
    explored, so re-suggesting the list is free of side effects."""
    llm = get_heavy_llm()
    if get_settings().ollama_heavy_base_url:
        model = None
    s = Steps(emit) if emit else None

    explored = load_explored()
    # Show the model the most-recent explored spaces so its list is fresh too.
    avoid = ", ".join(explored[-40:]) if explored else "(none yet)"
    user = (f"Name {k} niche sub-cultures worth building a store around.\n"
            f"Do NOT return these already-explored ones (or near-synonyms): {avoid}.")
    messages = [{"role": "system", "content": _SYS}, {"role": "user", "content": user}]

    label = f"Scouting {k} obscure niche-spaces"
    try:
        if s:
            await s.running(label)
            raw = ""
            async for chunk in llm.chat_stream(messages, model=model, temperature=0.9, fmt=_SCHEMA):
                raw += chunk
                await s.thought(chunk)
            data = parse_json(raw)
            await s.done(label)
        else:
            data = parse_json(await llm.chat(messages, model=model, temperature=0.9, fmt=_SCHEMA))
    except Exception as e:
        log.warning("niche scout failed (%s)", e)
        if s:
            await s.done(f"{label} — failed ({e})")
        return []

    out, seen = [], set()
    explored_set = set(explored)
    for nzn in data.get("niches", []) if isinstance(data, dict) else []:
        if not isinstance(nzn, dict) or not nzn.get("space"):
            continue
        key = _norm(nzn["space"])
        if key in seen or key in explored_set:  # dedup within the list + vs explored
            continue
        seen.add(key)
        out.append({"space": nzn["space"].strip(), "why": nzn.get("why", "").strip(),
                    "fresh": True})
    return out


def pick_fresh(suggested: list[dict], k: int) -> list[dict]:
    """Take the first `k` un-explored spaces and MARK them explored (rotation)."""
    explored = set(load_explored())
    fresh = [n for n in suggested if _norm(n["space"]) not in explored]
    chosen = (fresh or suggested)[:k]
    record_explored([n["space"] for n in chosen])
    return chosen
