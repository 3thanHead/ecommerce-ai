import { useEffect, useState } from "react";
import { api } from "./api";
import { Banner } from "./components";
import { Chat } from "./pages/Chat";
import { Research } from "./pages/Research";
import { Storefronts } from "./pages/Storefronts";

type Tab = "research" | "storefronts" | "chat";

export function App() {
  const [tab, setTab] = useState<Tab>("research");
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState("");
  const [fleetErr, setFleetErr] = useState("");
  const [storeRefresh, setStoreRefresh] = useState(0);

  // Load the model list once — this is also the fleet health check.
  useEffect(() => {
    api
      .models()
      .then((m) => {
        setModels(m.models);
        setModel(m.default);
      })
      .catch((e) => setFleetErr(e.message));
  }, []);

  return (
    <div className="app">
      <header>
        <h1>
          <span className="brand">storefront</span>-ai
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
          {(["research", "storefronts", "chat"] as Tab[]).map((t) => (
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

      {tab === "research" && (
        <Research model={model} onPromoted={() => setStoreRefresh((n) => n + 1)} />
      )}
      {tab === "storefronts" && <Storefronts refreshKey={storeRefresh} />}
      {tab === "chat" && <Chat model={model} />}
    </div>
  );
}
