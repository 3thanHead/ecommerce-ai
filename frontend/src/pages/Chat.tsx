import { useState } from "react";
import { api } from "../api";
import { Banner } from "../components";

// The smallest thing that proves the edge-ai connection: pick a model, talk to it.
export function Chat({ model }: { model: string }) {
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function send() {
    if (!input.trim() || busy) return;
    const next = [...messages, { role: "user", content: input }];
    setMessages(next);
    setInput("");
    setBusy(true);
    setErr("");
    try {
      const { reply } = await api.chat(next, model);
      setMessages([...next, { role: "assistant", content: reply }]);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <p className="muted" style={{ marginTop: 0 }}>
        Talking to <b>{model}</b> on the edge-ai fleet.
      </p>
      {err && <Banner>{err}</Banner>}
      <div className="chat-log">
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.content}
          </div>
        ))}
        {busy && <div className="spinner">thinking…</div>}
      </div>
      <div className="row">
        <textarea
          style={{ flex: 1 }}
          value={input}
          placeholder="Ask anything…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
          }}
        />
      </div>
      <div style={{ marginTop: 10 }}>
        <button className="primary" onClick={send} disabled={busy}>
          Send <span className="muted" style={{ fontWeight: 400 }}>(⌘/Ctrl+Enter)</span>
        </button>
      </div>
    </div>
  );
}
