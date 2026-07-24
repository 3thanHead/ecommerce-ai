"""Diagnostics — reachability of the free external sources the research agent
leans on. These are NOT domain APIs: the actual clients live in backend/research/
(reddit.py for the PullPush/Arctic Shift archives, saturation.py for the CJ/eBay
supply counts). The research flow uses them internally via /api/opportunities;
these routes just answer "is the source up?" for `make check-reddit` /
`make check-saturation`.
"""
from fastapi import APIRouter

from ..research import reddit
from ..research import saturation as sat

router = APIRouter(prefix="/api", tags=["diagnostics"])


@router.get("/reddit/health")
async def reddit_health():
    """Are the Reddit archives (PullPush, Arctic Shift) reachable right now?"""
    return await reddit.health()


@router.get("/saturation/health")
async def saturation_health():
    """Which supply providers (CJ/eBay) are configured + a live count probe."""
    return await sat.health()
