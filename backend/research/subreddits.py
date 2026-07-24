"""Reddit grounding via free archives -- no key, no card -- degrading gracefully.

Division of labor (learned the hard way -- PullPush's global full-text search is
too noisy to DISCOVER subs from a keyword; it returns viral off-topic posts):

  the model   proposes which subreddits fit the niche (it's good at this)
  Arctic Shift PROFILES each -> subscribers + rules/description + submission type
               (reliable; this is what tells us "can I post products here")
  PullPush     scoped to each sub (subreddit=X, q=seed) -> REAL on-topic posts +
               engagement (score, comments) to ground product ideas

Every call is throttled (both archives rate-limit) and fail-soft: a dead source
just thins the result. source note reflects what actually answered.
"""
import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field

import httpx

from ..progress import Steps

log = logging.getLogger(__name__)

PULLPUSH = "https://api.pullpush.io/reddit/search/submission/"
ARCTIC = "https://arctic-shift.photon-reddit.com/api"


@dataclass
class Post:
    subreddit: str
    title: str
    score: int
    num_comments: int
    domain: str


@dataclass
class SubredditProfile:
    name: str
    subscribers: int = 0
    submission_type: str = ""  # any | link | self
    description: str = ""
    exists: bool = False       # confirmed via Arctic Shift
    posts: int = 0             # on-topic posts PullPush found here
    sample_titles: list = field(default_factory=list)

    def dict(self) -> dict:
        return asdict(self)


class _Throttle:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self):
        async with self._lock:
            gap = time.monotonic() - self._last
            if gap < self.min_interval:
                await asyncio.sleep(self.min_interval - gap)
            self._last = time.monotonic()


_pp_throttle = _Throttle(1.3)
_as_throttle = _Throttle(0.6)


async def _pullpush(client, q: str, subreddit: str | None = None, size: int = 40) -> list[dict]:
    await _pp_throttle.wait()
    params = {"q": q, "size": size, "sort_type": "score", "sort": "desc"}
    if subreddit:
        params["subreddit"] = subreddit
    for _ in range(2):
        try:
            r = await client.get(PULLPUSH, params=params)
            if r.status_code == 429:
                await asyncio.sleep(2.5)
                continue
            r.raise_for_status()
            return r.json().get("data", [])
        except Exception as e:
            log.warning("pullpush %s/%s failed (%s)", subreddit, q, e)
            return []
    return []


async def _arctic_profile(client, name: str) -> dict:
    await _as_throttle.wait()
    try:
        r = await client.get(f"{ARCTIC}/subreddits/search", params={"subreddit": name, "limit": 1})
        r.raise_for_status()
        data = r.json().get("data") or []
        # Arctic prefix-matches; keep only an exact (case-insensitive) hit.
        for d in data:
            if (d.get("display_name", "") or "").lower() == name.lower():
                return d
        return data[0] if data and len(data) == 1 else {}
    except Exception as e:
        log.warning("arctic '%s' failed (%s)", name, e)
        return {}


async def health() -> dict:
    """Reachability of the two free archives (for the diagnostic endpoint)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        pp = await _pullpush(client, "desk", subreddit="battlestations", size=1)
        meta = await _arctic_profile(client, "pics")
    return {
        "pullpush": {"ok": bool(pp)},
        "arctic_shift": {"ok": bool(meta), "sample_subscribers": meta.get("subscribers")},
    }


async def ground(
    phrases: list[str], model_subreddits: list[str] | None = None, top: int = 6, emit=None
) -> dict:
    """Profile + ground the model's suggested subreddits. Returns
    {subreddits:[profile...], posts:[...], source}."""
    s = Steps(emit) if emit else None
    names = list(dict.fromkeys([n.lstrip("r/").strip() for n in (model_subreddits or []) if n]))[:top]
    seed = phrases[0] if phrases else ""
    profiles = {n: SubredditProfile(name=n) for n in names}

    if not names:
        return {"subreddits": [], "posts": [], "source": "model-only"}

    if s:
        await s.running(f"Profiling {len(names)} subreddits via Arctic Shift (subscribers + rules)")
    async with httpx.AsyncClient(timeout=25.0) as client:
        # Arctic Shift profiles (reliable) — subscribers + rules + submission type.
        for n in names:
            meta = await _arctic_profile(client, n)
            if meta:
                p = profiles[n]
                p.exists = True
                p.subscribers = int(meta.get("subscribers", 0) or 0)
                p.submission_type = meta.get("submission_type", "") or ""
                desc = (meta.get("public_description") or "").strip()
                rules = (meta.get("submit_text") or "").strip()
                p.description = (desc + ("\n" + rules if rules else ""))[:600]
        if s:
            got = sum(1 for p in profiles.values() if p.exists)
            await s.done(f"Profiled subreddits → {got}/{len(names)} confirmed on Arctic Shift")
            await s.running(f"Pulling real posts (PullPush) from the top subreddits about “{seed}”")

        # PullPush scoped to each real sub — real, on-topic posts + engagement.
        posts: list[Post] = []
        for n in [nm for nm in names if profiles[nm].exists][:4] or names[:4]:
            for row in await _pullpush(client, seed, subreddit=n):
                post = Post(n, row.get("title", "") or "", int(row.get("score", 0) or 0),
                            int(row.get("num_comments", 0) or 0), row.get("domain", "") or "")
                if post.title:
                    posts.append(post)
                    prof = profiles[n]
                    prof.posts += 1
                    if len(prof.sample_titles) < 3:
                        prof.sample_titles.append(post.title)
    if s:
        await s.done(f"Pulled {len(posts)} real posts across the subreddits")

    ranked = sorted(profiles.values(), key=lambda p: (p.subscribers, p.posts), reverse=True)
    has_posts = bool(posts)
    has_profiles = any(p.exists for p in ranked)
    source = "pullpush+arctic" if has_posts else ("arctic-only" if has_profiles else "model-only")
    return {
        "subreddits": [p.dict() for p in ranked],
        "posts": [asdict(p) for p in sorted(posts, key=lambda x: x.score, reverse=True)[:25]],
        "source": source,
    }
