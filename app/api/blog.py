"""/shop + /blog + /store/export -- the live LAN preview of the storefront.

Pages render through the single template (app/agents/shop/render.py) from the
venture's brand + catalog. This is the on-LAN preview while you work; the
PUBLIC site is the static build (site/build.py) of /store/export, deployed to
S3/CloudFront. This module only assembles context; the markup lives in
render.py, which the static builder uses too, so preview == published.

    GET /shop, /shop/{sku}, /blog, /blog/{slug}   the live preview
    GET /store/export                             the content snapshot
"""
import markdown as md
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from .. import db
from ..agents.shop import render, venture

router = APIRouter()


async def _ctx() -> dict:
    v = await venture.get()
    brand = venture.brand_of(v) if v else \
        {"name": "The Shop", "tagline": "", "accent": "#2563eb"}
    products = await db.find(venture.PRODUCTS, order_by="created_at",
                             desc=True, limit=50)
    posts = await db.find(venture.POSTS, order_by="published_at",
                          desc=True, limit=50)
    return {"brand": brand, "products": products, "posts": posts,
            "urls": {"shop": "/shop", "blog": "/blog"}}


def _link(items: list[dict], base: str, key: str) -> list[dict]:
    return [{**i, "_href": f"{base}/{i.get(key, '')}"} for i in items]


def _html(page: str, ctx: dict) -> HTMLResponse:
    return HTMLResponse(render.render(page, ctx))


def _md(text: str) -> str:
    return md.markdown(text or "")


@router.get("/shop", response_class=HTMLResponse)
async def shop_index():
    ctx = await _ctx()
    ctx["products"] = _link(ctx["products"], "/shop", "sku")
    return _html("shop", ctx)


@router.get("/shop/{sku}", response_class=HTMLResponse)
async def shop_product(sku: str):
    ctx = await _ctx()
    p = (await db.find(venture.PRODUCTS, where={"sku": sku}, limit=1) or [None])[0]
    if p is None:
        return HTMLResponse("<h1>No such product</h1>", status_code=404)
    ctx["product"] = {**p, "_href": f"/shop/{sku}",
                      **({"post_slug": f"/blog/{p['post_slug']}"} if p.get("post_slug") else {})}
    return _html("product", ctx)


@router.get("/blog", response_class=HTMLResponse)
async def blog_index():
    ctx = await _ctx()
    ctx["posts"] = _link(ctx["posts"], "/blog", "slug")
    return _html("blog", ctx)


@router.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post(slug: str):
    ctx = await _ctx()
    post = (await db.find(venture.POSTS, where={"slug": slug}, limit=1) or [None])[0]
    if post is None:
        return HTMLResponse("<h1>No such post</h1>", status_code=404)
    ctx["post"] = {**post, "body_html": _md(post.get("body_markdown"))}
    return _html("post", ctx)


@router.get("/store/export")
async def store_export():
    """The content snapshot the static builder (site/build.py) renders and
    ships. Brand, catalog, posts, the assembly stage's pages, and the
    marketing plan -- this box only generates content."""
    v = await venture.get()
    stages = v["stages"] if v else {}
    return JSONResponse({
        "brand": venture.brand_of(v) if v else {"name": "The Shop", "tagline": ""},
        "seed": v.get("seed") if v else None,
        "products": await db.find(venture.PRODUCTS, order_by="created_at",
                                  desc=True, limit=100),
        "posts": await db.find(venture.POSTS, order_by="published_at",
                               desc=True, limit=100),
        "pages": ((stages.get("assembly") or {}).get("output") or {}).get("pages", []),
        "marketing": (stages.get("marketing") or {}).get("output"),
    })
