"""The opportunity flow the operator drives:

  POST /api/opportunities         button -> category leaderboard (least saturated first)
  POST /api/opportunities/drill   one category -> Reddit-grounded product opportunities
  POST /api/opportunities/promote one category -> a Storefront (+ its drilled products)
  GET  /api/opportunities         run history
  GET  /api/opportunities/{id}    one run (with any drill results)

A run stores the whole leaderboard; drilling a category caches its result back
onto the run so the UI can revisit it. Promoting turns a category into a
Storefront and, if it's been drilled, seeds Product rows (candidates) carrying
the `cj_search_seed` Feature 2 will resolve against CJdropshipping.
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import Product, ResearchRun, Storefront
from ..research import drill, find_categories

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


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


def _get_category(run: ResearchRun, idx: int) -> dict:
    cats = run.result.get("categories", [])
    if not (0 <= idx < len(cats)):
        raise HTTPException(status_code=400, detail="category_index out of range")
    return cats[idx]


@router.post("")
async def scout(req: ScoutRequest, session: Session = Depends(get_session)):
    """The button: brainstorm + rank categories, least saturated first."""
    result = await find_categories(req.theme, req.model, req.n)
    run = ResearchRun(prompt=req.theme, model=result["model"], result=result)
    session.add(run)
    session.commit()
    session.refresh(run)
    return {"run_id": run.id, **result}


@router.post("/drill")
async def drill_category(req: DrillRequest, session: Session = Depends(get_session)):
    """Dig one category into Reddit -> concrete product opportunities."""
    run = session.get(ResearchRun, req.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    cat = _get_category(run, req.category_index)

    result = await drill(
        cat["name"], cat.get("subreddits", []), cat.get("audience", ""), req.model
    )

    # Cache the drill result onto the run (reassign so the JSON column is dirtied).
    new_result = dict(run.result)
    cats = list(new_result["categories"])
    cats[req.category_index] = {**cat, "drill": result}
    new_result["categories"] = cats
    run.result = new_result
    session.add(run)
    session.commit()
    return {"run_id": run.id, "category_index": req.category_index, **result}


@router.post("/promote")
def promote(req: PromoteRequest, session: Session = Depends(get_session)):
    """Category -> Storefront (+ Product candidates from its drilled opportunities)."""
    run = session.get(ResearchRun, req.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    cat = _get_category(run, req.category_index)

    base = _slugify(cat["name"])
    slug, k = base, 2
    while session.exec(select(Storefront).where(Storefront.slug == slug)).first():
        slug, k = f"{base}-{k}", k + 1

    store = Storefront(
        slug=slug,
        name=cat["name"],
        category=cat["name"],
        audience=cat.get("audience", ""),
        description=cat.get("angle", ""),
    )
    session.add(store)
    session.commit()
    session.refresh(store)

    # If the category was drilled, seed Product candidates carrying the CJ seed.
    made = 0
    drilled = cat.get("drill", {})
    for o in drilled.get("opportunities", []):
        session.add(
            Product(
                storefront_id=store.id,
                title=o.get("product", "Untitled"),
                description=o.get("rationale", ""),
                cj_product_id="",  # Feature 2 resolves this from cj_search_seed
                source=f"reddit:{o.get('cj_search_seed', '')}",
                status="candidate",
            )
        )
        made += 1
    session.commit()
    return {"storefront_id": store.id, "slug": slug, "products_seeded": made}


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
