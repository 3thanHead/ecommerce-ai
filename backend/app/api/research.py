"""Research endpoints: run the agent, browse past runs, promote a candidate.

A run is persisted whole (ResearchRun.result) so the UI can revisit it. Promoting
a candidate turns one niche into a Storefront + Niche row -- the seam Feature 2
(CJ product matching) will hang products off.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import Niche, ResearchRun, Storefront
from ..research import research as run_research

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/research", tags=["research"])


class ResearchRequest(BaseModel):
    prompt: str
    audience: str = ""
    model: str | None = None
    use_web: bool = True


def _slugify(text: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "store"


@router.post("")
async def create_research(req: ResearchRequest, session: Session = Depends(get_session)):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")
    result = await run_research(req.prompt, req.audience, req.model, req.use_web)

    run = ResearchRun(
        prompt=req.prompt, audience=result["audience"], model=result["model"], result=result
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return {"run_id": run.id, **result}


@router.get("")
def list_runs(session: Session = Depends(get_session)):
    runs = session.exec(select(ResearchRun).order_by(ResearchRun.created_at.desc())).all()
    return [
        {
            "id": r.id,
            "prompt": r.prompt,
            "audience": r.audience,
            "model": r.model,
            "candidates": len(r.result.get("candidates", [])),
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


class PromoteRequest(BaseModel):
    run_id: int
    candidate_index: int
    create_storefront: bool = True


@router.post("/promote")
def promote(req: PromoteRequest, session: Session = Depends(get_session)):
    """Turn one research candidate into a Niche (+ optionally a Storefront)."""
    run = session.get(ResearchRun, req.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    candidates = run.result.get("candidates", [])
    if not (0 <= req.candidate_index < len(candidates)):
        raise HTTPException(status_code=400, detail="candidate_index out of range")
    c = candidates[req.candidate_index]

    storefront_id = None
    if req.create_storefront:
        base = _slugify(c.get("name", "store"))
        slug = base
        n = 2
        while session.exec(select(Storefront).where(Storefront.slug == slug)).first():
            slug = f"{base}-{n}"
            n += 1
        store = Storefront(
            slug=slug,
            name=c.get("name", "Untitled"),
            category=c.get("name", ""),
            audience=c.get("audience", ""),
            description=c.get("rationale", ""),
        )
        session.add(store)
        session.commit()
        session.refresh(store)
        storefront_id = store.id

    niche = Niche(
        storefront_id=storefront_id,
        research_run_id=run.id,
        name=c.get("name", "Untitled"),
        audience=c.get("audience", ""),
        rationale=c.get("rationale", ""),
        demand=int(c.get("demand", 0)),
        saturation=int(c.get("saturation", 0)),
        saturation_reasoning=c.get("saturation_reasoning", ""),
        example_products=c.get("example_products", []),
        keywords=c.get("keywords", []),
        sources={"reddit_via_api": run.result.get("reddit_via_api")},
    )
    session.add(niche)
    session.commit()
    session.refresh(niche)
    return {"niche_id": niche.id, "storefront_id": storefront_id}
