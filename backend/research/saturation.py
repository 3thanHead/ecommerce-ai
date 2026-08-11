"""CJdropshipping access: an auth-token cache, the phrase-checked supply lookup,
and a health probe -- shared by whoever needs to know if CJ actually carries a
keyword. (The concept-level saturation shown on the board is a *different*,
already-real computation in prospect.py, from actual per-product listing
counts; this module used to also drive a drill-stage saturation/demand
re-measurement, but nothing ever read its output, so that's gone -- see
products.py for how a search seed gets resolved into a real CJ product.)

Everything here is local + private -- these are OUTBOUND calls from your
machine; nothing is exposed. The provider is optional and fail-soft:
unconfigured (or erroring) yields `None`/`configured: False` and callers
degrade accordingly.
"""
import asyncio
import json
import logging
import os
import re
import time

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


class _Throttle:
    """Space out calls to a rate-limited endpoint (min interval, shared lock)."""

    def __init__(self, interval: float):
        self.interval = interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self):
        async with self._lock:
            gap = time.monotonic() - self._last
            if gap < self.interval:
                await asyncio.sleep(self.interval - gap)
            self._last = time.monotonic()


# CJ's product/list is ~1 req/sec -- serialize queries so a concurrent batch
# (a prospecting scan) doesn't 429. They still fire back-to-back. 1.15s still
# drew occasional 429s on the larger sampled pages, so give it real headroom.
_cj_query_throttle = _Throttle(2.0)


# ----------------------------- CJdropshipping ----------------------------
# getAccessToken is rate-limited (~1 / 5 min), so the token is cached hard AND
# guarded by a lock: with many concurrent lookups (the leaderboard), exactly one
# fetches the token and the rest reuse it -- no thundering herd of 429s.
_cj_token = {"value": "", "exp": 0.0}
_cj_lock = asyncio.Lock()
_CJ_TOKEN_FILE = "data/.cj_token.json"  # in the mounted volume -> survives restarts


def _load_cj_token() -> None:
    try:
        with open(_CJ_TOKEN_FILE) as f:
            d = json.load(f)
        if d.get("exp", 0) > time.time():
            _cj_token.update(value=d["value"], exp=d["exp"])
    except Exception:
        pass


def _save_cj_token() -> None:
    try:
        os.makedirs(os.path.dirname(_CJ_TOKEN_FILE) or ".", exist_ok=True)
        with open(_CJ_TOKEN_FILE, "w") as f:
            json.dump({"value": _cj_token["value"], "exp": _cj_token["exp"]}, f)
    except Exception as e:
        log.debug("could not persist CJ token (%s)", e)


async def _cj_token_value(client: httpx.AsyncClient) -> str | None:
    s = get_settings()
    if _cj_token["exp"] <= time.time():
        _load_cj_token()  # try the persisted token before hitting the API
    if _cj_token["exp"] > time.time():
        return _cj_token["value"]
    async with _cj_lock:
        # Double-check: another coroutine may have fetched it while we waited.
        if _cj_token["exp"] > time.time():
            return _cj_token["value"]
        r = await client.post(
            "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken",
            json={"email": s.cj_email, "password": s.cj_api_key},
        )
        r.raise_for_status()
        data = r.json().get("data") or {}
        token = data.get("accessToken")
        if not token:
            return None
        # Token is valid ~15 days on CJ's side; cache 24h and persist so restarts
        # don't re-hit the ~1/5min token endpoint.
        _cj_token.update(value=token, exp=time.time() + 24 * 3600)
        _save_cj_token()
        return token


# Words that carry no product meaning -- CJ product names almost never contain
# them, so requiring them would reject every real match.
_STOPWORDS = {"custom", "customized", "personalized", "for", "with", "and",
              "the", "a", "of", "in", "on"}
_CJ_SAMPLE = 200  # products pulled per query to phrase-check (~200 KB, 1 request)


def _tokens(text: str) -> list[str]:
    """Alphanumeric tokens, crudely singularized so 'gloves' matches 'glove'."""
    return [t[:-1] if len(t) > 3 and t.endswith("s") else t
            for t in re.findall(r"[a-z0-9]+", text.lower())]


def _content_tokens(keyword: str) -> list[str]:
    return [t for t in _tokens(keyword) if t not in _STOPWORDS]


def _matches(name_tokens: set, want: list[str]) -> bool:
    """Does this product name describe the thing we searched for?

    CJ's product/list ORs the query words AND doesn't rank by relevance, so a
    strict all-words test has poor recall (verbose, reordered names -- "yoga mat"
    scored 1/200 against a catalog full of them). Relax to: the HEAD noun (the
    last content word -- the product type) plus at least one qualifier, or an
    exact all-words hit for 1-2 word seeds. Keeps precision (rejects the OR-junk)
    without demanding CJ's odd phrasing match ours verbatim."""
    if not want:
        return False
    if len(want) <= 2:
        return set(want) <= name_tokens
    head = want[-1]
    return head in name_tokens and any(w in name_tokens for w in want[:-1])


async def _cj_supply(keyword: str) -> dict | None:
    """Real supply for a keyword -- phrase-checked, because CJ's search ORs tokens.

    CJ's `productNameEn` filter matches ANY word and orders results badly, so
    its `total` is NOT a count of what you searched for:

        "coffee mug"                -> total 9,386, of 200 sampled only 6 are
                                       actually coffee mugs (the rest: patio
                                       furniture, coffee *tables*)
        "aquascaping co2 diffuser"  -> total 1,048, zero matches (aroma diffusers)
        "carabiner"                 -> 153, but "custom carabiner keychain" -> 6,829

    Adding words *raises* the total, so ranking on it doesn't just add noise --
    it actively punishes the specific seeds worth finding, and lands everything
    at 85-96 saturation. So: pull a page, count the names that actually describe
    the product (see _matches), and scale that rate onto the total. That rate
    correction also deflates niche-but-common-word seeds correctly -- "van life
    curtain" has a 4,108 total but a ~0.5% match rate, so ~20 real products, not
    thousands.

    CJ doesn't relevance-rank the page, so the rate is coarse; treat `count` as a
    magnitude, not a precise tally. Returns {total, sampled, matched, count}:
    `matched` is the direct observation used only to gate sourceability (did we
    see the product exist at all), `count` is the extrapolated supply that drives
    saturation.
    """
    s = get_settings()
    if not s.has_cj:
        return None
    try:
        async with httpx.AsyncClient(timeout=40.0) as client:
            token = await _cj_token_value(client)
            if not token:
                return None
            url = "https://developers.cjdropshipping.com/api2.0/v1/product/list"
            params = {"pageNum": 1, "pageSize": _CJ_SAMPLE, "productNameEn": keyword}
            headers = {"CJ-Access-Token": token}
            for attempt in range(2):  # throttle + one retry on a 429
                await _cj_query_throttle.wait()
                r = await client.get(url, headers=headers, params=params)
                if r.status_code == 429 and attempt == 0:
                    await asyncio.sleep(2.5)
                    continue
                r.raise_for_status()
                data = r.json().get("data") or {}
                total = int(data.get("total", 0))
                page = data.get("list") or []
                want = _content_tokens(keyword)
                if not want:  # nothing to check against -- take the total as-is
                    return {"total": total, "sampled": 0, "matched": 0, "count": total}
                matched = sum(
                    1 for p in page
                    if _matches(set(_tokens(p.get("productNameEn") or "")), want)
                )
                # Saw the whole result set -> matched IS the count, no estimating.
                count = (matched if total <= len(page)
                         else round(total * matched / len(page)) if page else 0)
                return {"total": total, "sampled": len(page),
                        "matched": matched, "count": count}
    except Exception as e:
        log.warning("CJ supply count failed for %r (%s)", keyword, e)
        return None
    return None


async def _cj_count(keyword: str) -> int | None:
    """Phrase-matched supply count only (health probe / simple callers)."""
    r = await _cj_supply(keyword)
    return None if r is None else r["count"]


# ----------------------------- top level ---------------------------------


async def health(sample: str = "desk mat") -> dict:
    """Is the supply provider (CJ) configured + a live count probe."""
    s = get_settings()
    row = {"name": "cjdropshipping", "configured": s.has_cj}
    if s.has_cj:
        count = await _cj_count(sample)
        row["ok"] = count is not None
        row["sample_count"] = count
    return {"sample_keyword": sample, "providers": [row]}
