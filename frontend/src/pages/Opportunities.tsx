import { useState } from "react";
import { api, Category, Drill, ScoutResult } from "../api";
import { Banner, Meter } from "../components";

// The whole flow on one screen: hit the button -> categories ranked least
// saturated first -> drill any one into Reddit -> promote to a storefront.
export function Opportunities({
  model,
  onPromoted,
}: {
  model: string;
  onPromoted: () => void;
}) {
  const [theme, setTheme] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [scout, setScout] = useState<ScoutResult | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [drills, setDrills] = useState<Record<number, Drill>>({});
  const [drilling, setDrilling] = useState<number | null>(null);
  const [promoted, setPromoted] = useState<Record<number, string>>({});

  async function find() {
    if (busy) return;
    setBusy(true);
    setErr("");
    setScout(null);
    setDrills({});
    setPromoted({});
    setOpen(null);
    try {
      setScout(await api.scout(theme, model));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function drill(i: number) {
    if (!scout) return;
    setOpen(open === i ? null : i);
    if (drills[i] || drilling !== null) return;
    setDrilling(i);
    setErr("");
    try {
      const d = await api.drill(scout.run_id, i, model);
      setDrills((prev) => ({ ...prev, [i]: d }));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setDrilling(null);
    }
  }

  async function promote(i: number) {
    if (!scout) return;
    try {
      const r = await api.promote(scout.run_id, i);
      setPromoted((p) => ({ ...p, [i]: r.slug }));
      onPromoted();
    } catch (e: any) {
      setErr(e.message);
    }
  }

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
          <button className="primary" onClick={find} disabled={busy}>
            {busy ? "Scouting…" : "Find opportunities"}
          </button>
        </div>
        {busy && (
          <div className="spinner" style={{ marginTop: 10 }}>
            {model} is ranking categories by saturation…
          </div>
        )}
        {!scout && !busy && (
          <p className="muted" style={{ marginBottom: 0 }}>
            Ranked least-saturated first. Click a category to drill into Reddit
            for concrete products to source.
          </p>
        )}
      </div>

      {err && <Banner>{err}</Banner>}

      {scout &&
        scout.categories.map((c: Category, i: number) => {
          const d = drills[i];
          const isOpen = open === i;
          return (
            <div className="card" key={i}>
              <div
                className="row"
                style={{ justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}
                onClick={() => drill(i)}
              >
                <div style={{ flex: 1 }}>
                  <div className="row" style={{ alignItems: "center", gap: 14 }}>
                    <Meter label="saturation" value={d ? d.saturation : c.saturation} invert />
                    <h3 style={{ margin: 0, fontSize: 16 }}>{c.name}</h3>
                  </div>
                  <div className="muted" style={{ fontSize: 13, marginTop: 4 }}>
                    {c.audience}
                  </div>
                </div>
                <div className="muted" style={{ fontSize: 12 }}>
                  {c.subreddits.slice(0, 3).map((s) => (
                    <span className="pill" key={s}>
                      r/{s}
                    </span>
                  ))}
                  <span style={{ marginLeft: 8 }}>{isOpen ? "▲" : "▼ drill"}</span>
                </div>
              </div>

              {isOpen && (
                <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
                  <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
                    <b>Angle:</b> {c.angle}
                  </p>

                  {drilling === i && <div className="spinner">reading Reddit + reasoning…</div>}

                  {d && (
                    <>
                      <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
                        {d.reddit_source === "none" ? (
                          <span style={{ color: "var(--warn)" }}>
                            ⚠ Reddit unreachable — opportunities from category
                            reasoning only. Add a Reddit script app for grounded results.
                          </span>
                        ) : (
                          <>grounded in {d.threads_sampled.length} Reddit threads ({d.reddit_source})</>
                        )}
                      </div>

                      {d.opportunities.map((o, j) => (
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

                      <div style={{ marginTop: 12 }}>
                        <button
                          className="primary"
                          disabled={!!promoted[i]}
                          onClick={() => promote(i)}
                        >
                          {promoted[i]
                            ? `✓ storefront /${promoted[i]} created`
                            : `Create storefront + ${d.opportunities.length} products`}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
    </>
  );
}
