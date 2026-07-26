# ecommerce-ai

Hit a button and get **storefront concepts built out of real products** — scanned
live from CJdropshipping's catalog, scored by how many sellers are already on each
item versus how many people search for it. Every product on the board exists and
is sourceable, so promoting a concept builds a storefront out of inventory rather
than out of an idea. Drill any concept into **real Reddit discussion** for its
audience and the subreddits you could actually post in. Generation runs on your
**edge-ai** Ollama cluster (free, local); this app just orchestrates and stores.

Built **feature by feature**. Working today:

- **The button → CJ's catalog first, the model last.** Stage 1 starts from real
  inventory, not imagination: it picks real **leaf categories** from CJ's tree
  (540 of them), pulls the actual products in them, and scores each one. The
  saturation signal is CJ's own **`listedNum`** — how many CJ sellers already list
  *that exact product* — so it's exact and per-product, not a keyword guess.
  Demand is a free **Google Suggest** buyer-intent probe. The score is
  **opportunity = demand × openness × proof-of-sale**: a product nobody competes
  on *and* nobody buys scores near zero, because an empty aisle isn't an
  opportunity. Only then does the model get involved — grouping the winning real
  products into **storefront concepts** (name, audience, angle, subreddits).
- **Surprise me.** No theme? It rotates into CJ categories recent runs haven't
  touched (it remembers), so each run sweeps new aisles. No model needed to
  choose, so a flaky fleet can't stall the scan. With a theme, it matches CJ's
  real category names, and where a theme shares no words with them ("desk
  setups") the model maps it onto the **real aisle list** — picking by index, so
  it can't conjure a category with nothing behind it.
- **Drill-down.** Click a concept → the free Reddit archives surface real threads
  + subreddit profiles → the audience's own language and which subreddits
  **allow product posts**. Plus long-tail keywords for the copy.
- **Product resolution (Feature 2).** Promoting a concept seeds its products with
  their real CJ ids already attached. **Resolve** fetches each one's full record —
  price, image gallery, video — live from CJ. (Legacy candidates that only carry
  a search seed still get the search-and-verify path.)
- **Storefront generation.** Hit **Generate store** and the model writes the
  store's branding (tagline, hero, accent colour) and a benefit-led sales pitch
  per product, aimed at that concept's audience. It renders a real customer-facing
  page at **`/store/{slug}`** — hero + product grid with the CJ images, pitches,
  and prices. The actual live end of the pipeline.
- **Streamed + local.** Every step streams live, like a build log. One Ollama
  endpoint, model chosen per request; an optional heavier model for clustering.

**Next:** a daily unattended batch that sweeps the catalog and builds stores from
what it finds; then POD/digital verticals (which need their own supply signals —
CJ is dropship-only).

## Flow

```
        [ Find opportunities ]      ← button (theme, # concepts, scan depth)
                 │
                 │  pick REAL CJ leaf categories: theme → name match → model maps
                 │  the theme onto real aisles;  no theme → rotate to fresh ones
                 ▼
   pull the real products in them (pid, title, price, image, listedNum)
                 │  score each: saturation = sellers already on it,
                 │  demand = buyer-intent autocompletes, proof = has it ever sold
                 ▼
   the openest distinct products  ──►  model groups them into STOREFRONT CONCEPTS
                 │                      (falls back to CJ's own categories if the
                 │                       fleet is down — the board still comes out)
                 │  click one → drill (audience) or automate
                 ▼
   storefront + its real products (CJ ids already attached)
                 │  Resolve → full gallery, video, current price from CJ
                 ▼
   Generate → model writes branding + per-product sales copy
                 ▼
   live store at /store/{slug}  (hero + product grid, real images/prices)
```

Nothing invented survives to the board: the model never names a product, it only
groups products CJ already sells. Only drill-down touches the Reddit archives.

CJ's API is throttled to ~1 request per 2s and one category = one request, so a
scan is roughly `categories × 2s` plus the clustering call (~30s).

## Grounding — all free, no keys

**Reddit** grounding uses the Pushshift-successor **archives**, which need no
Reddit account:
- **PullPush** — keyword search → which subreddits discuss a niche + real post
  engagement (score, comments).
- **Arctic Shift** — subreddit profiles: subscribers, rules, submission type, so
  the model can judge "can I post products here?".

Both are community-run, throttled, and fail-soft — a dead source just thins a
drill, and the UI labels how grounded it was (`pullpush+arctic` / `arctic-only` /
`model-only`). Nothing to configure.

**Supply** grounding is **CJdropshipping** (free account) — it *is* the catalog
the whole flow reads from, so without a key there's nothing to prospect. It's all
outbound and local: no account to expose, nothing inbound.

Two caveats we learned the hard way, both handled in code:

- **`listedNum` is the honest saturation signal.** We used to phrase-match CJ's
  keyword search, but its `productNameEn` filter **ORs the words** and doesn't
  rank by relevance, so the raw `total` isn't a count of what you searched —
  "coffee mug" returns ~9k results that are mostly coffee *tables*, and *adding*
  words *raises* the total. Every product row already carries how many CJ sellers
  list it (median 4 in Decor Paintings, 105 in Evening Dresses, hot items in the
  hundreds). That's real competition, per product, free.
- **CJ's category filter isn't always a filter.** For small categories their
  backend falls back to a fuzzy name search: `Basketball Shoes` (total 132) comes
  back 42% *laundry baskets*. Small categories whose page is substantially
  off-topic get the strays dropped, and the scan says how many.

Tunables live at the top of [prospect.py](backend/research/prospect.py)
(`DEFAULT_MAX_SATURATION`, `_LISTING_CEILING`, `_PROOF`) and
[catalog.py](backend/research/catalog.py) (`_SMALL_CATEGORY`, `_CONTAMINATED`).

## Quick start (docker — everything in one container)

```bash
cp .env.example .env          # set OLLAMA_BASE_URL + OLLAMA_MODEL (+ CJ keys)
make run                      # build + run -> open http://localhost:8820
make logs                     # tail logs   |   make stop   to stop
make check-llm                # confirm the edge-ai connection
make check-saturation         # confirm the CJ supply source
```

The image builds the React admin and serves it from FastAPI, so there's a single
container and one URL. Data persists to `./data`. AI still runs on edge-ai.

### Local dev without docker (hot reload, two processes)

```bash
make install                  # python venv + npm deps
make dev                      # backend  :8820   (terminal 1)
make ui                       # admin UI :5173   (terminal 2, proxies /api)
```

## Config (`.env`)

| var | what |
|-----|------|
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | the edge-ai endpoint + workhorse model |
| `OLLAMA_HEAVY_BASE_URL` / `_MODEL` | optional bigger model for the clustering step (blank = use the workhorse) |
| `DATABASE_URL` | SQLite path (default `sqlite:///data/storefront.db`) |
| `CJ_EMAIL` / `CJ_API_KEY` | **required** — CJ's catalog is what stage 1 prospects (and the product source) |

## Layout

```
backend/
  llm/ollama.py          the whole AI connection (one Ollama endpoint, schema-JSON)
  research/
    catalog.py           CJ's catalog: real category tree + real products
    prospect.py          stage 1 — scan real products → storefront concepts
    drilldown.py         stage 2 — concept → subreddits + posts → audience research
    reddit.py            Reddit grounding: PullPush (posts) + Arctic Shift (profiles)
    keywords.py          Google Suggest keyword expansion + demand probe
    saturation.py        CJ auth/throttle + keyword-supply counts (drill-down)
    products.py          Feature 2 — hydrate a CJ pid (or resolve a legacy seed)
    store_gen.py         storefront generation — branding + per-product sales copy
  api/                   chat, opportunities, storefronts, diagnostics, render (/store)
  models.py              Storefront / Product / Niche / ResearchRun (SQLite)
frontend/src/            React admin: Opportunities, Storefronts, Chat
infra/                   Terraform (AWS deploy — later)
```
