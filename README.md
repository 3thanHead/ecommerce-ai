# ecommerce-ai

Hit a button and get **the least saturated products a model can find** — scanned
out of a much larger candidate pool, where saturation is *measured* from real
supplier catalog counts, not guessed. Drill any survivor
into **real Reddit discussion** to surface concrete products to source
(each with a CJdropshipping search seed) and the subreddits you could actually
post them in. Promote a category and it becomes a storefront with those products
queued up. Generation runs on your **edge-ai** Ollama cluster (free, local); this
app just orchestrates and stores.

Built **feature by feature**. Working today:

- **The button → a descent into niches, ranked by opportunity.** The model
  doesn't pick the board. It suggests broad **directions**, real **CJdropshipping
  supply counts** measure them, and then the engine keeps **drilling the
  best-opportunity lanes into narrower sub-niches** (`"yoga mat" → "aerial yoga
  hammock" → …`), measuring each, until narrowing stops improving. The score is
  **opportunity = demand × low-saturation** — a free **Google Suggest** buyer-
  intent breadth signal for demand, times openness — so the board is the
  best-of-both: things people actually search for AND few sellers stock, never a
  wide-open niche nobody buys. Each result carries its own specific seed and its
  own **micro-community subreddits**. You choose how many to keep and how deep.
- **Surprise me / suggest niches.** No theme? The AI names a batch of obscure but
  *sourceable* enthusiast sub-cultures, auto-picks a few **fresh** ones (it
  remembers what it's tried, so each run explores new ground), and descends. Or
  hit **Suggest niches** to pick one from the list yourself.
- **Drill-down.** Click a category → the free Reddit archives surface real threads
  + subreddit profiles → the model names specific products (each with a
  `cj_search_seed`) and flags which subreddits **allow product posts**. Plus
  per-category long-tail keywords.
- **Measured saturation, banded.** Real supply (CJ product counts) instead of
  the model's opinion — a reproducible number, from an outbound call on your
  machine (nothing exposed). There are two ways to be useless, so the scan keeps
  a *band*: above the ceiling is a commodity fight, below the floor no supplier
  carries it (a wide-open score with nothing to sell). Degrades to the estimate
  when no CJ key is set, and the UI says which.
- **Streamed + local.** Every step streams live, like a build log. One Ollama
  endpoint, model chosen per request; an optional heavier model for the brainstorm.

**Next (Feature 2):** resolve each `cj_search_seed` against CJdropshipping to
attach a real product — info, images, video.

## Flow

```
        [ Find opportunities ]      ← button (theme, # results, scan depth)
                 │
                 │  seed: measure a batch of broad directions on CJ
                 │  ┌── take the least-saturated SOURCEABLE lanes ──┐
                 │  │   ask the model for narrower sub-niches        │ until narrowing
                 │  │   measure those on CJ, band open/crowded/thin  │ stops lowering
                 │  └── the lowest become the next lanes to drill ───┘ sat, or budget
                 ▼
   leaderboard = the n lowest-saturation niches  (measured), each with
                 its own seed + micro-community subreddits
                 │  click one → drill or automate
                 ▼
   Reddit archives ──► products + cj_search_seed + post-friendly subreddits
                 │  promote
                 ▼
   storefront + product candidates  ──►  (Feature 2) CJdropshipping match
```

The drill keys off the **niche** the descent landed on — its specific seed and
its own micro-subreddits — not a high-level category, so the products it surfaces
are niche too. Only drill-down touches the Reddit archives; the descent just
needs the model + CJ counts.

CJ's API is ~1 req/sec, so the descent's wall-clock is roughly the pool size in
seconds (a 16-candidate scan ≈ half a minute). The UI shows a running count.

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
keyword. Without a key, saturation is the model's estimate. It's all outbound and
local: no account to expose, nothing inbound.

A caveat we learned the hard way: CJ's `productNameEn` filter **ORs the words**
and doesn't rank by relevance, so its raw `total` is *not* a count of the thing
you searched — "coffee mug" returns ~9k results that are mostly coffee *tables*
and patio furniture, and *adding* words *raises* the total. Ranking on it pinned
everything at 85–96. So each count is **phrase-checked**: we pull a page, keep
the names that actually describe the product, and scale that rate onto the total
(this also deflates niche-but-common-word seeds like "van life curtain"
correctly). It's coarse — treat the number as a magnitude, not a tally — but it
finally separates open lanes from commodities. Tunables live at the top of
[categories.py](backend/research/categories.py) (`DEFAULT_MAX_SATURATION`,
`MIN_SOURCEABLE_MATCHES`).

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
| `OLLAMA_HEAVY_BASE_URL` / `_MODEL` | optional bigger model for the brainstorm step (blank = use the workhorse) |
| `DATABASE_URL` | SQLite path (default `sqlite:///data/storefront.db`) |
| `CJ_EMAIL` / `CJ_API_KEY` | optional; flips saturation from estimate → measured (+ Feature 2 source) |

## Layout

```
backend/
  llm/ollama.py          the whole AI connection (one Ollama endpoint, schema-JSON)
  research/
    categories.py        stage 1 — prospect a pool, keep the least saturated n
    drilldown.py         stage 2 — category → subreddits + posts → products (CJ seeds)
    reddit.py            Reddit grounding: PullPush (posts) + Arctic Shift (profiles)
    keywords.py          Google Suggest keyword expansion
    saturation.py        measured saturation — CJ supply counts vs demand
  api/                   chat, opportunities, storefronts, diagnostics
  models.py              Storefront / Product / Niche / ResearchRun (SQLite)
frontend/src/            React admin: Opportunities, Storefronts, Chat
infra/                   Terraform (AWS deploy — later)
```
