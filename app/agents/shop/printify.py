"""Printify print-on-demand -- plain code against their REST API.

Printify owns fulfillment and shipping for POD goods, so "publish to
Printify" is the whole back half of the physical-product story: we create a
product draft in the shop; printing/shipping happen on their side per order.

A real Printify product needs a DESIGN IMAGE plus a blueprint (garment/mug/
poster), a print provider, and variants. Design generation isn't in the
pipeline yet, so create_draft() requires listing["image_url"]; without one it
returns {"skipped": ...} and the pipeline records that gap. Blueprint and
provider come from env with catalog defaults so a starting product works
without hand-tuning.

Env: PRINTIFY_API_KEY, PRINTIFY_SHOP_ID; optional PRINTIFY_BLUEPRINT_ID /
PRINTIFY_PRINT_PROVIDER_ID (defaults: 6 = Unisex Gildan 5000 tee, provider
99 = Printify Choice).
"""
import os

import httpx

API = "https://api.printify.com/v1"


def configured() -> bool:
    return bool(os.environ.get("PRINTIFY_API_KEY")
                and os.environ.get("PRINTIFY_SHOP_ID"))


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['PRINTIFY_API_KEY']}"}


async def _req(client: httpx.AsyncClient, method: str, path: str,
               json: dict | None = None) -> dict:
    r = await client.request(method, f"{API}{path}", json=json,
                             headers=_headers())
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
    return r.json()


async def create_draft(listing: dict, sku: str) -> dict:
    """Upload the design image and create an unpublished product draft.
    Returns {"printify_product_id", ...} | {"skipped": ...} | {"error": ...}."""
    if not configured():
        return {"skipped": "printify not configured "
                           "(set PRINTIFY_API_KEY + PRINTIFY_SHOP_ID)"}
    image_url = listing.get("image_url")
    if not image_url:
        return {"skipped": "no design image yet -- add image_url to the "
                           "product, then `publish <sku>` again"}
    shop = os.environ["PRINTIFY_SHOP_ID"]
    blueprint = int(os.environ.get("PRINTIFY_BLUEPRINT_ID", "6"))
    provider = int(os.environ.get("PRINTIFY_PRINT_PROVIDER_ID", "99"))
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            art = await _req(c, "POST", "/uploads/images.json",
                             {"file_name": f"{sku}.png", "url": image_url})
            variants = await _req(
                c, "GET",
                f"/catalog/blueprints/{blueprint}/print_providers/{provider}"
                "/variants.json")
            ids = [v["id"] for v in variants.get("variants", [])[:6]]
            if not ids:
                return {"error": "printify: blueprint/provider has no variants"}
            price_cents = max(1, int(round(float(listing.get("price_usd") or 25) * 100)))
            product = await _req(c, "POST", f"/shops/{shop}/products.json", {
                "title": listing["title"],
                "description": listing.get("description", ""),
                "tags": listing.get("tags", [])[:10],
                "blueprint_id": blueprint,
                "print_provider_id": provider,
                "variants": [{"id": i, "price": price_cents, "is_enabled": True}
                             for i in ids],
                "print_areas": [{
                    "variant_ids": ids,
                    "placeholders": [{"position": "front", "images": [{
                        "id": art["id"], "x": 0.5, "y": 0.5,
                        "scale": 1.0, "angle": 0}]}],
                }],
            })
        return {"printify_product_id": product["id"],
                "variants": len(ids), "status": "draft"}
    except (RuntimeError, httpx.HTTPError) as e:
        return {"error": f"printify: {e}"}
