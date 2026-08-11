import { useEffect, useState } from "react";
import { api, Campaign, ContentAsset, Product } from "../api";
import { Banner } from "../components";

// The staging queue: generate an image + caption for a resolved product,
// then approve or reject each piece before it's anything more than a draft.
// Nothing here posts anywhere yet (Phase 5 wires an approval to Postiz).
export function Review({ model }: { model: string }) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [campaignId, setCampaignId] = useState<number | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [content, setContent] = useState<ContentAsset[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .campaigns()
      .then((cs) => {
        setCampaigns(cs);
        setCampaignId((prev) => prev ?? cs[0]?.id ?? null);
      })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, []);

  function refresh() {
    if (campaignId == null) return;
    api.campaign(campaignId).then((d) => setProducts(d.products)).catch((e) => setErr(e.message));
    api.content(campaignId).then(setContent).catch((e) => setErr(e.message));
  }
  useEffect(refresh, [campaignId]);

  if (loading) return <div className="spinner">loading…</div>;
  if (campaigns.length === 0)
    return (
      <div className="card muted">
        No campaigns yet. Build one from the <b>Opportunities</b> tab first.
      </div>
    );

  const resolved = products.filter((p) => p.cj_product_id);

  return (
    <>
      <div className="card">
        <label>Campaign</label>
        <select
          value={campaignId ?? ""}
          onChange={(e) => setCampaignId(Number(e.target.value))}
        >
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.product_count ?? 0} products)
            </option>
          ))}
        </select>
      </div>

      {err && <Banner>{err}</Banner>}

      {resolved.length === 0 ? (
        <div className="card muted">
          No resolved products in this campaign yet — resolve some on the{" "}
          <b>Campaigns</b> tab first.
        </div>
      ) : (
        resolved.map((p) => (
          <ProductRow
            key={p.id}
            product={p}
            campaignId={campaignId!}
            model={model}
            assets={content.filter((a) => a.product_id === p.id)}
            onChanged={refresh}
          />
        ))
      )}
    </>
  );
}

function ProductRow({
  product,
  campaignId,
  model,
  assets,
  onChanged,
}: {
  product: Product;
  campaignId: number;
  model: string;
  assets: ContentAsset[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<"image" | "caption" | "both" | null>(null);
  const [err, setErr] = useState("");

  async function generate(kind: "image" | "caption" | "both") {
    setBusy(kind);
    setErr("");
    try {
      const calls = [];
      if (kind === "image" || kind === "both")
        calls.push(api.generateImageAsset(campaignId, product.id));
      if (kind === "caption" || kind === "both")
        calls.push(api.generateCaptionAsset(campaignId, product.id, model));
      const results = await Promise.allSettled(calls);
      const failed = results.find((r) => r.status === "rejected") as
        | PromiseRejectedResult
        | undefined;
      if (failed) throw failed.reason;
      onChanged();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <div className="row" style={{ gap: 10, alignItems: "center" }}>
          {product.images?.[0] && (
            <img
              src={product.images[0]}
              alt={product.title}
              style={{ width: 44, height: 44, borderRadius: 6, objectFit: "cover" }}
            />
          )}
          <b style={{ fontSize: 14 }}>{product.title}</b>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <button className="ghost" onClick={() => generate("image")} disabled={!!busy}>
            {busy === "image" ? "Generating…" : "+ image"}
          </button>
          <button className="ghost" onClick={() => generate("caption")} disabled={!!busy}>
            {busy === "caption" ? "Generating…" : "+ caption"}
          </button>
          <button className="primary" onClick={() => generate("both")} disabled={!!busy}>
            {busy === "both" ? "Generating…" : "Generate content"}
          </button>
        </div>
      </div>

      {err && <Banner>{err}</Banner>}

      {assets.length > 0 && (
        <div style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
          {assets.map((a) => (
            <AssetRow key={a.id} asset={a} onChanged={onChanged} />
          ))}
        </div>
      )}
    </div>
  );
}

function AssetRow({ asset, onChanged }: { asset: ContentAsset; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);

  async function act(fn: (id: number) => Promise<ContentAsset>) {
    setBusy(true);
    try {
      await fn(asset.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  const statusColor =
    asset.status === "approved"
      ? "var(--good)"
      : asset.status === "rejected"
        ? "var(--bad, #f88)"
        : "var(--warn)";

  return (
    <div className="thread" style={{ paddingBottom: 10 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="row" style={{ gap: 8, alignItems: "center" }}>
            <span className="pill">{asset.kind}</span>
            <span className="pill" style={{ borderColor: statusColor, color: statusColor }}>
              {asset.status.replace("_", " ")}
            </span>
          </div>
          {asset.kind === "image" && asset.asset_url ? (
            <img
              src={asset.asset_url}
              alt=""
              style={{ width: 120, height: 120, objectFit: "cover", borderRadius: 6, marginTop: 6 }}
            />
          ) : (
            <div style={{ fontSize: 13, marginTop: 6, whiteSpace: "pre-wrap" }}>{asset.text}</div>
          )}
        </div>
        {asset.status === "pending_review" && (
          <div className="row" style={{ gap: 6, flexShrink: 0 }}>
            <button className="ghost" disabled={busy} onClick={() => act(api.rejectContent)}>
              Reject
            </button>
            <button className="primary" disabled={busy} onClick={() => act(api.approveContent)}>
              Approve
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
