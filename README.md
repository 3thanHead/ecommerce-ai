# ecommerce-ai

Hit a button and get **product categories ranked least-saturated first** — where
saturation is *measured* from real supplier catalog counts, not guessed. Drill any
category into **real Reddit discussion** to surface concrete products to source
(each with a CJdropshipping search seed) and the subreddits you could actually
post them in. Promote a category and it becomes a storefront with those products
queued up. Generation runs on your **edge-ai** Ollama cluster (free, local); this
app just orchestrates and stores.

Built **feature by feature**. Working today:

- **The button → measured leaderboard.** The model brainstorms product
  categories; real **CJdropshipping supply counts** rank them by saturation
  (least crowded first), each with its audience, the winning angle, and the
  subreddits to dig into.
- **Drill-down.** Click a category → the free Reddit archives surface real threads
  + subreddit profiles → the model names specific products (each with a
  `cj_search_seed`) and flags which subreddits **allow product posts**. Plus
  per-category long-tail keywords.
- **Measured saturation.** Real supply (CJ product counts, optionally eBay
  listings) instead of the model's opinion — a reproducible number. Degrades to
  the estimate when no supply key is set, and the UI says which.
- **Streamed + local.** Every step streams live, like a build log. One Ollama
  endpoint, model chosen per request; an optional heavier model for the brainstorm.

**Next (Feature 2):** resolve each `cj_search_seed` against CJdropshipping to
attach a real product — info, images, video.

## Flow

```
        [ Find opportunities ]            ← button (optional broad theme)
                 │  model brainstorms categories → CJ supply counts rank them
                 ▼
   category leaderboard  (least SATURATED first — measured)
                 │  click one → drill or automate
                 ▼
   Reddit archives ──► products + cj_search_seed + post-friendly subreddits
                 │  promote
                 ▼
   storefront + product candidates  ──►  (Feature 2) CJdropshipping match
```

Only drill-down touches the Reddit archives; the leaderboard just needs the model
+ CJ counts.

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

**Saturation** grounding is **CJdropshipping** (free account) — supply counts per
keyword. Add eBay for a second signal. Without a key, saturation is the model's
estimate.

## Quick start (docker — everything in one container)

```bash
cp .env.example .env          # set OLLAMA_BASE_URL + OLLAMA_MODEL (+ CJ keys)
make run                      # build + run -> open http://localhost:8820
make logs                     # tail logs   |   make stop   to stop
make check-llm                # confirm the edge-ai connection
make check-saturation         # confirm CJ/eBay supply sources
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
| `OLLAMA_HEAVY_BASE_URL` / `_MODEL` | optional bigger model for the brainstorm step (blank = use the workhorse) |
| `DATABASE_URL` | SQLite path (default `sqlite:///data/storefront.db`) |
| `CJ_EMAIL` / `CJ_API_KEY` | optional; flips saturation from estimate → measured (+ Feature 2 source) |
| `EBAY_CLIENT_ID` / `_SECRET` | optional second supply signal |

## Layout

```
backend/
  llm/ollama.py          the whole AI connection (one Ollama endpoint, schema-JSON)
  research/
    categories.py        stage 1 — brainstorm + rank by measured saturation
    drilldown.py         stage 2 — category → subreddits + posts → products (CJ seeds)
    reddit.py            Reddit grounding: PullPush (posts) + Arctic Shift (profiles)
    keywords.py          Google Suggest keyword expansion
    saturation.py        measured saturation — CJ/eBay supply counts vs demand
  api/                   chat, opportunities, storefronts, diagnostics
  models.py              Storefront / Product / Niche / ResearchRun (SQLite)
frontend/src/            React admin: Opportunities, Storefronts, Chat
infra/                   Terraform (AWS deploy — later)
```
