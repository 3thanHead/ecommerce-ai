// One tiny fetch wrapper. Everything is a relative /api call so it works the
// same in dev (Vite proxy) and prod (served by FastAPI).

export type Opportunity = {
  product: string;
  rationale: string;
  evidence: string[];
  cj_search_seed: string;
  demand_signal: number;
};

export type Thread = {
  id: string;
  title: string;
  subreddit: string;
  score: number;
  permalink: string;
};

export type Keyword = { phrase: string; freq: number };

export type Drill = {
  category: string;
  reddit_source: string; // direct | discovery | none
  saturation: number;
  saturation_reasoning: string;
  opportunities: Opportunity[];
  keywords: Keyword[];
  threads_sampled: Thread[];
};

export type Category = {
  name: string;
  audience: string;
  saturation: number;
  saturation_reasoning: string;
  angle: string;
  keyword_seed?: string;
  subreddits: string[];
  drill?: Drill;
};

// One SSE frame from a streaming endpoint (see app/progress.py).
export type SSEEvent =
  | { type: "step"; name: string; status: "running" | "done" }
  | { type: "thought"; text: string }
  | { type: "result"; data: any }
  | { type: "error"; message: string };

// POST + read a text/event-stream response, invoking onEvent per frame.
export async function stream(
  path: string,
  body: unknown,
  onEvent: (e: SSEEvent) => void,
): Promise<void> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok || !r.body) throw new Error(`${r.status} ${r.statusText}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)));
    }
  }
}

export type ScoutResult = {
  run_id: number;
  theme: string;
  model: string;
  categories: Category[];
};

export type Storefront = {
  id: number;
  slug: string;
  name: string;
  category: string;
  audience: string;
  description: string;
  status: string;
  product_count?: number;
};

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail || `${r.status} ${r.statusText}`);
  }
  return r.json();
}

export const api = {
  models: () =>
    req<{ default: string; models: string[]; base_url: string }>("/api/models"),
  chat: (messages: { role: string; content: string }[], model?: string) =>
    req<{ reply: string; model: string }>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ messages, model }),
    }),

  // Stage 1: the button -> ranked category leaderboard.
  scout: (theme: string, model?: string, n = 12) =>
    req<ScoutResult>("/api/opportunities", {
      method: "POST",
      body: JSON.stringify({ theme, model, n }),
    }),
  // Stage 2: drill one category into Reddit -> product opportunities.
  drill: (run_id: number, category_index: number, model?: string) =>
    req<Drill>("/api/opportunities/drill", {
      method: "POST",
      body: JSON.stringify({ run_id, category_index, model }),
    }),
  // Category -> storefront (+ seeded product candidates if drilled).
  promote: (run_id: number, category_index: number) =>
    req<{ storefront_id: number; slug: string; products_seeded: number }>(
      "/api/opportunities/promote",
      {
        method: "POST",
        body: JSON.stringify({ run_id, category_index }),
      },
    ),

  storefronts: () => req<Storefront[]>("/api/storefronts"),
};
