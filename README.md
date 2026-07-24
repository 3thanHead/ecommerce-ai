# storefront-ai

Hit a button and get **product categories ranked least-saturated first**, then
**drill any one into Reddit** to surface concrete products to source — each with
a search seed for CJdropshipping. Promote a category and it becomes a storefront
with those products queued up. Generation runs on your **edge-ai** Ollama box
(free, local); this app just orchestrates and stores.

Built **feature by feature**. Working today:

- **The button → category leaderboard.** One model call ranks product categories
  by saturation (least crowded first), each with its audience, the winning
  angle, and the subreddits to dig into. Fast and organic — no keyword lists.
- **Drill-down.** Click a category → the agent pulls real Reddit threads from its
  communities and names specific products to sell, each with a `cj_search_seed`.
- **Promote → storefront.** A category becomes a storefront; its drilled products
  become candidates carrying the CJ seed.
- **LLM connection.** One Ollama endpoint, model chosen per request. Point
  `OLLAMA_BASE_URL` at edge-ai (or a local Ollama) and go.

**Next (Feature 2):** resolve each `cj_search_seed` against CJdropshipping to
attach a real product — info, images, videos.

## Flow

```
        [ Find opportunities ]            ← button (optional broad theme)
                 │  the model ranks categories by saturation
                 ▼
   category leaderboard  (least saturated first)
                 │  click one → drill
                 ▼
   Reddit threads ──► concrete products + cj_search_seed   ← grounded in discussion
                 │  promote
                 ▼
   storefront + product candidates  ──►  (Feature 2) CJdropshipping match
```

Stage 1 is instant and offline (pure model judgment). Only drill-down touches
the network, so the leaderboard never waits on Reddit.

## The Reddit path (and its honest limits)

Drill-down reads Reddit through one interface that degrades:

1. **PRAW read-only** — used when `REDDIT_CLIENT_ID/SECRET` are set. Real
   structured signals (score, comments), ToS-compliant, hits `oauth.reddit.com`
   (the sanctioned path, not the blocked public web). **This is the reliable
   way to ground drill-downs.** Register a **"script" app** at
   reddit.com/prefs/apps — instant, no approval queue (that gate is only the
   *commercial* Data API).
2. **Public `.json`** — no key, full signals when it works.
3. **Jina page-read** — `r.jina.ai` reads Reddit pages server-side.

> **Reality check:** Reddit aggressively 403-blocks the keyless paths (2 and 3)
> — often from residential IPs *and* Jina's servers. When that happens the drill
> falls back to category reasoning only and the UI says so. **Add a Reddit
> script app (path 1) for dependable grounding.** Posting is never automated —
> the agent drafts; you post.

## Quick start (docker — everything in one container)

```bash
cp .env.example .env          # set OLLAMA_BASE_URL + OLLAMA_MODEL
make run                      # build + run -> open http://localhost:8820
make logs                     # tail logs   |   make stop   to stop
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
| `OLLAMA_BASE_URL` | edge-ai box, e.g. `http://192.168.1.111:11434` |
| `OLLAMA_MODEL` | default model (any you've pulled there) |
| `DATABASE_URL` | SQLite path (default `sqlite:///data/storefront.db`) |
| `REDDIT_CLIENT_ID` / `_SECRET` | optional; enables reliable PRAW grounding |
| `JINA_READER_BASE` | keyless page reader (default `https://r.jina.ai`) |

## Layout

```
backend/
  llm/ollama.py          the whole AI connection (one Ollama endpoint, schema-JSON)
  research/
    categories.py        stage 1 — brainstorm + rank by measured saturation
    drilldown.py         stage 2 — category → subreddits + posts → products (CJ seeds)
    subreddits.py        Reddit grounding: PullPush (posts) + Arctic Shift (profiles)
    keywords.py          Google Suggest keyword expansion
    saturation.py        measured saturation — CJ/eBay supply counts vs demand
    web.py               keyless page reader (Firecrawl / Jina)
  api/                   chat, opportunities, storefronts, reddit, saturation
  models.py              Storefront / Product / Niche / ResearchRun (SQLite)
frontend/src/            React admin: Opportunities, Storefronts, Chat
infra/                   Terraform (AWS deploy — later)
```
