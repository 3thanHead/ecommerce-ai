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

export type Post = {
  subreddit: string;
  title: string;
  score: number;
  num_comments: number;
  domain: string;
};

export type SubredditProfile = {
  name: string;
  subscribers: number;
  submission_type: string; // any | link | self
  description: string;
  exists: boolean;
  posts: number;
  sample_titles: string[];
  product_friendly: "yes" | "limited" | "no";
  reason: string;
};

export type Drill = {
  category: string;
  reddit_source: string; // pullpush+arctic | arctic-only | model-only
  saturation: number;
  saturation_reasoning: string;
  saturation_method: "measured" | "estimated";
  saturation_supply: Record<string, number>; // {provider: listing count}
  saturation_demand: number;
  subreddits: SubredditProfile[];
  opportunities: Opportunity[];
  keywords: Keyword[];
  posts_sampled: Post[];
};

// A real CJdropshipping product, straight off their catalog — the atom the whole
// flow is built from. `listings` is how many CJ sellers already list this exact
// product: the competition signal saturation is derived from.
export type CJProduct = {
  pid: string;
  title: string;
  price: number | null;
  image: string;
  listings: number;
  category: string;
  category_path: string;
  saturation: number;
  demand?: number | null;
  opportunity?: number;
  band?: "open" | "crowded";
};

// A campaign concept: real products grouped into one social-content push.
export type Category = {
  name: string;
  audience: string;
  angle: string;
  keyword_seed?: string;
  subreddits: string[];
  products: CJProduct[];
  drill?: Drill;
  saturation: number;
  saturation_reasoning?: string;
  saturation_method?: "measured" | "estimated";
  saturation_supply?: Record<string, number>;
  listings?: number;            // mean CJ sellers per product in this concept
  supply_count?: number | null;
  demand?: number | null;       // 0-100 buyer-intent breadth (Google Suggest)
  opportunity?: number;         // demand × low-saturation — the ranking score
  band?: "open" | "crowded";
  category_paths?: string[];    // the CJ aisles its products came from
  price_range?: [number, number] | null;
};

// What the scan actually cost and turned up (the funnel above the board).
export type Scan = {
  scanned: number;            // real CJ products looked at
  categories_scanned: number; // CJ leaf categories hunted in
  grounds: string[];          // which ones
  open?: number;              // products under the saturation ceiling
  crowded?: number;
  kept?: number;              // products that made it into a concept
  concepts?: number;
  requested?: number;         // n asked for
  measured: boolean;
  median_listings?: number;
  max_saturation: number;
};

// One SSE frame from a streaming endpoint (see app/progress.py).
export type SSEEvent =
  | { type: "step"; name: string; status: "running" | "done"; key?: string }
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
  categories: Category[]; // campaign concepts, best opportunity first
  scan?: Scan;
  error?: string;
};

export type Campaign = {
  id: number;
  slug: string;
  name: string;
  category: string;
  audience: string;
  description: string;
  status: string;
  product_count?: number;
};

// A product candidate; the CJ fields (cj_product_id, price, images…) fill in
// once Feature 2 resolves its search seed.
export type Product = {
  id: number;
  campaign_id: number | null;
  title: string;
  description: string;
  cj_product_id: string;
  price: number | null;
  images: string[];
  videos: string[];
  source: string;
  status: string;
};

export type CampaignDetail = Campaign & { products: Product[] };

// One generated piece staged for review -- an image, a video (roadmap), or a
// caption -- tied to a product. Approving an image also lands it on the
// product's gallery (backend/api/content.py).
export type ContentAsset = {
  id: number;
  campaign_id: number;
  product_id: number;
  kind: "image" | "video" | "caption";
  status: "pending_review" | "approved" | "rejected" | "posted";
  target_platform: string;
  prompt: string;
  text: string;
  asset_url: string;
  comfy_workflow: string;
  created_at: string;
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

  // Stage 1: scan real CJ products, keep the n best campaign concepts.
  scout: (theme: string, model?: string, n = 8, pool = 0) =>
    req<ScoutResult>("/api/opportunities", {
      method: "POST",
      body: JSON.stringify({ theme, model, n, pool }),
    }),
  // Stage 2: drill one concept into Reddit -> audience + product opportunities.
  drill: (run_id: number, category_index: number, model?: string) =>
    req<Drill>("/api/opportunities/drill", {
      method: "POST",
      body: JSON.stringify({ run_id, category_index, model }),
    }),
  // Category -> campaign (+ seeded product candidates if drilled).
  promote: (run_id: number, category_index: number) =>
    req<{ campaign_id: number; slug: string; products_seeded: number }>(
      "/api/opportunities/promote",
      {
        method: "POST",
        body: JSON.stringify({ run_id, category_index }),
      },
    ),

  campaigns: () => req<Campaign[]>("/api/campaigns"),
  campaign: (id: number) => req<CampaignDetail>(`/api/campaigns/${id}`),

  // Staging/review queue.
  content: (campaignId: number) =>
    req<ContentAsset[]>(`/api/campaigns/${campaignId}/content`),
  generateImageAsset: (campaignId: number, productId: number) =>
    req<ContentAsset>(`/api/campaigns/${campaignId}/products/${productId}/content/image`, {
      method: "POST",
    }),
  generateCaptionAsset: (campaignId: number, productId: number, model?: string) =>
    req<ContentAsset>(`/api/campaigns/${campaignId}/products/${productId}/content/caption`, {
      method: "POST",
      body: JSON.stringify({ model }),
    }),
  approveContent: (assetId: number) =>
    req<ContentAsset>(`/api/content/${assetId}/approve`, { method: "POST" }),
  rejectContent: (assetId: number) =>
    req<ContentAsset>(`/api/content/${assetId}/reject`, { method: "POST" }),
};
