"""The opportunity flow the operator drives.

Stage 1 is CJ-first (see research/prospect.py): it scans real CJdropshipping
products and returns CAMPAIGN CONCEPTS -- each a cluster of actual, sourceable
products with their CJ ids, prices and images. Everything downstream therefore
starts from real inventory, not from an idea that may have nothing behind it.

Interactive, streamed (Server-Sent Events -- the UI watches the agent work):
  POST /api/opportunities/stream        button -> campaign-concept board
  POST /api/opportunities/drill/stream  one concept -> Reddit audience research
  POST /api/opportunities/automate/stream  one concept -> drill THEN build the campaign

Plain JSON (scripts/tests, no live steps):
  POST /api/opportunities   /drill   /promote
  GET  /api/opportunities   /{run_id}

A run stores the whole board; drilling caches its result back onto the run.
Promoting/automating turns a concept into a Campaign whose Products already
carry their real CJ product ids (Feature 2 only has to fetch the full gallery).
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import engine, get_session
from ..models import Campaign, Product, ResearchRun
from ..progress import Steps, sse
from ..research import DEFAULT_MAX_SATURATION, drill, prospect

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])

_SSE = {"media_type": "text/event-stream", "headers": {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}}


class ScoutRequest(BaseModel):
    theme: str = ""
    model: str | None = None
    n: int = 8              # storefront concepts to keep (the board length)
    pool: int = 0           # real CJ products to scan; 0 -> 100x n
    max_saturation: int = DEFAULT_MAX_SATURATION  # ceiling for "open lane"


class DrillRequest(BaseModel):
    run_id: int
    category_index: int
    model: str | None = None


class PromoteRequest(BaseModel):
    run_id: int
    category_index: int


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "store"


def _category_at(run: ResearchRun, idx: int) -> dict:
    cats = run.result.get("categories", [])
    if not (0 <= idx < len(cats)):
        raise ValueError("category_index out of range")
    return cats[idx]


def _load_category(run_id: int, idx: int) -> dict:
    with Session(engine) as session:
        run = session.get(ResearchRun, run_id)
        if not run:
            raise ValueError("run not found")
        return _category_at(run, idx)


def _cache_drill(run_id: int, idx: int, result: dict) -> None:
    with Session(engine) as session:
        run = session.get(ResearchRun, run_id)
        if not run:
            return
        new_result = dict(run.result)
        cats = list(new_result["categories"])
        cats[idx] = {**cats[idx], "drill": result}
        new_result["categories"] = cats
        run.result = new_result  # reassign so the JSON column is dirtied
        session.add(run)
        session.commit()


def _build_campaign(cat: dict, drill_result: dict | None = None) -> dict:
    """Create a Campaign from a concept, seeded with its REAL CJ products.

    The board already resolved these against CJ, so each Product lands with its
    cj_product_id, price and listing image -- nothing to search for. The
    campaign's resolve step later fetches each one's full gallery
    (products.hydrate)."""
    with Session(engine) as session:
        base = _slugify(cat["name"])
        slug, k = base, 2
        while session.exec(select(Campaign).where(Campaign.slug == slug)).first():
            slug, k = f"{base}-{k}", k + 1
        campaign = Campaign(
            slug=slug, name=cat["name"], category=cat["name"],
            audience=cat.get("audience", ""), description=cat.get("angle", ""),
        )
        session.add(campaign)
        session.commit()
        session.refresh(campaign)

        made = 0
        for p in cat.get("products", []):
            session.add(Product(
                campaign_id=campaign.id, title=p.get("title", "Untitled"),
                description="", cj_product_id=p.get("pid", ""),
                price=p.get("price"),
                images=[p["image"]] if p.get("image") else [],
                source=f"cjdropshipping:{p.get('category', '')}", status="candidate",
            ))
            made += 1
        session.commit()
        return {"campaign_id": campaign.id, "slug": slug, "products_seeded": made}


# ----------------------------- streaming ---------------------------------

@router.post("/stream")
async def scout_stream(req: ScoutRequest):
    async def job(emit):
        result = await prospect(req.theme, req.model, req.n, req.pool,
                                req.max_saturation, emit=emit)
        theme = result["theme"]
        with Session(engine) as session:
            run = ResearchRun(prompt=theme, model=result["model"], result=result)
            session.add(run)
            session.commit()
            session.refresh(run)
            rid = run.id
        await emit(type="result", data={"run_id": rid, **result})

    return StreamingResponse(sse(job), **_SSE)


@router.post("/drill/stream")
async def drill_stream(req: DrillRequest):
    async def job(emit):
        cat = _load_category(req.run_id, req.category_index)
        result = await drill(cat["name"], cat.get("subreddits", []), cat.get("audience", ""), req.model, cat.get("keyword_seed", ""), emit=emit)
        _cache_drill(req.run_id, req.category_index, result)
        await emit(type="result", data=result)

    return StreamingResponse(sse(job), **_SSE)


@router.post("/automate/stream")
async def automate_stream(req: DrillRequest):
    """The 'Start automation' button: research the audience, then build the
    campaign from the concept's real CJ products."""
    async def job(emit):
        cat = _load_category(req.run_id, req.category_index)
        s = Steps(emit)
        await s.running(f"Automating “{cat['name']}”")
        result = await drill(cat["name"], cat.get("subreddits", []), cat.get("audience", ""), req.model, cat.get("keyword_seed", ""), emit=emit)
        _cache_drill(req.run_id, req.category_index, result)

        await s.running("Building campaign from its real CJ products")
        built = _build_campaign(cat, result)
        await s.done(f"Built campaign /{built['slug']} with {built['products_seeded']} real CJ products")
        await s.done(f"Automating “{cat['name']}”")
        await emit(type="result", data={**built, "drill": result})

    return StreamingResponse(sse(job), **_SSE)


# ----------------------------- plain JSON --------------------------------

@router.post("")
async def scout(req: ScoutRequest, session: Session = Depends(get_session)):
    result = await prospect(req.theme, req.model, req.n, req.pool,
                            req.max_saturation)
    run = ResearchRun(prompt=result["theme"], model=result["model"], result=result)
    session.add(run)
    session.commit()
    session.refresh(run)
    return {"run_id": run.id, **result}


@router.post("/drill")
async def drill_category(req: DrillRequest, session: Session = Depends(get_session)):
    run = session.get(ResearchRun, req.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    try:
        cat = _category_at(run, req.category_index)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = await drill(cat["name"], cat.get("subreddits", []), cat.get("audience", ""), req.model, cat.get("keyword_seed", ""))
    _cache_drill(req.run_id, req.category_index, result)
    return {"run_id": run.id, "category_index": req.category_index, **result}


@router.post("/promote")
def promote(req: PromoteRequest, session: Session = Depends(get_session)):
    run = session.get(ResearchRun, req.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    try:
        cat = _category_at(run, req.category_index)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _build_campaign(cat, cat.get("drill"))


@router.get("")
def list_runs(session: Session = Depends(get_session)):
    runs = session.exec(select(ResearchRun).order_by(ResearchRun.created_at.desc())).all()
    return [
        {
            "id": r.id,
            "theme": r.prompt or "(broad)",
            "model": r.model,
            "categories": len(r.result.get("categories", [])),
            "created_at": r.created_at,
        }
        for r in runs
    ]


@router.get("/{run_id}")
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(ResearchRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": run.id, **run.result}
