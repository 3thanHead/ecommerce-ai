import { useState } from "react";
import { api, Category, CJProduct, Drill, Scan, ScoutResult } from "../api";
import { Banner, Meter, Working } from "../components";
import { useJob } from "../useJob";

function fmt(n: number): string {
  return n >= 1000 ? (n / 1000).toFixed(n >= 100000 ? 0 : 1) + "k" : String(n);
}

// Scan depth is now measured in REAL CJ categories swept — one catalog request
// each (~100 products), so depth buys breadth of real inventory, not more guesses.
const DEPTHS = [
  { cats: 4, label: "Quick", hint: "4 CJ categories — a fast look" },
  { cats: 8, label: "Standard", hint: "8 CJ categories — the usual sweep" },
  { cats: 16, label: "Deep", hint: "16 CJ categories — widest net, slower" },
];

// CJ's catalog calls are throttled to ~1 every 2s; clustering adds ~half a minute.
function eta(cats: number): string {
  const secs = Math.round(cats * 2 + 35);
  return secs < 90 ? `~${secs}s` : `~${Math.round(secs / 60)} min`;
}

function ScanSummary({ scan }: { scan: Scan }) {
  if (!scan.measured) {
    return (
      <div className="card muted" style={{ fontSize: 13 }}>
        No supplier connected — add <b>CJ_EMAIL</b>/<b>CJ_API_KEY</b> to .env.
        Everything here starts from CJ's real catalog, so there's nothing to scan
        without it.
      </div>
    );
  }
  return (
    <div className="card" style={{ fontSize: 13 }}>
      Scanned <b>{scan.scanned}</b> real CJ products across{" "}
      <b>{scan.categories_scanned}</b>{" "}
      {scan.categories_scanned === 1 ? "category" : "categories"}
      {scan.median_listings != null && (
        <span className="muted"> · median {scan.median_listings} sellers per product</span>
      )}{" "}
      →{" "}
      <span style={{ color: "var(--good)" }}>
        <b>{scan.open ?? 0}</b> under the ceiling (saturation ≤ {scan.max_saturation})
      </span>{" "}
      <span className="muted">· {scan.crowded ?? 0} already crowded</span>
      <div style={{ marginTop: 6 }}>
        <span style={{ color: "var(--good)" }}>
          ✓ {scan.concepts ?? 0} storefront concept
          {scan.concepts === 1 ? "" : "s"} built from {scan.kept ?? 0} real,
          sourceable products
        </span>
        {scan.requested != null &&
          (scan.concepts ?? 0) < scan.requested && (
            <span style={{ color: "var(--warn)" }}>
              {" "}— {scan.concepts} of {scan.requested} asked for. That's what CJ
              actually had here; try a deeper scan or a broader theme.
            </span>
          )}
      </div>
      {scan.grounds?.length > 0 && (
        <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
          where the board came from
          {scan.categories_scanned > scan.grounds.length &&
            ` (${scan.grounds.length} of ${scan.categories_scanned} swept)`}
          :{" "}
          {scan.grounds.map((g) => (
            <span className="pill" key={g}>
              {g}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function FriendlyBadge({ v }: { v: "yes" | "limited" | "no" }) {
  const map = {
    yes: ["✅ can post", "var(--good)"],
    limited: ["⚠️ limited", "var(--warn)"],
    no: ["❌ no promo", "var(--bad)"],
  } as const;
  const [label, color] = map[v] ?? map.limited;
  return (
    <span className="pill" style={{ borderColor: color, color }}>
      {label}
    </span>
  );
}

// One real CJ product on a concept card: picture, price, and how many sellers
// are already on it (the whole reason it made the board).
function ProductTile({ p }: { p: CJProduct }) {
  return (
    <div
      className="thread"
      style={{ display: "flex", gap: 10, alignItems: "center", paddingBottom: 8 }}
      title={`${p.title}\nCJ ${p.pid} · ${p.category_path}`}
    >
      {p.image && (
        <img
          src={p.image}
          alt={p.title}
          loading="lazy"
          style={{ width: 46, height: 46, borderRadius: 6, objectFit: "cover", flexShrink: 0 }}
        />
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          {p.title}
        </div>
        <div className="muted" style={{ fontSize: 12 }}>
          {p.price != null && <b>${p.price.toFixed(2)}</b>}
          {p.price != null && " · "}
          <span
            style={{ color: p.listings <= 5 ? "var(--good)" : undefined }}
            title="CJ sellers already listing this exact product"
          >
            {p.listings} seller{p.listings === 1 ? "" : "s"}
          </span>
          {" · "}
          {p.category}
        </div>
      </div>
    </div>
  );
}

// The whole flow: hit the button -> CJ's real catalog is scanned and grouped into
// storefront concepts -> drill one for its audience, or automate the store.
export function Opportunities({
  model,
  onPromoted,
}: {
  model: string;
  onPromoted: () => void;
}) {
  const [theme, setTheme] = useState("");
  const [n, setN] = useState(8);
  const [cats, setCats] = useState(8);
  const scout = useJob<ScoutResult>();

  const pool = cats * 100;

  // No theme -> "surprise me": rotate into CJ categories recent runs skipped.
  // A typed theme picks the real categories whose names match it.
  function find() {
    if (scout.running) return;
    scout.run("/api/opportunities/stream", { theme, model, n, pool });
  }

  const result = scout.result;

  return (
    <>
      <div className="card">
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <label>Theme (optional — blank = sweep fresh CJ categories)</label>
            <input
              value={theme}
              placeholder="blank → surprise me · or type a space, e.g. desk setups"
              onChange={(e) => setTheme(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && find()}
            />
          </div>
          <div>
            <label>Concepts</label>
            <select value={n} onChange={(e) => setN(Number(e.target.value))}>
              {[3, 5, 8, 12, 20].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label>Scan depth</label>
            <select
              value={cats}
              onChange={(e) => setCats(Number(e.target.value))}
              title={DEPTHS.find((d) => d.cats === cats)?.hint}
            >
              {DEPTHS.map((d) => (
                <option key={d.cats} value={d.cats} title={d.hint}>
                  {d.label} ({d.cats} categories)
                </option>
              ))}
            </select>
          </div>
          <button className="primary" onClick={find} disabled={scout.running}>
            {scout.running ? "Scanning…" : theme.trim() ? "Find opportunities" : "Surprise me"}
          </button>
        </div>

        <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
          Sweeps <b>{cats}</b> real CJdropshipping categories (~<b>{pool}</b>{" "}
          products), keeps the least-contested, and groups them into <b>{n}</b>{" "}
          storefront concepts · {eta(cats)}
        </div>
        {(scout.running || (!result && scout.steps.length > 0)) && (
          <div style={{ marginTop: 12 }}>
            <Working steps={scout.steps} thinking={scout.thinking} />
          </div>
        )}
        {!result && !scout.running && scout.steps.length === 0 && (
          <p className="muted" style={{ marginBottom: 0 }}>
            Hit <b>Surprise me</b> and it sweeps aisles of CJdropshipping's real
            catalog you haven't looked at yet, scores every product by how many
            sellers are already on it versus how many people search for it, then
            groups the openings into storefront concepts. Every product you see is
            real and sourceable — drill one for its audience, or{" "}
            <b>Automate</b> the whole store.
          </p>
        )}
      </div>

      {scout.error && <Banner>{scout.error}</Banner>}
      {result?.error && <Banner>{result.error}</Banner>}

      {result?.scan && <ScanSummary scan={result.scan} />}

      {result &&
        result.categories.map((c, i) => (
          <CategoryCard
            key={i}
            category={c}
            runId={result.run_id}
            index={i}
            model={model}
            onPromoted={onPromoted}
          />
        ))}
    </>
  );
}

function CategoryCard({
  category: c,
  runId,
  index,
  model,
  onPromoted,
}: {
  category: Category;
  runId: number;
  index: number;
  model: string;
  onPromoted: () => void;
}) {
  const job = useJob<any>();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"drill" | "automate" | null>(null);
  const [promotedSlug, setPromotedSlug] = useState("");

  // The drill data can come from a drill run (result IS the drill) or an
  // automate run (result.drill).
  const drill: Drill | null = job.result
    ? job.result.opportunities
      ? job.result
      : job.result.drill ?? null
    : null;
  const automatedSlug: string | undefined = job.result?.slug;

  function start(which: "drill" | "automate") {
    setOpen(true);
    setMode(which);
    setPromotedSlug("");
    const path =
      which === "drill"
        ? "/api/opportunities/drill/stream"
        : "/api/opportunities/automate/stream";
    job.run(path, { run_id: runId, category_index: index, model }).then(() => {
      if (which === "automate") onPromoted();
    });
  }

  async function promote() {
    try {
      const r = await api.promote(runId, index);
      setPromotedSlug(r.slug);
      onPromoted();
    } catch {
      /* surfaced elsewhere */
    }
  }

  const products = c.products ?? [];
  const thumb = products[0]?.image;

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 14 }}>
        {thumb && (
          <img
            src={thumb}
            alt={c.name}
            loading="lazy"
            style={{ width: 72, height: 72, borderRadius: 8, objectFit: "cover", flexShrink: 0 }}
          />
        )}
        <div style={{ flex: 1 }}>
          <div className="row" style={{ alignItems: "center", gap: 10 }}>
            {c.opportunity != null && (
              <span
                className="pill"
                style={{ borderColor: "var(--good)", color: "var(--good)", fontWeight: 700 }}
                title="Opportunity = demand × low saturation — the score the board is ranked by. High = people search for it AND few sellers are on it."
              >
                ⭐ {c.opportunity}
              </span>
            )}
            <Meter label="saturation" value={c.saturation} invert />
            {c.demand != null && <Meter label="demand" value={c.demand} />}
            <span
              className="pill"
              style={{ borderColor: "var(--good)", color: "var(--good)" }}
              title={c.saturation_reasoning}
            >
              ✓ {c.listings ?? 0} sellers/product
            </span>
            {c.band === "crowded" && (
              <span
                className="pill"
                style={{ borderColor: "var(--warn)", color: "var(--warn)" }}
                title="Over the saturation ceiling — shown only because the scan found nothing more open."
              >
                over ceiling
              </span>
            )}
            <h3 style={{ margin: 0, fontSize: 16 }}>{c.name}</h3>
          </div>
          <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
            {c.audience}
          </div>
          <div style={{ fontSize: 12, marginTop: 4 }}>
            <span style={{ color: "var(--good)" }}>
              {products.length} real CJ product{products.length === 1 ? "" : "s"}
            </span>
            {c.price_range && (
              <span className="muted">
                {" "}· ${c.price_range[0].toFixed(2)}–${c.price_range[1].toFixed(2)} cost
              </span>
            )}
            {c.category_paths?.length ? (
              <span className="muted"> · {c.category_paths.join(" / ")}</span>
            ) : null}
          </div>
          <div style={{ marginTop: 6 }}>
            {(c.subreddits ?? []).slice(0, 4).map((s) => (
              <span className="pill" key={s}>
                r/{s}
              </span>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="ghost" onClick={() => setOpen((v) => !v)}>
            {open ? "Hide" : "Products"}
          </button>
          <button className="ghost" disabled={job.running} onClick={() => start("drill")}>
            Drill
          </button>
          <button className="primary" disabled={job.running} onClick={() => start("automate")}>
            {mode === "automate" && job.running ? "Automating…" : "Automate"}
          </button>
        </div>
      </div>

      {open && (
        <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
            <b>Angle:</b> {c.angle}
          </p>

          <label>The shelf — real CJ products, best opportunity first</label>
          {products.map((p) => (
            <ProductTile key={p.pid} p={p} />
          ))}

          {!drill && !job.running && (
            <div style={{ marginTop: 14 }}>
              {promotedSlug ? (
                <span style={{ color: "var(--good)" }}>
                  ✓ storefront /{promotedSlug} created
                </span>
              ) : (
                <button className="primary" onClick={promote}>
                  Create storefront + {products.length} products
                </button>
              )}
            </div>
          )}

          {(job.running || job.steps.length > 0) && (
            <div style={{ marginTop: 12 }}>
              <Working steps={job.steps} thinking={job.thinking} />
            </div>
          )}
          {job.error && <Banner>{job.error}</Banner>}

          {drill && (
            <div style={{ marginTop: 12 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
                {drill.reddit_source === "model-only" ? (
                  <span style={{ color: "var(--warn)" }}>
                    ⚠ Reddit archives quiet — subreddits from the model's knowledge,
                    not verified. Try again in a bit for live data.
                  </span>
                ) : (
                  <>
                    grounded via <b>{drill.reddit_source}</b> ·{" "}
                    {drill.posts_sampled.length} real posts
                  </>
                )}
              </div>

              {drill.subreddits.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <label>Subreddits — can you post products there?</label>
                  {drill.subreddits.map((s) => (
                    <div key={s.name} className="thread" style={{ paddingBottom: 8 }}>
                      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                        <div>
                          <FriendlyBadge v={s.product_friendly} />{" "}
                          <a href={`https://reddit.com/r/${s.name}`} target="_blank" rel="noreferrer">
                            r/{s.name}
                          </a>{" "}
                          {s.subscribers > 0 && (
                            <span className="muted">· {fmt(s.subscribers)} members</span>
                          )}
                          {s.submission_type && (
                            <span className="muted"> · {s.submission_type} posts</span>
                          )}
                          {!s.exists && <span className="muted"> · unverified</span>}
                        </div>
                      </div>
                      {s.reason && (
                        <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                          {s.reason}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {drill.opportunities.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <label>What this audience asks for (angles for the copy)</label>
                  {drill.opportunities.map((o, j) => (
                    <div key={j} className="thread" style={{ paddingBottom: 10 }}>
                      <div className="row" style={{ justifyContent: "space-between" }}>
                        <b>{o.product}</b>
                        <span className="meter">
                          <span className="muted">demand</span> <b>{o.demand_signal}</b>
                        </span>
                      </div>
                      <div className="muted" style={{ fontSize: 13, margin: "3px 0" }}>
                        {o.rationale}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {drill.keywords.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <label>Keywords for this concept ({drill.keywords.length})</label>
                  <div>
                    {drill.keywords.slice(0, 16).map((k) => (
                      <span className="pill" key={k.phrase}>
                        {k.phrase}
                        {k.freq > 1 && <span className="muted"> ·{k.freq}</span>}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div style={{ marginTop: 14 }}>
                {automatedSlug ? (
                  <span style={{ color: "var(--good)" }}>
                    ✓ storefront <b>/{automatedSlug}</b> built with{" "}
                    {job.result.products_seeded} real CJ products
                  </span>
                ) : promotedSlug ? (
                  <span style={{ color: "var(--good)" }}>✓ storefront /{promotedSlug} created</span>
                ) : (
                  <button className="primary" onClick={promote}>
                    Create storefront + {products.length} products
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
