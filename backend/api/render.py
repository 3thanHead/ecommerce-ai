"""The customer-facing storefront -- a real, self-contained HTML page rendered
from the generated StorePage + resolved products. Served at /store/{slug} (no
/api prefix), mounted before the admin SPA so it takes precedence.

This is the "live store" end of the pipeline: niche → products → generated copy →
a page a shopper could actually browse.
"""
import html

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from ..db import engine
from ..models import Product, Storefront, StorePage

router = APIRouter(tags=["store"])


def _esc(v) -> str:
    return html.escape(str(v or ""))


def _price(p) -> str:
    return f"${p:.2f}" if isinstance(p, (int, float)) else ""


def _product_card(p: Product) -> str:
    img = p.images[0] if p.images else ""
    price = _price(p.price)
    return f"""
      <article class="card">
        <div class="img">{f'<img src="{_esc(img)}" alt="{_esc(p.title)}" loading="lazy">' if img else ''}</div>
        <div class="body">
          <h3>{_esc(p.title)}</h3>
          <p>{_esc(p.description)}</p>
          <div class="row">
            <span class="price">{price}</span>
            <button disabled>Add to cart</button>
          </div>
        </div>
      </article>"""


def _page_html(store: Storefront, page: StorePage | None, products: list[Product]) -> str:
    accent = (page.accent if page else "#6ee7b7")
    tagline = _esc(page.tagline if page else store.category)
    hero = _esc(page.hero if page else store.description)
    sourced = [p for p in products if p.images]
    cards = "\n".join(_product_card(p) for p in sourced) or (
        '<p class="empty">No products sourced yet.</p>')
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(store.name)}</title>
<style>
  :root {{ --accent: {accent}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0b0d12; color: #e7e9ee; line-height: 1.5; }}
  header {{ padding: 64px 24px; text-align: center;
           background: radial-gradient(1200px 400px at 50% -10%, color-mix(in srgb, var(--accent) 22%, transparent), transparent); }}
  header .brand {{ font-size: 13px; letter-spacing: .18em; text-transform: uppercase;
                  color: var(--accent); font-weight: 700; }}
  header h1 {{ font-size: clamp(28px, 6vw, 52px); margin: 10px 0 6px; }}
  header .tag {{ font-size: clamp(16px, 3vw, 22px); color: var(--accent); font-weight: 600; }}
  header .hero {{ max-width: 640px; margin: 16px auto 0; color: #aab; }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 8px 20px 64px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 20px; }}
  .card {{ background: #141821; border: 1px solid #222836; border-radius: 12px; overflow: hidden;
          display: flex; flex-direction: column; }}
  .card .img {{ aspect-ratio: 1; background: #1a1f2b; }}
  .card .img img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
  .card .body {{ padding: 14px; display: flex; flex-direction: column; gap: 8px; flex: 1; }}
  .card h3 {{ margin: 0; font-size: 15px; }}
  .card p {{ margin: 0; font-size: 13px; color: #aab; flex: 1; }}
  .card .row {{ display: flex; justify-content: space-between; align-items: center; margin-top: 6px; }}
  .card .price {{ font-weight: 700; color: var(--accent); font-size: 18px; }}
  .card button {{ background: var(--accent); color: #0b0d12; border: 0; border-radius: 8px;
                 padding: 8px 14px; font-weight: 700; cursor: not-allowed; opacity: .9; }}
  .empty {{ color: #778; text-align: center; padding: 40px; }}
  footer {{ text-align: center; color: #556; font-size: 12px; padding: 32px; }}
</style>
</head><body>
  <header>
    <div class="brand">{_esc(store.audience)}</div>
    <h1>{_esc(store.name)}</h1>
    <div class="tag">{tagline}</div>
    <p class="hero">{hero}</p>
  </header>
  <main>
    <div class="grid">
      {cards}
    </div>
  </main>
  <footer>{_esc(store.name)} · demo storefront · prices from CJdropshipping</footer>
</body></html>"""


@router.get("/store/{slug}", response_class=HTMLResponse)
def store_page(slug: str):
    with Session(engine) as session:
        store = session.exec(select(Storefront).where(Storefront.slug == slug)).first()
        if not store:
            return HTMLResponse("<h1>Store not found</h1>", status_code=404)
        page = session.exec(
            select(StorePage).where(StorePage.storefront_id == store.id)).first()
        products = session.exec(
            select(Product).where(Product.storefront_id == store.id)).all()
    return HTMLResponse(_page_html(store, page, products))
