"""Reddit as a research source, behind one interface with THREE backends that
degrade in order. Callers get the same list[Thread] and never learn which ran.

1. PRAW read-only (best) -- when REDDIT_CLIENT_ID/SECRET are set. Structured
   signals, ToS-compliant, ~100 req/min. Register a "script" app: instant, no
   approval queue. OAuth goes to oauth.reddit.com, which isn't IP-blocked the
   way the public site is.
2. Public `.json` endpoints -- no key, but Reddit now 403-blocks these from many
   IPs (datacenter AND a lot of residential). When it works you get full signals.
3. Jina page-read (always-on floor) -- r.jina.ai READS Reddit listing/search
   pages server-side, so it works even when 1 and 2 are IP-blocked from this box.
   We parse the real thread links + titles from the markdown. Signals are thinner
   (score/comments unknown) but titles + subreddits are real. This is the path
   that keeps research alive here. (Keyless web *search* -- DDG, s.jina.ai -- is
   now gated/rate-limited, so we don't depend on it.)
"""
import asyncio
import logging
import re
import time
from dataclasses import asdict, dataclass

import httpx

from ..config import get_settings
from .web import active_reader, read_url

log = logging.getLogger(__name__)

# https://www.reddit.com/r/<sub>/comments/<id>/<slug>/
_THREAD_URL_RE = re.compile(r"reddit\.com/r/([^/]+)/comments/([^/]+)/([^/?#]+)")
# Markdown links Jina emits: [title](url)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)]+)\)")
_BOILER = ("welcome to r/", "read the rules", "megathread", "click here")


def _is_boiler(title: str) -> bool:
    t = title.lower()
    return any(b in t for b in _BOILER)


def _strip_sub(name: str) -> str:
    """Normalize 'r/Cozy', '/r/Cozy ', 'Cozy' -> 'Cozy' (models add the prefix)."""
    return name.strip().lstrip("/").removeprefix("r/").strip("/ ").strip()


@dataclass
class Thread:
    id: str
    title: str
    subreddit: str
    score: int
    upvote_ratio: float
    num_comments: int
    created_utc: float
    permalink: str
    url: str
    selftext: str

    def dict(self) -> dict:
        return asdict(self)


class _Throttle:
    """Serialize + space out requests on the keyless path (min interval)."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            gap = time.monotonic() - self._last
            if gap < self.min_interval:
                await asyncio.sleep(self.min_interval - gap)
            self._last = time.monotonic()


class RedditClient:
    def __init__(self, settings=None):
        self.s = settings or get_settings()
        self._throttle = _Throttle(1.1)
        self._praw = None  # lazily built sync PRAW instance

    @property
    def using_api(self) -> bool:
        return self.s.reddit_has_api

    # --- public interface -------------------------------------------------

    async def search(
        self,
        query: str,
        subreddit: str | None = None,
        sort: str = "top",
        time_filter: str = "year",
        limit: int = 25,
    ) -> list[Thread]:
        """Search threads by query (optionally scoped to one subreddit).

        Direct only (PRAW or public .json). Returns [] when blocked/empty -- the
        agent detects a thin haul and calls discover() ONCE, so we never fan Jina
        reads out per query.
        """
        subreddit = _strip_sub(subreddit) if subreddit else None
        if self.using_api:
            return await asyncio.to_thread(
                self._praw_search, query, subreddit, sort, time_filter, limit
            )
        return await self._json_search(query, subreddit, sort, time_filter, limit)

    async def top(
        self, subreddit: str, time_filter: str = "month", limit: int = 25
    ) -> list[Thread]:
        """Top threads in a subreddit -- the audience's current center of mass."""
        subreddit = _strip_sub(subreddit)
        if self.using_api:
            return await asyncio.to_thread(self._praw_top, subreddit, time_filter, limit)
        return await self._json_top(subreddit, time_filter, limit)

    async def check(self, sub: str = "pics") -> dict:
        """Diagnostic: does Reddit access actually work from here? Reports the
        PRAW/OAuth path (if creds present) AND the keyless floor, with real
        errors -- so after adding a script app you can tell instantly whether
        oauth.reddit.com is reachable from this box or also IP-blocked."""
        out: dict = {"has_creds": self.using_api, "reader": active_reader(),
                     "user_agent": self.s.reddit_user_agent}
        if self.using_api:
            try:
                hits = await asyncio.to_thread(self._praw_probe, sub)
                out["praw"] = {"ok": True, "count": len(hits),
                               "sample": hits[0].title if hits else None}
            except Exception as e:
                out["praw"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        try:
            d = await self.discover([sub], max_pages=1)
            out["keyless"] = {"ok": bool(d), "count": len(d)}
        except Exception as e:
            out["keyless"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return out

    def _praw_probe(self, sub: str) -> list[Thread]:
        """Like _praw_top but lets errors propagate (for check())."""
        subs = self._reddit().subreddit(sub).top(time_filter="week", limit=3)
        return [self._from_submission(s) for s in subs]

    # --- web-discovery backend (always-on floor) --------------------------

    async def discover(self, subreddits: list[str], max_pages: int = 5) -> list[Thread]:
        """Always-on floor: have Jina READ each subreddit's /top listing server-side
        (bypassing this box's IP block), then parse the real thread links + titles
        from the returned markdown.

        No search engine involved -- s.jina.ai/DuckDuckGo now gate or rate-limit
        keyless search, but r.jina.ai reading a public Reddit page still works. We
        read subreddit LISTINGS only (not /search, which renders empty via Jina)
        and keep ONLY threads whose subreddit we actually requested -- Reddit's
        global "popular" rail leaks into the markdown for JS-heavy or nonexistent
        subs, and that filter drops it. Engagement numbers aren't in the markdown,
        so they stay 0; titles + subreddits are real, which is what the model reads.
        """
        wanted = [_strip_sub(x) for x in subreddits if _strip_sub(x)][:max_pages]
        wanted_lc = {w.lower() for w in wanted}
        urls = [f"https://www.reddit.com/r/{sub}/top/?t=year" for sub in wanted]

        pages = await asyncio.gather(*(read_url(u, max_chars=8000) for u in urls))
        threads: dict[str, Thread] = {}
        for md in pages:
            for label, url in _MD_LINK_RE.findall(md or ""):
                m = _THREAD_URL_RE.search(url)
                if not m:
                    continue
                sub, tid, slug = m.group(1), m.group(2), m.group(3)
                if sub.lower() not in wanted_lc:  # drop popular-rail leakage
                    continue
                title = label.strip() or slug.replace("_", " ").strip().capitalize()
                if tid in threads or _is_boiler(title):
                    continue
                threads[tid] = Thread(
                    id=tid, title=title, subreddit=sub, score=0, upvote_ratio=0.0,
                    num_comments=0, created_utc=0.0,
                    permalink=f"https://www.reddit.com/r/{sub}/comments/{tid}/{slug}",
                    url=url, selftext="",
                )
        return list(threads.values())



def get_reddit() -> RedditClient:
    return RedditClient()
