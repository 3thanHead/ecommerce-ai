import { useState } from "react";
import { api, Category, Drill, Niche, Scan, ScoutResult } from "../api";
import { Banner, Meter, Working } from "../components";
import { useJob } from "../useJob";

function fmt(n: number): string {
  return n >= 1000 ? (n / 1000).toFixed(n >= 100000 ? 0 : 1) + "k" : String(n);
}

// The scan budget, as a multiple of the results you want back. The engine seeds
// broad directions, then keeps drilling the least-saturated into narrower niches
// until it hits the floor — a bigger budget descends further into low saturation.
const DEPTHS = [
  { mult: 1, label: "Quick", hint: "measure the seed directions only — no descent" },
  { mult: 5, label: "Standard", hint: "descend a few levels into niches" },
  { mult: 10, label: "Deep", hint: "descend hard — slow, lowest-saturation niches" },
];

// Supply lookups are serialized at ~1 req/sec by CJ's rate limit, so a big pool
// is genuinely minutes. Say so up front rather than looking hung.
function eta(pool: number): string {
  const secs = Math.round(pool * 1.2);
  return secs < 90 ? `~${secs}s` : `~${Math.round(secs / 60)} min`;
}

function ScanSummary({ scan }: { scan: Scan }) {
  if (!scan.measured) {
    return (
      <div className="card muted" style={{ fontSize: 13 }}>
        Saturation is the model's estimate — add <b>CJ_EMAIL</b>/<b>CJ_API_KEY</b>{" "}
        to .env to measure real supply and descend into low-saturation niches.
      </div>
    );
  }
  return (
    <div className="card" style={{ fontSize: 13 }}>
      Scanned <b>{scan.scanned}</b> candidates over {scan.rounds}{" "}
      {scan.rounds === 1 ? "round" : "rounds"} →{" "}
      <span style={{ color: "var(--good)" }}>
        <b>{scan.open}</b> open {scan.open === 1 ? "lane" : "lanes"}
      </span>{" "}
      (saturation ≤ {scan.max_saturation}) ·{" "}
      <span className="muted">
        {scan.crowded} too crowded · {scan.thin} not sourceable (no supplier
        carries it)
      </span>
      {scan.open === 0 && (
        <div style={{ color: "var(--warn)", marginTop: 6 }}>
          Nothing came in under the ceiling — showing the least crowded of what was
          scanned. Try a narrower theme, a deeper scan, or a higher ceiling.
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

// The whole flow: hit the button -> watch the model rank categories least
// saturated first -> drill or fully automate any one, watching it work.
export function Opportunities({
  model,
  onPromoted,
}: {
  model: string;
  onPromoted: () => void;
}) {
  const [theme, setTheme] = useState("");
  const [n, setN] = useState(8);
  const [depth, setDepth] = useState(5);
  const [niches, setNiches] = useState<Niche[] | null>(null);
  const [nichesBusy, setNichesBusy] = useState(false);
  const scout = useJob<ScoutResult>();

  const pool = Math.min(n * depth, 200);

  function runWith(themeArg: string, explore: boolean) {
    if (scout.running) return;
    setNiches(null);
    scout.run("/api/opportunities/stream", { theme: themeArg, model, n, pool, explore });
  }
  // No theme -> "surprise me": the AI picks fresh niche-spaces itself.
  const find = () => runWith(theme, !theme.trim());
  const pickNiche = (space: string) => {
    setTheme(space);
    runWith(space, false);
  };

  async function suggestNiches() {
    if (nichesBusy) return;
    setNichesBusy(true);
    try {
      setNiches((await api.niches(model, 12)).niches);
    } catch {
      /* surfaced via the banner on the next scout run */
    } finally {
      setNichesBusy(false);
    }
  }

  const result = scout.result;

  return (
    <>
      <div className="card">
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <label>Theme (optional — blank = let the AI pick a fresh niche)</label>
            <input
              value={theme}
              placeholder="blank → surprise me · or type a space, e.g. desk setups"
              onChange={(e) => setTheme(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && find()}
            />
          </div>
          <div>
            <label>Results</label>
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
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
              title={DEPTHS.find((d) => d.mult === depth)?.hint}
            >
              {DEPTHS.map((d) => (
                <option key={d.mult} value={d.mult} title={d.hint}>
                  {d.label} ({d.mult}×)
                </option>
              ))}
            </select>
          </div>
          <button
            className="ghost"
            onClick={suggestNiches}
            disabled={scout.running || nichesBusy}
            title="Let the AI list obscure niches to pick from"
          >
            {nichesBusy ? "Thinking…" : "Suggest niches"}
          </button>
          <button className="primary" onClick={find} disabled={scout.running}>
            {scout.running ? "Scanning…" : theme.trim() ? "Find opportunities" : "Surprise me"}
          </button>
        </div>

        {niches && !scout.running && (
          <div style={{ marginTop: 10 }}>
            <label>Pick a niche to descend into — or just hit Surprise me</label>
            <div>
              {niches.map((nz) => (
                <button
                  key={nz.space}
                  className="pill"
                  onClick={() => pickNiche(nz.space)}
                  title={nz.why}
                  style={{ cursor: "pointer", marginBottom: 4 }}
                >
                  {nz.space}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
          {depth === 1 ? (
            <>Measures the seed directions and ranks them — no descent.</>
          ) : (
            <>
              Descends up to <b>{pool}</b> candidates deep, keeping the <b>{n}</b>{" "}
              lowest-saturation sourceable niches · {eta(pool)} of supplier lookups
            </>
          )}
        </div>
        {(scout.running || (!result && scout.steps.length > 0)) && (
          <div style={{ marginTop: 12 }}>
            <Working steps={scout.steps} thinking={scout.thinking} />
          </div>
        )}
        {!result && !scout.running && scout.steps.length === 0 && (
          <p className="muted" style={{ marginBottom: 0 }}>
            Hit <b>Surprise me</b> and the AI picks a fresh niche for you (different
            every run), then descends into its least-saturated products. Or{" "}
            <b>Suggest niches</b> to pick one yourself. Then drill a niche into
            Reddit for products to source, or <b>Automate</b> a storefront.
          </p>
        )}
      </div>

      {scout.error && <Banner>{scout.error}</Banner>}

      {result?.chosen_niches && result.chosen_niches.length > 0 && (
        <div className="card" style={{ fontSize: 13 }}>
          <span className="muted">AI picked these niches to explore this run:</span>{" "}
          {result.chosen_niches.map((nz) => (
            <span className="pill" key={nz.space} title={nz.why}>
              {nz.space}
            </span>
          ))}
        </div>
      )}

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

  const sat = drill ? drill.saturation : c.saturation;
  const satMethod = drill ? drill.saturation_method : c.saturation_method;
  const satSupply = drill ? drill.saturation_supply : c.saturation_supply;
  const supplyText = Object.entries(satSupply || {})
    .map(([p, n]) => `${n.toLocaleString()} on ${p}`)
    .join(", ");

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ flex: 1 }}>
          <div className="row" style={{ alignItems: "center", gap: 10 }}>
            {c.opportunity != null && (
              <span
                className="pill"
                style={{ borderColor: "var(--good)", color: "var(--good)", fontWeight: 700 }}
                title="Opportunity = demand × low saturation — the score the board is ranked by. High = people search for it AND few sellers stock it."
              >
                ⭐ {c.opportunity}
              </span>
            )}
            <Meter label="saturation" value={sat} invert />
            {c.demand != null && <Meter label="demand" value={c.demand} />}
            {satMethod === "measured" ? (
              <span
                className="pill"
                style={{ borderColor: "var(--good)", color: "var(--good)" }}
                title={`Phrase-matched supplier supply: ${supplyText}`}
              >
                ✓ {c.supply_count != null ? `~${fmt(c.supply_count)}` : "measured"}
              </span>
            ) : (
              <span className="pill muted" title="Model estimate — add a CJ/eBay key for measured supply.">
                est
              </span>
            )}
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
          <div style={{ marginTop: 6 }}>
            {c.subreddits.slice(0, 4).map((s) => (
              <span className="pill" key={s}>
                r/{s}
              </span>
            ))}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
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

          {(job.running || job.steps.length > 0) && (
            <Working steps={job.steps} thinking={job.thinking} />
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
              <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
                saturation:{" "}
                {drill.saturation_method === "measured" ? (
                  <span style={{ color: "var(--good)" }}>
                    ✓ measured —{" "}
                    {Object.entries(drill.saturation_supply)
                      .map(([p, n]) => `${n.toLocaleString()} on ${p}`)
                      .join(", ")}
                  </span>
                ) : (
                  <span>
                    estimated by model{" "}
                    <span title="Add a CJ or eBay key for a measured supply-based score.">
                      (no supply source configured)
                    </span>
                  </span>
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

              <label>Products to source</label>
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
                  <span className="pill">CJ search: {o.cj_search_seed}</span>
                </div>
              ))}

              {drill.keywords.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <label>Keywords for this category ({drill.keywords.length})</label>
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
                    {job.result.products_seeded} products
                  </span>
                ) : promotedSlug ? (
                  <span style={{ color: "var(--good)" }}>✓ storefront /{promotedSlug} created</span>
                ) : (
                  <button className="primary" onClick={promote}>
                    Create storefront + {drill.opportunities.length} products
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
