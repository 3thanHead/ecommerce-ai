"""Diagnostics — reachability of the free external sources the research agent
leans on. These are NOT domain APIs: the actual clients live in backend/research/
(reddit.py for the PullPush/Arctic Shift archives, saturation.py for the CJ
supply counts, websearch.py for the local SearXNG instance). The research flow
uses them internally via /api/opportunities; these routes just answer "is the
source up?" for `make check-reddit` / `make check-saturation`.
"""
from fastapi import APIRouter

from ..research import reddit
from ..research import saturation as sat
from ..research import websearch

router = APIRouter(prefix="/api", tags=["diagnostics"])


@router.get("/reddit/health")
async def reddit_health():
    """Are the Reddit archives (PullPush, Arctic Shift) reachable right now?"""
    return await reddit.health()


@router.get("/saturation/health")
async def saturation_health():
    """Is the CJ supply provider configured + a live count probe."""
    return await sat.health()


@router.get("/websearch/health")
async def websearch_health():
    """Is the local SearXNG instance configured + a live query probe."""
    return await websearch.health()
