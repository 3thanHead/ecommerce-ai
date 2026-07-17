"""Where listings are allowed to go.

POLICY (enforced here, in code, not by the model): products are AI-generated,
so they are published ONLY to platforms that explicitly permit AI-created
content -- our own storefront (trivially safe) and Printify print-on-demand.
Marketplaces that ban or restrict AI work (or hand-made-only venues like Etsy
handmade) must never be added to this registry.

A platform entry is an async publish(product) -> dict describing what
happened. publish_all() fans a product out to every platform that fits its
kind ("digital" -> storefront; "pod" -> storefront + Printify) and returns
the per-platform results; the caller stores them on the product record.
"""
import os

from . import printify


def storefront_url(path: str = "") -> str:
    """Public base of our own shop/blog -- the ngrok domain once there is
    one. BLOG_BASE_URL is injected by `edge deploy` from the root .env
    (no addresses in git), same as IOT_DEVICE_URL."""
    base = os.environ.get("BLOG_BASE_URL") or "http://localhost:8810"
    return f"{base.rstrip('/')}{path}"


async def _publish_storefront(product: dict) -> dict:
    """Our own site: the product page goes live the moment the record is
    stored (api/blog.py renders it), so 'publishing' is just the URL."""
    return {"platform": "storefront", "ok": True,
            "url": storefront_url(f"/shop/{product['sku']}")}


async def _publish_printify(product: dict) -> dict:
    result = await printify.create_draft(product, product["sku"])
    return {"platform": "printify", "ok": "error" not in result, **result}


# kind -> the platforms that carry it. Extend by adding an entry -- and only
# after checking the venue allows AI-generated products.
PLATFORMS = {
    "digital": [_publish_storefront],
    "pod": [_publish_storefront, _publish_printify],
}


async def publish_all(product: dict) -> list[dict]:
    kind = product.get("kind", "digital")
    return [await p(product) for p in PLATFORMS.get(kind, PLATFORMS["digital"])]
