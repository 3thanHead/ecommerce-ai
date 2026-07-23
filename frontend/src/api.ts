// One tiny fetch wrapper. Everything is a relative /api call so it works the
// same in dev (Vite proxy) and prod (served by FastAPI).

export type Candidate = {
  name: string;
  audience: string;
  rationale: string;
  demand: number;
  saturation: number;
  saturation_reasoning: string;
  example_products: string[];
  keywords: string[];
};

export type Thread = {
  id: string;
  title: string;
  subreddit: string;
  score: number;
  num_comments: number;
  permalink: string;
};

export type ResearchResult = {
  run_id: number;
  prompt: string;
  audience: string;
  model: string;
  reddit_source: string; // direct | discovery | none
  summary: string;
  candidates: Candidate[];
  threads_sampled: Thread[];
  keywords: { phrase: string; freq: number }[];
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
  research: (prompt: string, audience: string, model?: string) =>
    req<ResearchResult>("/api/research", {
      method: "POST",
      body: JSON.stringify({ prompt, audience, model }),
    }),
  runs: () =>
    req<{ id: number; prompt: string; audience: string; candidates: number }[]>(
      "/api/research",
    ),
  getRun: (id: number) => req<ResearchResult>(`/api/research/${id}`),
  promote: (run_id: number, candidate_index: number) =>
    req<{ niche_id: number; storefront_id: number | null }>(
      "/api/research/promote",
      {
        method: "POST",
        body: JSON.stringify({ run_id, candidate_index, create_storefront: true }),
      },
    ),
  storefronts: () => req<Storefront[]>("/api/storefronts"),
  storefront: (id: number) => req<any>(`/api/storefronts/${id}`),
};
