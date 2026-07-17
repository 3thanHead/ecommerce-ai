"""Stripe payment handling -- plain code, no LLM anywhere near money.

One call: product_payment_link(listing) creates Product -> Price ->
Payment Link and returns the hosted checkout URL. Stripe's API is
form-encoded REST, so httpx is all we need.

Env: STRIPE_API_KEY (use an sk_test_ key until the shop is real).
Unconfigured or failing -> {"error": ...} so the pipeline records the gap
and moves on instead of dying.
"""
import os

import httpx

API = "https://api.stripe.com/v1"


def configured() -> bool:
    return bool(os.environ.get("STRIPE_API_KEY"))


async def _post(client: httpx.AsyncClient, path: str, data: dict) -> dict:
    r = await client.post(f"{API}{path}", data=data,
                          auth=(os.environ["STRIPE_API_KEY"], ""))
    body = r.json()
    if r.status_code >= 400:
        raise RuntimeError(body.get("error", {}).get("message", r.text[:200]))
    return body


async def product_payment_link(title: str, price_usd: float, sku: str) -> dict:
    """Create a Stripe Product + Price + Payment Link for one listing.
    Returns {"payment_url", "stripe_product", "stripe_price"} or {"error"}."""
    if not configured():
        return {"error": "stripe not configured (set STRIPE_API_KEY)"}
    cents = max(50, int(round(price_usd * 100)))  # Stripe minimum is $0.50
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            product = await _post(c, "/products",
                                  {"name": title, "metadata[sku]": sku})
            price = await _post(c, "/prices",
                                {"product": product["id"],
                                 "unit_amount": cents, "currency": "usd"})
            link = await _post(c, "/payment_links",
                               {"line_items[0][price]": price["id"],
                                "line_items[0][quantity]": 1,
                                "metadata[sku]": sku})
        return {"payment_url": link["url"], "stripe_product": product["id"],
                "stripe_price": price["id"]}
    except (RuntimeError, httpx.HTTPError) as e:
        return {"error": f"stripe: {e}"}
