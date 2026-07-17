"""The storefront template -- one clean, self-contained look.

Renders the four pages (shop, product, blog, post) from a single context, with
no external dependencies (inline CSS, system fonts) so the same output works
served live (api/blog.py) or as a static file:// build (site/build.py). Stdlib
only -- site/build.py loads this module by path without importing the app, so
building a site needs no langchain/fastapi.

Context:
    brand    {name, tagline, accent}
    urls     {"shop": ..., "blog": ...}
    products [{..., "_href"}]   product {..., "_href"}
    posts    [{..., "_href"}]   post {..., "body_html"}
"""
import html

ACCENT = "#2563eb"


def esc(v) -> str:
    return html.escape(str(v or ""))


def money(v) -> str:
    try:
        return f"${float(v):,.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "$?"


def _css(accent: str) -> str:
    return f"""
:root {{ color-scheme: light dark; --accent: {accent}; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: system-ui, -apple-system, sans-serif;
  line-height: 1.6; color: #1a1a1a; background: #fafafa; }}
a {{ color: var(--accent); text-decoration: none; }}
header {{ border-bottom: 1px solid #e5e5e5; background: #fff; }}
header .bar {{ max-width: 60rem; margin: 0 auto; padding: 1rem 1.5rem;
  display: flex; justify-content: space-between; align-items: baseline; }}
header .name {{ font-size: 1.25rem; font-weight: 700; }}
header nav a {{ margin-left: 1.5rem; font-size: .95rem; }}
main {{ max-width: 60rem; margin: 0 auto; padding: 2.5rem 1.5rem 4rem; }}
.hero {{ text-align: center; padding: 1rem 0 2.5rem; }}
.hero h1 {{ font-size: 2.5rem; margin: 0 0 .3em; }}
.hero p {{ color: #666; font-size: 1.1rem; margin: 0; }}
.grid {{ display: grid; gap: 1.25rem;
  grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); }}
.card {{ display: block; background: #fff; border: 1px solid #e5e5e5;
  border-radius: 12px; padding: 1.25rem; transition: box-shadow .15s; }}
.card:hover {{ box-shadow: 0 4px 20px rgba(0,0,0,.08); }}
.card .kind {{ font-size: .7rem; text-transform: uppercase; letter-spacing: .08em;
  color: var(--accent); }}
.card h2 {{ font-size: 1.05rem; margin: .3rem 0; color: #1a1a1a; }}
.card .sub {{ color: #666; font-size: .9rem; margin: 0; }}
.card .price {{ font-weight: 700; margin-top: .75rem; }}
.product h1, .post h1 {{ font-size: 2rem; margin: 0 0 .2em; }}
.product .sub {{ color: #666; font-size: 1.1rem; }}
.product ul {{ padding-left: 1.2rem; }} .product li {{ margin: .35rem 0; }}
.buy {{ display: inline-block; margin-top: 1.5rem; background: var(--accent);
  color: #fff; padding: .8rem 2rem; border-radius: 8px; font-weight: 600; }}
.buy.soon {{ background: #ddd; color: #666; }}
.tags {{ margin-top: 1.5rem; }}
.tags span {{ display: inline-block; background: #eee; color: #555;
  border-radius: 99px; padding: .15rem .7rem; font-size: .78rem; margin: 0 .35rem .35rem 0; }}
.post article {{ font-size: 1.05rem; }}
footer {{ max-width: 60rem; margin: 0 auto; padding: 2rem 1.5rem;
  color: #999; font-size: .8rem; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #16181c; color: #e8e8e8; }}
  header, .card {{ background: #1e2126; border-color: #2c3038; }}
  header .name, .card h2, .product h1, .post h1 {{ color: #f0f0f0; }}
  .hero p, .card .sub, .product .sub {{ color: #9aa0a8; }}
  .tags span {{ background: #2c3038; color: #b8bcc4; }}
}}
"""


def _shell(title: str, ctx: dict, body: str, page_class: str = "") -> str:
    b = ctx["brand"]
    return (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc(title)}</title><style>{_css(b.get('accent') or ACCENT)}</style>"
        f"</head><body class='{page_class}'>"
        f"<header><div class='bar'><a class='name' href='{ctx['urls']['shop']}'>{esc(b['name'])}</a>"
        f"<nav><a href='{ctx['urls']['shop']}'>Shop</a>"
        f"<a href='{ctx['urls']['blog']}'>Blog</a></nav></div></header>"
        f"<main>{body}</main>"
        f"<footer>{esc(b['name'])} — products and posts here are AI-assisted creations.</footer>"
        f"</body></html>")


def _card(p: dict) -> str:
    return (f"<a class='card' href='{esc(p['_href'])}'>"
            f"<div class='kind'>{esc(p.get('kind'))}</div>"
            f"<h2>{esc(p['title'])}</h2>"
            f"<p class='sub'>{esc(p.get('subtitle'))}</p>"
            f"<div class='price'>{money(p.get('price_usd'))}</div></a>")


def render(page: str, ctx: dict) -> str:
    b = ctx["brand"]
    if page == "shop":
        hero = (f"<div class='hero'><h1>{esc(b['name'])}</h1>"
                f"<p>{esc(b.get('hero') or b.get('tagline'))}</p></div>")
        grid = "".join(_card(p) for p in ctx["products"]) or \
            "<p style='text-align:center;color:#888'>Nothing for sale yet.</p>"
        return _shell(b["name"], ctx, f"{hero}<div class='grid'>{grid}</div>")

    if page == "product":
        p = ctx["product"]
        bullets = "".join(f"<li>{esc(x)}</li>" for x in p.get("bullets", []))
        paras = "".join(f"<p>{esc(t)}</p>"
                        for t in p.get("description", "").split("\n") if t.strip())
        if p.get("payment_url"):
            buy = f"<a class='buy' href='{esc(p['payment_url'])}'>Buy — {money(p.get('price_usd'))}</a>"
        else:
            buy = f"<span class='buy soon'>{money(p.get('price_usd'))} · checkout coming soon</span>"
        post = (f"<p style='margin-top:1.5rem'><a href='{esc(p['post_slug'])}'>Read the story →</a></p>"
                if p.get("post_slug") else "")
        tags = "".join(f"<span>{esc(t)}</span>" for t in p.get("tags", []))
        return _shell(p["title"], ctx,
                      f"<div class='kind' style='color:var(--accent)'>{esc(p.get('kind'))}</div>"
                      f"<h1>{esc(p['title'])}</h1><p class='sub'>{esc(p.get('subtitle'))}</p>"
                      f"{paras}<ul>{bullets}</ul>{buy}{post}"
                      f"<div class='tags'>{tags}</div>", "product")

    if page == "blog":
        cards = "".join(
            f"<a class='card' href='{esc(p['_href'])}'><h2>{esc(p['title'])}</h2>"
            f"<p class='sub'>{esc(p.get('excerpt'))}</p></a>" for p in ctx["posts"]) or \
            "<p style='text-align:center;color:#888'>No posts yet.</p>"
        return _shell(f"Blog — {b['name']}", ctx,
                      f"<div class='hero'><h1>Blog</h1></div><div class='grid'>{cards}</div>")

    post = ctx["post"]
    tags = "".join(f"<span>{esc(t)}</span>" for t in post.get("tags", []))
    return _shell(post["title"], ctx,
                  f"<h1>{esc(post['title'])}</h1>"
                  f"<article>{post.get('body_html', '')}</article>"
                  f"<div class='tags'>{tags}</div>", "post")
