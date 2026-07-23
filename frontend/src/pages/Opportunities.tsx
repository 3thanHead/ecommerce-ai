import { useState } from "react";
import { api, Category, Drill, ScoutResult } from "../api";
import { Banner, Meter, Working } from "../components";
import { useJob } from "../useJob";

function fmt(n: number): string {
  return n >= 1000 ? (n / 1000).toFixed(n >= 100000 ? 0 : 1) + "k" : String(n);
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
  const scout = useJob<ScoutResult>();

  function find() {
    if (!scout.running) scout.run("/api/opportunities/stream", { theme, model, n: 12 });
  }

  const result = scout.result;

  return (
    <>
      <div className="card">
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <label>Theme (optional — leave blank to range broadly)</label>
            <input
              value={theme}
              placeholder="e.g. pet stuff, outdoor gear, desk setups…"
              onChange={(e) => setTheme(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && find()}
            />
          </div>
          <button className="primary" onClick={find} disabled={scout.running}>
            {scout.running ? "Scouting…" : "Find opportunities"}
          </button>
        </div>
        {(scout.running || (!result && scout.steps.length > 0)) && (
          <div style={{ marginTop: 12 }}>
            <Working steps={scout.steps} thinking={scout.thinking} />
          </div>
        )}
        {!result && !scout.running && scout.steps.length === 0 && (
          <p className="muted" style={{ marginBottom: 0 }}>
            Ranked least-saturated first. Drill a category into Reddit for products
            to source, or hit <b>Automate</b> to build its storefront in one go.
          </p>
        )}
      </div>

      {scout.error && <Banner>{scout.error}</Banner>}

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

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ flex: 1 }}>
          <div className="row" style={{ alignItems: "center", gap: 14 }}>
            <Meter label="saturation" value={sat} invert />
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
              <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
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
