"""Product image generation via edge-ai's image-gen node.

Thin client for the fleet's image-role box (see edge-ai/apps/image-gen):
POST a prompt, get PNG bytes back, save it under data/generated/ so the
static mount in main.py can serve it. Degrades the same way CJ does when
unconfigured -- callers check `has_image_gen` first and just don't show the
button.
"""
import logging
import os
import re
import time
import uuid

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

_GEN_DIR = os.path.join("data", "generated")
_TIMEOUT = 120.0  # cold-start-tolerant; a warm render is ~20-30s per the fleet's own numbers


def _prompt_for(title: str, description: str = "") -> str:
    base = f"product photo of {title.strip()}" if title.strip() else "product photo"
    if description.strip():
        base += f", {description.strip()[:200]}"
    return f"{base}, studio lit, plain background, e-commerce catalog style, sharp focus"


async def generate_product_image(title: str, description: str = "") -> dict | None:
    """Generate one product image. Returns {"url": "/generated/<file>.png", "prompt": ...}
    or None if image-gen isn't configured or the call fails."""
    settings = get_settings()
    if not settings.has_image_gen:
        return None

    prompt = _prompt_for(title, description)
    body = {"prompt": prompt}
    if settings.image_model:
        body["model"] = settings.image_model

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(f"{settings.image_base_url.rstrip('/')}/generate", json=body)
            r.raise_for_status()
            png = r.content
    except Exception as e:
        log.warning("image-gen failed for %r (%s)", title, e)
        return None

    os.makedirs(_GEN_DIR, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "product"
    filename = f"{slug}-{int(time.time())}-{uuid.uuid4().hex[:6]}.png"
    with open(os.path.join(_GEN_DIR, filename), "wb") as f:
        f.write(png)

    return {"url": f"/generated/{filename}", "prompt": prompt}
