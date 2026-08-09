import { useEffect, useState } from "react";
import { api, Campaign, CampaignDetail, Product } from "../api";
import { Banner, Working } from "../components";
import { useJob } from "../useJob";

// The campaigns the agent's niches became. Expand one to see its products and
// resolve their CJ search seeds into real sourced products (Feature 2).
// Generating/reviewing social content for a resolved product happens on the
// Review tab, not here.
export function Campaigns({ refreshKey }: { refreshKey: number }) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<number | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .campaigns()
      .then(setCampaigns)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [refreshKey]);

  if (loading) return <div className="spinner">loading campaigns…</div>;
  if (err) return <Banner>{err}</Banner>;

  if (campaigns.length === 0)
    return (
      <div className="card muted">
        No campaigns yet. Hit <b>Find opportunities</b>, then <b>Automate</b> a
        niche to create one.
      </div>
    );

  return (
    <>
      {campaigns.map((c) => (
        <CampaignCard
          key={c.id}
          campaign={c}
          open={openId === c.id}
          onToggle={() => setOpenId(openId === c.id ? null : c.id)}
        />
      ))}
    </>
  );
}

function fmtPrice(p: number | null): string {
  return p == null ? "—" : `$${p.toFixed(2)}`;
}

function CampaignCard({
  campaign,
  open,
  onToggle,
}: {
  campaign: Campaign;
  open: boolean;
  onToggle: () => void;
}) {
  const [detail, setDetail] = useState<CampaignDetail | null>(null);
  const [err, setErr] = useState("");
  const resolveJob = useJob<{ products: Product[]; resolved: number }>();

  function load() {
    api.campaign(campaign.id).then(setDetail).catch((e) => setErr(e.message));
  }
  useEffect(() => {
    if (open && !detail) load();
  }, [open]);

  // The stream returns the fresh product list; use it the moment it lands.
  const products = resolveJob.result?.products ?? detail?.products ?? [];
  const unresolved = products.filter((p) => !p.cj_product_id).length;

  function resolve() {
    if (!resolveJob.running)
      resolveJob.run(`/api/campaigns/${campaign.id}/resolve/stream`, {});
  }

  return (
    <div className="card">
      <div
        className="row"
        style={{ justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}
        onClick={onToggle}
      >
        <div>
          <b>{campaign.name}</b>{" "}
          <span className="muted" style={{ fontSize: 12 }}>
            /{campaign.slug}
          </span>
          <div className="muted" style={{ fontSize: 13 }}>
            {campaign.audience}
          </div>
        </div>
        <div className="row" style={{ gap: 8, alignItems: "center" }}>
          <span className="pill">{campaign.status}</span>
          <span className="muted" style={{ fontSize: 13 }}>
            {campaign.product_count ?? products.length} products
          </span>
          <span className="muted">{open ? "▲" : "▼"}</span>
        </div>
      </div>

      {open && (
        <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          {err && <Banner>{err}</Banner>}

          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <label style={{ margin: 0 }}>
              Products {unresolved > 0 && <span className="muted">· {unresolved} unresolved</span>}
            </label>
            <button
              className="ghost"
              onClick={resolve}
              disabled={resolveJob.running || unresolved === 0}
              title="Match each product's CJ search seed to a real CJdropshipping product"
            >
              {resolveJob.running
                ? "Resolving…"
                : unresolved === 0
                  ? "All resolved"
                  : `Resolve ${unresolved} on CJ`}
            </button>
          </div>

          {(resolveJob.running || resolveJob.steps.length > 0) && (
            <Working steps={resolveJob.steps} thinking={resolveJob.thinking} />
          )}
          {resolveJob.error && <Banner>{resolveJob.error}</Banner>}

          <div className="product-grid">
            {products.map((p) => (
              <ProductCard key={p.id} product={p} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ProductCard({ product: p }: { product: Product }) {
  const img = p.images?.[0];
  const resolved = !!p.cj_product_id;
  return (
    <div className="product-card">
      <div
        style={{
          width: "100%",
          aspectRatio: "1",
          background: "var(--panel, #1a1a1a)",
          borderRadius: 6,
          overflow: "hidden",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 8,
        }}
      >
        {img ? (
          <img
            src={img}
            alt={p.title}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
            loading="lazy"
          />
        ) : (
          <span className="muted" style={{ fontSize: 12 }}>
            not sourced yet
          </span>
        )}
      </div>
      <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.3 }}>{p.title}</div>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginTop: 4 }}>
        <span style={{ color: resolved ? "var(--good)" : "var(--muted)" }}>
          {fmtPrice(p.price)}
        </span>
        {resolved ? (
          <span className="muted" style={{ fontSize: 11 }} title={`CJ ${p.cj_product_id}`}>
            {p.images.length} imgs{p.videos.length ? " · video" : ""}
          </span>
        ) : (
          <span className="pill muted" style={{ fontSize: 11 }}>
            candidate
          </span>
        )}
      </div>
    </div>
  );
}
