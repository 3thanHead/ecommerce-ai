"""Reddit access diagnostic. After adding a script app's creds to .env, hit this
(or `make check-reddit`) to confirm the OAuth/PRAW path actually reaches Reddit
from this box -- and whether the keyless floor is currently blocked."""
from fastapi import APIRouter

from ..research import get_reddit

router = APIRouter(prefix="/api/reddit", tags=["reddit"])


@router.get("/health")
async def reddit_health():
    return await get_reddit().check()
