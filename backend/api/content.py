"""The staging/review queue: generated content (image/caption today, video on
the roadmap) waits here for a human to approve or reject before anything goes
near a social post. Nothing here posts anywhere -- Phase 5 (Postiz) wires an
approval to an actual post.

  POST   /campaigns/{id}/products/{id}/content/image     generate + stage one image
  POST   /campaigns/{id}/products/{id}/content/caption    generate + stage one caption
  GET    /campaigns/{id}/content                          everything staged for a campaign
  POST   /content/{asset_id}/approve                      approve (images also land on Product.images)
  POST   /content/{asset_id}/reject                        reject
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import Campaign, ContentAsset, Product
from ..research.captions import generate_caption
from ..research.images import generate_product_image

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["content"])


class GenerateRequest(BaseModel):
    model: str | None = None


def _get_product(session: Session, campaign_id: int, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if not product or product.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="product not found")
    return product


@router.post("/campaigns/{campaign_id}/products/{product_id}/content/image")
async def generate_image_asset(campaign_id: int, product_id: int,
                                session: Session = Depends(get_session)):
    product = _get_product(session, campaign_id, product_id)
    result = await generate_product_image(product.title, product.description)
    if result is None:
        raise HTTPException(
            status_code=501,
            detail="image generation isn't configured or the call failed — "
                    "set IMAGE_BASE_URL to the fleet's image-gen node (see .env.example)",
        )
    asset = ContentAsset(
        campaign_id=campaign_id, product_id=product_id, kind="image",
        prompt=result["prompt"], asset_url=result["url"],
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.post("/campaigns/{campaign_id}/products/{product_id}/content/caption")
async def generate_caption_asset(campaign_id: int, product_id: int, req: GenerateRequest,
                                  session: Session = Depends(get_session)):
    product = _get_product(session, campaign_id, product_id)
    campaign = session.get(Campaign, campaign_id)
    try:
        text = await generate_caption(product.title, product.description,
                                       campaign.audience if campaign else "", req.model)
    except Exception as e:
        log.warning("caption generation failed for product %s (%s)", product_id, e)
        raise HTTPException(status_code=502, detail=f"caption generation failed: {e}")
    asset = ContentAsset(
        campaign_id=campaign_id, product_id=product_id, kind="caption",
        prompt="social caption", text=text,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


@router.get("/campaigns/{campaign_id}/content")
def list_content(campaign_id: int, session: Session = Depends(get_session)):
    return session.exec(
        select(ContentAsset)
        .where(ContentAsset.campaign_id == campaign_id)
        .order_by(ContentAsset.created_at.desc())
    ).all()


@router.post("/content/{asset_id}/approve")
def approve_content(asset_id: int, session: Session = Depends(get_session)):
    asset = session.get(ContentAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="content asset not found")
    asset.status = "approved"
    session.add(asset)
    # An approved image is now an official product photo, not just a draft.
    if asset.kind == "image" and asset.asset_url:
        product = session.get(Product, asset.product_id)
        if product and asset.asset_url not in (product.images or []):
            product.images = [*(product.images or []), asset.asset_url]
            session.add(product)
    session.commit()
    session.refresh(asset)
    return asset


@router.post("/content/{asset_id}/reject")
def reject_content(asset_id: int, session: Session = Depends(get_session)):
    asset = session.get(ContentAsset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="content asset not found")
    asset.status = "rejected"
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset
