"""The opportunity flow the operator drives.

Interactive, streamed (Server-Sent Events -- the UI watches the agent work):
  POST /api/opportunities/stream        button -> category leaderboard
  POST /api/opportunities/drill/stream  one category -> Reddit + keywords -> products
  POST /api/opportunities/automate/stream  one category -> drill THEN build the storefront

Plain JSON (scripts/tests, no live steps):
  POST /api/opportunities   /drill   /promote
  GET  /api/opportunities   /{run_id}

A run stores the whole leaderboard; drilling caches its result back onto the run.
Promoting/automating turns a category into a Storefront and seeds Product
candidates carrying the `cj_search_seed` Feature 2 resolves against CJdropshipping.
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import engine, get_session
from ..models import Product, ResearchRun, Storefront
from ..progress import Steps, sse
from ..research import drill, find_categories

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])

_SSE = {"media_type": "text/event-stream", "headers": {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}}


class ScoutRequest(BaseModel):
    theme: str = ""
    model: str | None = None
    n: int = 12


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


def _build_storefront(cat: dict, drill_result: dict | None) -> dict:
    """Create a Storefront from a category (+ Product candidates if drilled)."""
    with Session(engine) as session:
        base = _slugify(cat["name"])
        slug, k = base, 2
        while session.exec(select(Storefront).where(Storefront.slug == slug)).first():
            slug, k = f"{base}-{k}", k + 1
        store = Storefront(
            slug=slug, name=cat["name"], category=cat["name"],
            audience=cat.get("audience", ""), description=cat.get("angle", ""),
        )
        session.add(store)
        session.commit()
        session.refresh(store)

        made = 0
        for o in (drill_result or {}).get("opportunities", []):
            session.add(Product(
                storefront_id=store.id, title=o.get("product", "Untitled"),
                description=o.get("rationale", ""), cj_product_id="",
                source=f"reddit:{o.get('cj_search_seed', '')}", status="candidate",
            ))
            made += 1
        session.commit()
        return {"storefront_id": store.id, "slug": slug, "products_seeded": made}


# ----------------------------- streaming ---------------------------------

@router.post("/stream")
async def scout_stream(req: ScoutRequest):
    async def job(emit):
        result = await find_categories(req.theme, req.model, req.n, emit=emit)
        with Session(engine) as session:
            run = ResearchRun(prompt=req.theme, model=result["model"], result=result)
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
    """The 'Start automation' button: drill the category, then build its storefront."""
    async def job(emit):
        cat = _load_category(req.run_id, req.category_index)
        s = Steps(emit)
        await s.running(f"Automating “{cat['name']}”")
        result = await drill(cat["name"], cat.get("subreddits", []), cat.get("audience", ""), req.model, cat.get("keyword_seed", ""), emit=emit)
        _cache_drill(req.run_id, req.category_index, result)

        await s.running("Building storefront + product candidates")
        built = _build_storefront(cat, result)
        await s.done(f"Built storefront /{built['slug']} with {built['products_seeded']} products")
        await s.done(f"Automating “{cat['name']}”")
        await emit(type="result", data={**built, "drill": result})

    return StreamingResponse(sse(job), **_SSE)


# ----------------------------- plain JSON --------------------------------

@router.post("")
async def scout(req: ScoutRequest, session: Session = Depends(get_session)):
    result = await find_categories(req.theme, req.model, req.n)
    run = ResearchRun(prompt=req.theme, model=result["model"], result=result)
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
    return _build_storefront(cat, cat.get("drill"))


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
