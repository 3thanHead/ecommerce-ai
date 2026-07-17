#!/usr/bin/env python3
"""Build the public storefront as a static site from approved content.

Renders content (an /store/export snapshot) through the same template the
live LAN preview uses (app/agents/shop/render.py), so what you approved in
the flow is exactly what ships. No LLM, no LAN: this runs identically on your
laptop and in GitHub Actions.

    python3 site/build.py --file content/export.json      # the CI path
    python3 site/build.py --url http://localhost:8820     # pull live + build

Output: site/dist/ -- index.html (shop), product/<sku>.html,
blog/index.html + blog/<slug>.html, page/<slug>.html, export.json.

Deps: pip install markdown
"""
import argparse
import importlib.util
import json
import shutil
import sys
import urllib.request
from pathlib import Path

import markdown as md

REPO = Path(__file__).resolve().parents[1]
RENDER_PY = REPO / "app/agents/shop/render.py"
DIST = Path(__file__).resolve().parent / "dist"


def load_render():
    """Load the template module straight from its file -- no app import, so
    building a website needs no langchain/fastapi installed (render.py is
    stdlib-only)."""
    spec = importlib.util.spec_from_file_location("shoprender", RENDER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_export(url: str | None, file: str | None) -> dict:
    if file:
        return json.loads(Path(file).read_text())
    with urllib.request.urlopen(f"{url.rstrip('/')}/store/export", timeout=30) as r:
        return json.load(r)


def build(export: dict) -> Path:
    tmpl = load_render()

    brand = export.get("brand") or {"name": "The Shop", "tagline": ""}
    products = export.get("products") or []
    posts = export.get("posts") or []
    pages = export.get("pages") or []

    if DIST.exists():
        shutil.rmtree(DIST)
    for sub in ("product", "blog", "page"):
        (DIST / sub).mkdir(parents=True)

    # Relative hrefs so the site works from S3/CloudFront or file://
    def ctx(depth: int = 0) -> dict:
        up = "../" * depth
        return {"brand": brand,
                "urls": {"shop": f"{up}index.html", "blog": f"{up}blog/index.html"},
                "products": [{**p, "_href": f"{up}product/{p['sku']}.html"}
                             for p in products],
                "posts": [{**p, "_href": f"{up}blog/{p['slug']}.html"}
                          for p in posts]}

    def write(path: str, page: str, extra: dict, depth: int) -> None:
        c = {**ctx(depth), **extra}
        (DIST / path).write_text(tmpl.render(page, c), encoding="utf-8")

    write("index.html", "shop", {}, 0)
    for p in products:
        prod = {**p, "_href": "#"}
        if p.get("post_slug"):  # relative link to the product's story
            prod["post_slug"] = f"../blog/{p['post_slug']}.html"
        write(f"product/{p['sku']}.html", "product", {"product": prod}, 1)
    write("blog/index.html", "blog", {}, 1)
    for p in posts:
        write(f"blog/{p['slug']}.html", "post",
              {"post": {**p, "body_html": md.markdown(p.get("body_markdown", ""))}}, 1)
    for p in pages:  # about/FAQ/policies render through the post template
        write(f"page/{p['slug']}.html", "post",
              {"post": {**p, "body_html": md.markdown(p.get("body_markdown", ""))}}, 1)

    (DIST / "export.json").write_text(json.dumps(export, indent=2))
    n = 3 + len(products) + len(posts) + len(pages)
    print(f"built {n} pages -> {DIST} "
          f"({len(products)} products, {len(posts)} posts, {len(pages)} pages)")
    return DIST


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="generation service base, e.g. http://localhost:8820")
    src.add_argument("--file", help="a committed content/export.json")
    args = ap.parse_args()
    build(fetch_export(args.url, args.file))
