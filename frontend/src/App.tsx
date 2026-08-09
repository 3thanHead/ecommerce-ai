import { useEffect, useState } from "react";
import { api } from "./api";
import { Banner } from "./components";
import { Campaigns } from "./pages/Campaigns";
import { Chat } from "./pages/Chat";
import { Opportunities } from "./pages/Opportunities";
import { Review } from "./pages/Review";

type Tab = "opportunities" | "campaigns" | "review" | "chat";

export function App() {
  const [tab, setTab] = useState<Tab>("opportunities");
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [fleetErr, setFleetErr] = useState("");
  const [campaignRefresh, setCampaignRefresh] = useState(0);

  // Load the model list once — this is also the fleet health check.
  useEffect(() => {
    api
      .models()
      .then((m) => {
        setModels(m.models);
        // Only select the configured default if the fleet actually serves it --
        // otherwise the <select> shows the first option while silently sending a
        // model no node has, and every call comes back 503 from the balancer.
        setModel(m.models.includes(m.default) ? m.default : m.models[0] ?? "");
      })
      .catch((e) => setFleetErr(e.message));
  }, []);

  return (
    <div className="app">
      <header>
        <h1>
          <span className="brand">ecommerce</span>-ai
        </h1>
        <span className="model-badge">
          model
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {models.length === 0 && <option>{model || "…"}</option>}
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </span>
        <nav>
          {(["opportunities", "campaigns", "review", "chat"] as Tab[]).map((t) => (
            <button
              key={t}
              className={tab === t ? "active" : ""}
              onClick={() => setTab(t)}
            >
              {t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
        </nav>
      </header>

      {fleetErr && (
        <Banner>
          Can't reach the edge-ai fleet: {fleetErr}. Check OLLAMA_BASE_URL in .env.
        </Banner>
      )}

      {tab === "opportunities" && (
        <Opportunities model={model} onPromoted={() => setCampaignRefresh((n) => n + 1)} />
      )}
      {tab === "campaigns" && <Campaigns refreshKey={campaignRefresh} />}
      {tab === "review" && <Review model={model} />}
      {tab === "chat" && <Chat model={model} />}
    </div>
  );
}
