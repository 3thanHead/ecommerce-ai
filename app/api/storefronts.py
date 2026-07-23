"""Storefront + product + niche management -- what the admin UI reads and writes.

Storefronts are the stores the agent's categories become; products (Feature 2)
and niches hang off them. Deliberately plain CRUD; the interesting logic lives in
the research agent, not here.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import Niche, Product, Storefront

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["storefronts"])


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
