"""Saturation supply-source diagnostic. `make check-saturation` hits this to
confirm CJ/eBay auth works and what a sample keyword's supply count looks like."""
from fastapi import APIRouter

from ..research import saturation as sat

router = APIRouter(prefix="/api/saturation", tags=["saturation"])


@router.get("/health")
async def saturation_health():
    return await sat.health()
