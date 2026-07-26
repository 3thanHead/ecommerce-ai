"""Storefront + product + niche management -- what the admin UI reads and writes.

Storefronts are the stores the agent's categories become; products (Feature 2)
and niches hang off them. Deliberately plain CRUD; the interesting logic lives in
the research agent, not here.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import engine, get_session
from ..models import Niche, Product, Storefront, StorePage
from ..progress import Steps, sse
from ..research.products import ground_product, hydrate
from ..research.store_gen import generate_store

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["storefronts"])

_SSE = {"media_type": "text/event-stream",
        "headers": {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}}


def _seed_of(p: Product) -> str:
    """The CJ search seed a candidate carries -- stored on `source` as
    '<kind>:<seed>' by the promote/automate build; fall back to the title."""
    src = p.source or ""
    if ":" in src:
        return src.split(":", 1)[1].strip() or p.title
    return p.title


class StorefrontIn(BaseModel):
    name: str
    category: str = ""
    audience: str = ""
    description: str = ""
    slug: str | None = None


def _slugify(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "store"


@router.get("/storefronts")
def list_storefronts(session: Session = Depends(get_session)):
    stores = session.exec(select(Storefront).order_by(Storefront.created_at.desc())).all()
    out = []
    for s in stores:
        n_products = len(session.exec(select(Product).where(Product.storefront_id == s.id)).all())
        out.append({**s.model_dump(), "product_count": n_products})
    return out


@router.post("/storefronts")
def create_storefront(body: StorefrontIn, session: Session = Depends(get_session)):
    slug = _slugify(body.slug or body.name)
    if session.exec(select(Storefront).where(Storefront.slug == slug)).first():
        raise HTTPException(status_code=409, detail=f"slug '{slug}' already exists")
    store = Storefront(
        slug=slug,
        name=body.name,
        category=body.category,
        audience=body.audience,
        description=body.description,
    )
    session.add(store)
    session.commit()
    session.refresh(store)
    return store


@router.get("/storefronts/{store_id}")
def get_storefront(store_id: int, session: Session = Depends(get_session)):
    store = session.get(Storefront, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="storefront not found")
    products = session.exec(select(Product).where(Product.storefront_id == store_id)).all()
    niches = session.exec(select(Niche).where(Niche.storefront_id == store_id)).all()
    return {**store.model_dump(), "products": products, "niches": niches}


@router.post("/storefronts/{store_id}/resolve/stream")
async def resolve_products(store_id: int):
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
            store = session.get(Storefront, store_id)
            if not store:
                await emit(type="error", message="storefront not found")
                return
            store_audience = store.audience
            products = session.exec(
                select(Product).where(Product.storefront_id == store_id)).all()
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
                 else await ground_product(seed, idea=title, audience=store_audience))
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
                select(Product).where(Product.storefront_id == store_id)
                .order_by(Product.created_at.desc())).all()
            await emit(type="result", data={
                "storefront_id": store_id,
                "resolved": resolved,
                "products": [p.model_dump() for p in prods],
            })

    return StreamingResponse(sse(job), **_SSE)


@router.post("/storefronts/{store_id}/generate/stream")
async def generate_storefront(store_id: int, req: dict | None = None):
    """Generate the customer-facing store: branding (tagline/hero/accent) + a
    sales pitch per product, streamed. Persists a StorePage and writes each pitch
    onto Product.description. View the result at /store/{slug}."""
    model = (req or {}).get("model")

    async def job(emit):
        s = Steps(emit)
        with Session(engine) as session:
            store = session.get(Storefront, store_id)
            if not store:
                await emit(type="error", message="storefront not found")
                return
            products = session.exec(
                select(Product).where(Product.storefront_id == store_id)).all()
            store_d = store.model_dump()
            prod_d = [{"id": p.id, "title": p.title, "price": p.price} for p in products]
            slug = store.slug

        gen = await generate_store(store_d, prod_d, model, emit=emit)

        await s.running("Saving store copy")
        with Session(engine) as session:
            page = session.exec(
                select(StorePage).where(StorePage.storefront_id == store_id)).first()
            if not page:
                page = StorePage(storefront_id=store_id)
            page.tagline, page.hero, page.accent = gen["tagline"], gen["hero"], gen["accent"]
            session.add(page)
            for p in session.exec(select(Product).where(Product.storefront_id == store_id)).all():
                if p.id in gen["pitches"]:
                    p.description = gen["pitches"][p.id]
                    session.add(p)
            store = session.get(Storefront, store_id)
            if store.status == "draft":
                store.status = "active"
                session.add(store)
            session.commit()
        await s.done(f"Store ready — view it at /store/{slug}")
        await emit(type="result", data={
            "storefront_id": store_id, "slug": slug,
            "tagline": gen["tagline"], "hero": gen["hero"], "accent": gen["accent"],
            "url": f"/store/{slug}",
        })

    return StreamingResponse(sse(job), **_SSE)


@router.delete("/storefronts/{store_id}")
def delete_storefront(store_id: int, session: Session = Depends(get_session)):
    store = session.get(Storefront, store_id)
    if not store:
        raise HTTPException(status_code=404, detail="storefront not found")
    session.delete(store)
    session.commit()
    return {"deleted": store_id}


@router.get("/niches")
def list_niches(session: Session = Depends(get_session)):
    return session.exec(select(Niche).order_by(Niche.created_at.desc())).all()


@router.get("/products")
def list_products(storefront_id: int | None = None, session: Session = Depends(get_session)):
    stmt = select(Product)
    if storefront_id is not None:
        stmt = stmt.where(Product.storefront_id == storefront_id)
    return session.exec(stmt.order_by(Product.created_at.desc())).all()
