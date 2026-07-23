"""Grounding diagnostic -- are the free Reddit archives reachable right now?
`make check-reddit` hits this. Both are community-run and flaky, so this tells
you whether a thin drill was the archives being down vs. something else."""
from fastapi import APIRouter

from ..research import subreddits as sr

router = APIRouter(prefix="/api/reddit", tags=["reddit"])


@router.get("/health")
async def reddit_health():
    return await sr.health()
