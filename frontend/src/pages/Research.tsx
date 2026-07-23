import { useState } from "react";
import { api, Candidate, ResearchResult } from "../api";
import { Banner, Meter } from "../components";

// Run the niche agent, read its candidates + saturation reasoning, and promote
// the good ones into storefronts.
export function Research({ model, onPromoted }: { model: string; onPromoted: () => void }) {
  const [prompt, setPrompt] = useState("");
  const [audience, setAudience] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [promoted, setPromoted] = useState<Record<number, boolean>>({});

  async function run() {
    if (!prompt.trim() || busy) return;
    setBusy(true);
    setErr("");
    setResult(null);
    setPromoted({});
    try {
      setResult(await api.research(prompt, audience, model));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function promote(i: number) {
    if (!result) return;
    try {
      await api.promote(result.run_id, i);
      setPromoted((p) => ({ ...p, [i]: true }));
      onPromoted();
    } catch (e: any) {
      setErr(e.message);
    }
  }

  return (
    <>
      <div className="card">
        <div className="row">
          <div style={{ flex: 2, minWidth: 240 }}>
            <label>Category or prompt</label>
            <input
              value={prompt}
              placeholder="e.g. cozy desk decor for remote workers"
              onChange={(e) => setPrompt(e.target.value)}
            />
          </div>
          <div style={{ flex: 1, minWidth: 180 }}>
            <label>Target audience (optional)</label>
            <input
              value={audience}
              placeholder="work-from-home millennials"
              onChange={(e) => setAudience(e.target.value)}
            />
          </div>
        </div>
        <div style={{ marginTop: 12 }}>
          <button className="primary" onClick={run} disabled={busy}>
            {busy ? "Researching…" : "Research niches"}
          </button>
          {busy && (
            <span className="spinner" style={{ marginLeft: 12 }}>
              Reddit + keywords + {model}… (up to ~2 min)
            </span>
          )}
        </div>
      </div>

      {err && <Banner>{err}</Banner>}

      {result && (
        <>
          <div className="card">
            <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
              run #{result.run_id} · model {result.model} · reddit via{" "}
              <b>{result.reddit_source}</b>
              {result.reddit_source === "discovery" &&
                " (keyless page-read — thread scores unavailable)"}
            </div>
            <p style={{ margin: 0 }}>{result.summary}</p>
          </div>

          {result.candidates.map((c: Candidate, i: number) => (
            <div className="card candidate" key={i}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h3>{c.name}</h3>
                <button
                  className="ghost"
                  disabled={promoted[i]}
                  onClick={() => promote(i)}
                >
                  {promoted[i] ? "✓ storefront created" : "Promote → storefront"}
                </button>
              </div>
              <div className="muted">{c.audience}</div>
              <div className="scores">
                <Meter label="demand" value={c.demand} />
                <Meter label="saturation" value={c.saturation} invert />
              </div>
              <p>{c.rationale}</p>
              <p className="muted" style={{ fontSize: 13 }}>
                <b>Saturation:</b> {c.saturation_reasoning}
              </p>
              <div>
                <label>Example products to source (CJdropshipping)</label>
                {c.example_products.map((p, j) => (
                  <span className="pill" key={j}>
                    {p}
                  </span>
                ))}
              </div>
              <div style={{ marginTop: 8 }}>
                <label>Target keywords</label>
                {c.keywords.map((k, j) => (
                  <span className="pill" key={j}>
                    {k}
                  </span>
                ))}
              </div>
            </div>
          ))}

          {result.threads_sampled.length > 0 && (
            <div className="card">
              <label>Reddit threads sampled ({result.threads_sampled.length})</label>
              {result.threads_sampled.map((t) => (
                <div className="thread" key={t.id}>
                  <a href={t.permalink} target="_blank" rel="noreferrer">
                    r/{t.subreddit}
                  </a>{" "}
                  {t.score > 0 && <span className="muted">[{t.score} pts] </span>}
                  {t.title}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </>
  );
}
