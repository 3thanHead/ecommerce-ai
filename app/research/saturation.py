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
import base64
import logging
import math
import time

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

# Count that reads as "fully saturated" on the log scale (tunable).
_SATURATION_CEILING = 50_000


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
# getAccessToken is rate-limited (~1 / 5 min), so the token is cached hard.
_cj_token = {"value": "", "exp": 0.0}


async def _cj_token_value(client: httpx.AsyncClient) -> str | None:
    s = get_settings()
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
    _cj_token["value"] = token
    _cj_token["exp"] = time.time() + 12 * 3600  # token lives days; refresh well within
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
            r = await client.get(
                "https://developers.cjdropshipping.com/api2.0/v1/product/list",
                headers={"CJ-Access-Token": token},
                params={"pageNum": 1, "pageSize": 1, "productNameEn": keyword},
            )
            r.raise_for_status()
            data = r.json().get("data") or {}
            return int(data.get("total", 0))
    except Exception as e:
        log.warning("CJ supply count failed for %r (%s)", keyword, e)
        return None


# ----------------------------- top level ---------------------------------

_PROVIDERS = [("cjdropshipping", _cj_count), ("ebay", _ebay_count)]


async def measure(keyword: str, keywords: list[dict]) -> dict:
    """Measured saturation for a keyword. Returns:
      {measured, saturation|None, demand, supply:{provider:count}, method}
    measured=False (and the caller keeps the model's estimate) when no provider
    is configured or all fail."""
    demand = _demand_score(keywords)
    supply: dict[str, int] = {}
    for name, fn in _PROVIDERS:
        count = await fn(keyword)
        if count is not None:
            supply[name] = count

    if not supply:
        return {"measured": False, "saturation": None, "demand": demand,
                "supply": {}, "method": "estimated"}

    # Average the per-provider supply scores (each already log-scaled 0-100).
    scores = [_supply_score(c) for c in supply.values()]
    saturation = round(sum(scores) / len(scores))
    return {"measured": True, "saturation": saturation, "demand": demand,
            "supply": supply, "method": "measured"}
