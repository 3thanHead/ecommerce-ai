"""Campaign + product + niche management -- what the admin UI reads and writes.

Campaigns are the batches of products the agent's niches become -- each one a
push of real, sourced products through content generation and out to social
media. Products (Feature 2) and niches hang off them. Deliberately plain CRUD;
the interesting logic lives in the research agent, not here.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import engine, get_session
from ..models import Campaign, Niche, Product
from ..progress import Steps, sse
from ..research.products import ground_product, hydrate

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["campaigns"])

_SSE = {"media_type": "text/event-stream",
        "headers": {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}}


def _seed_of(p: Product) -> str:
    """The CJ search seed a candidate carries -- stored on `source` as
    '<kind>:<seed>' by the promote/automate build; fall back to the title."""
    src = p.source or ""
    if ":" in src:
        return src.split(":", 1)[1].strip() or p.title
    return p.title


class CampaignIn(BaseModel):
    name: str
    category: str = ""
    audience: str = ""
    description: str = ""
    slug: str | None = None


def _slugify(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "campaign"


@router.get("/campaigns")
def list_campaigns(session: Session = Depends(get_session)):
    campaigns = session.exec(select(Campaign).order_by(Campaign.created_at.desc())).all()
    out = []
    for c in campaigns:
        n_products = len(session.exec(select(Product).where(Product.campaign_id == c.id)).all())
        out.append({**c.model_dump(), "product_count": n_products})
    return out


@router.post("/campaigns")
def create_campaign(body: CampaignIn, session: Session = Depends(get_session)):
    slug = _slugify(body.slug or body.name)
    if session.exec(select(Campaign).where(Campaign.slug == slug)).first():
        raise HTTPException(status_code=409, detail=f"slug '{slug}' already exists")
    campaign = Campaign(
        slug=slug,
        name=body.name,
        category=body.category,
        audience=body.audience,
        description=body.description,
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, session: Session = Depends(get_session)):
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="campaign not found")
    products = session.exec(select(Product).where(Product.campaign_id == campaign_id)).all()
    niches = session.exec(select(Niche).where(Niche.campaign_id == campaign_id)).all()
    return {**campaign.model_dump(), "products": products, "niches": niches}


@router.post("/campaigns/{campaign_id}/resolve/stream")
async def resolve_products(campaign_id: int):
    """Fill in each product's full CJ data (gallery, video, current price).

    Two kinds of candidate, and the stage-1 board now produces the first:
      already has a cj_product_id -> just fetch its detail (no search, no judging)
      seed only                   -> search CJ and have the model verify a match
    Promoted products arrive with the pid and the single listing thumbnail, so
    "has an image" isn't "is resolved" -- anything still on one image gets its
    full gallery fetched. Products with a real gallery are skipped."""
    async def job(emit):
        s = Steps(emit)
        with Session(engine) as session:
            campaign = session.get(Campaign, campaign_id)
            if not campaign:
                await emit(type="error", message="campaign not found")
                return
            campaign_audience = campaign.audience
            products = session.exec(
                select(Product).where(Product.campaign_id == campaign_id)).all()
            work = [(p.id, p.cj_product_id, _seed_of(p), p.title,
                     (p.images or [None])[0])
                    for p in products
                    if not p.cj_product_id or len(p.images or []) <= 1]

        if not work:
            await s.done("Nothing to resolve — every product already has its CJ data")
        else:
            known = sum(1 for w in work if w[1])
            await s.running(f"Fetching CJ data for {len(work)} products"
                            + (f" ({known} already matched to a CJ id)" if known else ""))
        resolved = 0
        for db_id, pid, seed, title, thumb in work:
            r = (await hydrate(pid, fallback_image=thumb or "") if pid
                 else await ground_product(seed, idea=title, audience=campaign_audience))
            with Session(engine) as session:
                p = session.get(Product, db_id)
                if r and p:
                    p.cj_product_id = r["cj_product_id"]
                    p.price = r["price"] if r["price"] is not None else p.price
                    p.images = r["images"] or p.images
                    p.videos = r["videos"]
                    session.add(p)
                    session.commit()
            label = title or seed
            if r:
                resolved += 1
                await s.done(f"“{label[:40]}” → ✓ {len(r['images'])} images, "
                             f"${r['price'] if r['price'] is not None else '?'}")
            else:
                await s.done(f"“{label[:40]}” → CJ had nothing (skipped)")
        if work:
            await s.done(f"Resolved {resolved}/{len(work)} products against CJdropshipping")

        with Session(engine) as session:
            prods = session.exec(
                select(Product).where(Product.campaign_id == campaign_id)
                .order_by(Product.created_at.desc())).all()
            await emit(type="result", data={
                "campaign_id": campaign_id,
                "resolved": resolved,
                "products": [p.model_dump() for p in prods],
            })

    return StreamingResponse(sse(job), **_SSE)


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, session: Session = Depends(get_session)):
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="campaign not found")
    session.delete(campaign)
    session.commit()
    return {"deleted": campaign_id}


@router.get("/niches")
def list_niches(session: Session = Depends(get_session)):
    return session.exec(select(Niche).order_by(Niche.created_at.desc())).all()


@router.get("/products")
def list_products(campaign_id: int | None = None, session: Session = Depends(get_session)):
    stmt = select(Product)
    if campaign_id is not None:
        stmt = stmt.where(Product.campaign_id == campaign_id)
    return session.exec(stmt.order_by(Product.created_at.desc())).all()
