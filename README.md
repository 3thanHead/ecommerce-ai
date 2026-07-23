# storefront-ai

Turn a category or chat prompt into **product niches** — researched from real
Reddit discussion + keyword demand, rated for saturation by a local LLM — then
manage the storefronts those niches become. Generation runs on your **edge-ai**
Ollama box (free, local); this app just orchestrates and stores.

Being built **feature by feature**. What works today:

- **Feature 1 — niche research agent.** One prompt → the model plans where to
  look → real Reddit threads + Google-autocomplete keyword demand → the model
  synthesizes niche candidates, each with a demand score and a **saturation
  rating it has to justify**. Promote a candidate to create a storefront.
- **LLM connection.** One Ollama endpoint, model chosen per request. Nothing
  more — point `OLLAMA_BASE_URL` at edge-ai (or a local Ollama) and go.

Later: CJdropshipping product matching (info/images/videos) → products on the
storefronts (Feature 2); publishing.

## Architecture

```
you ─► React admin (Vite)
          │  /api
          ▼
     FastAPI backend ──► research agent ──┬─► Reddit (3 backends, degrade in order)
          │                               ├─► Google Suggest (keyword demand)
          │                               └─► edge-ai / Ollama  [the model]
          ▼
     SQLite (storefronts, niches, products, runs)
```

Deliberately small: SQLite (one file), one backend service, one AI endpoint.

## The Reddit path (why three backends)

Research reads Reddit through one interface that degrades:

1. **PRAW read-only** — used when `REDDIT_CLIENT_ID/SECRET` are set. Structured
   signals (score, comments, upvote ratio), ToS-compliant, ~100 req/min. Register
   a **"script" app** at reddit.com/prefs/apps — instant, no approval queue
   (that gate is only the *commercial* Data API).
2. **Public `.json` endpoints** — no key, full signals *when they work*. Reddit
   now 403-blocks these from many IPs.
3. **Jina page-read** (always-on floor) — `r.jina.ai` reads a subreddit's `/top`
   listing **server-side**, so it works even when 1 and 2 are blocked from your
   box. Titles + subreddits are real; engagement numbers aren't in the page, so
   scores show as 0. This keeps research alive with zero credentials.

Posting is never automated — the agent drafts content for you to post manually.

> **Better signals:** add a Reddit script app (path 1) and/or point
> `OLLAMA_MODEL` at a larger model — a small 4B model sometimes invents
> subreddit names, which the discovery filter simply drops.

## Quick start

```bash
cp .env.example .env          # set OLLAMA_BASE_URL + OLLAMA_MODEL
make install                  # python venv + npm deps

# two terminals:
make dev                      # backend  :8820
make ui                       # admin UI :5173  -> open this

make check-llm                # confirm the edge-ai connection + list models
```

Docker (backend only; UI via `make ui`):

```bash
make run                      # docker compose up -d --build
```

## Config (`.env`)

| var | what |
|-----|------|
| `OLLAMA_BASE_URL` | edge-ai box, e.g. `http://192.168.1.111:11434` |
| `OLLAMA_MODEL` | default model (any you've pulled there) |
| `DATABASE_URL` | SQLite path (default `sqlite:///data/storefront.db`) |
| `REDDIT_CLIENT_ID` / `_SECRET` | optional; enables the PRAW path |
| `JINA_READER_BASE` | keyless page reader (default `https://r.jina.ai`) |

## Layout

```
backend/app/
  llm/ollama.py        the whole AI connection (one endpoint, per-call model)
  research/
    reddit.py          3-backend Reddit client (PRAW / .json / Jina)
    keywords.py        Google Suggest keyword expansion
    web.py             keyless page reader (Jina) + web search
    agent.py           plan → gather → judge (saturation reasoning)
  api/                 chat, research, storefronts
  models.py            Storefront / Niche / Product / ResearchRun (SQLite)
frontend/src/          React admin: Research, Storefronts, Chat
```
