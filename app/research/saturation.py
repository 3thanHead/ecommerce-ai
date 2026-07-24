"""Measured saturation -- supply counts vs. demand, instead of the model's guess.

Saturation is a supply-crowdedness signal: how many sellers already compete for a
keyword. We read that from real APIs (a "supply provider") and log-scale it 0-100.
Demand is the free keyword-breadth signal we already have. The opportunity is high
demand + low saturation.

Providers are optional and fail-soft. With none configured (or all erroring) the
result is `measured: False` and callers keep the model's estimate -- so the whole
thing degrades to exactly today's behavior until a free key lands.

  CJdropshipping  # of dropship products for the keyword -- the most on-point
                  supply signal (and the Feature 2 catalog). Free account.
  eBay Browse     # of listings (`total`) for the keyword -- broad market. Free.
"""
import asyncio
import base64
import json
import logging
import math
import os
import time

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

# Count that reads as "fully saturated" on the log scale (tunable).
_SATURATION_CEILING = 50_000


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
# (the leaderboard) doesn't 429. They still fire back-to-back, ~1/sec.
_cj_query_throttle = _Throttle(1.15)


def _supply_score(count: int) -> int:
    if count <= 0:
        return 0
    score = math.log10(count + 1) / math.log10(_SATURATION_CEILING) * 100
    return max(0, min(100, round(score)))


def _demand_score(keywords: list[dict]) -> int:
    # Breadth proxy: how many long-tail phrases the seed autocompletes into.
    return max(0, min(100, len(keywords) * 5))


# ----------------------------- eBay --------------------------------------

_ebay_token = {"value": "", "exp": 0.0}


async def _ebay_count(keyword: str) -> int | None:
    s = get_settings()
    if not s.has_ebay:
        return None
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            if _ebay_token["exp"] < time.time():
                basic = base64.b64encode(
                    f"{s.ebay_client_id}:{s.ebay_client_secret}".encode()
                ).decode()
                r = await client.post(
                    "https://api.ebay.com/identity/v1/oauth2/token",
                    headers={"Authorization": f"Basic {basic}",
                             "Content-Type": "application/x-www-form-urlencoded"},
                    data={"grant_type": "client_credentials",
                          "scope": "https://api.ebay.com/oauth/api_scope"},
                )
                r.raise_for_status()
                tok = r.json()
                _ebay_token["value"] = tok["access_token"]
                _ebay_token["exp"] = time.time() + tok.get("expires_in", 7200) - 60
            r = await client.get(
                "https://api.ebay.com/buy/browse/v1/item_summary/search",
                headers={"Authorization": f"Bearer {_ebay_token['value']}",
                         "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
                params={"q": keyword, "limit": 1},
            )
            r.raise_for_status()
            return int(r.json().get("total", 0))
    except Exception as e:
        log.warning("eBay supply count failed for %r (%s)", keyword, e)
        return None


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


async def _cj_count(keyword: str) -> int | None:
    s = get_settings()
    if not s.has_cj:
        return None
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            token = await _cj_token_value(client)
            if not token:
                return None
            url = "https://developers.cjdropshipping.com/api2.0/v1/product/list"
            params = {"pageNum": 1, "pageSize": 1, "productNameEn": keyword}
            headers = {"CJ-Access-Token": token}
            for attempt in range(2):  # throttle + one retry on a 429
                await _cj_query_throttle.wait()
                r = await client.get(url, headers=headers, params=params)
                if r.status_code == 429 and attempt == 0:
                    await asyncio.sleep(1.3)
                    continue
                r.raise_for_status()
                data = r.json().get("data") or {}
                return int(data.get("total", 0))
    except Exception as e:
        log.warning("CJ supply count failed for %r (%s)", keyword, e)
        return None
    return None


# ----------------------------- top level ---------------------------------

_PROVIDERS = [("cjdropshipping", _cj_count), ("ebay", _ebay_count)]


async def health(sample: str = "desk mat") -> dict:
    """Which supply providers are configured + a live count probe for each."""
    s = get_settings()
    out = []
    for name, fn, configured in (
        ("cjdropshipping", _cj_count, s.has_cj),
        ("ebay", _ebay_count, s.has_ebay),
    ):
        row = {"name": name, "configured": configured}
        if configured:
            count = await fn(sample)
            row["ok"] = count is not None
            row["sample_count"] = count
        out.append(row)
    return {"sample_keyword": sample, "providers": out}


async def _supply_only(keyword: str) -> dict:
    """Supply-based saturation for one keyword (no demand side). Building block."""
    supply: dict[str, int] = {}
    for name, fn in _PROVIDERS:
        count = await fn(keyword)
        if count is not None:
            supply[name] = count
    if not supply:
        return {"measured": False, "saturation": None, "supply": {}, "method": "estimated"}
    scores = [_supply_score(c) for c in supply.values()]
    return {"measured": True, "saturation": round(sum(scores) / len(scores)),
            "supply": supply, "method": "measured"}


async def measure(keyword: str, keywords: list[dict]) -> dict:
    """Measured saturation for a keyword (drill). Adds the demand side.
    measured=False -> caller keeps the model's estimate."""
    out = await _supply_only(keyword)
    out["demand"] = _demand_score(keywords)
    return out


async def measure_batch(keywords: list[str], concurrency: int = 4) -> list[dict]:
    """Supply-based saturation for many keywords at once (the leaderboard).

    Runs the per-keyword lookups CONCURRENTLY behind a semaphore -- the whole
    batch finishes in about the time of one, without tripping CJ's rate limit.
    Each entry degrades independently to measured=False."""
    sem = asyncio.Semaphore(concurrency)

    async def one(kw: str) -> dict:
        async with sem:
            return await _supply_only(kw)

    return await asyncio.gather(*(one(kw) for kw in keywords))
