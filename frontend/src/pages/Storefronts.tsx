import { useEffect, useState } from "react";
import { api, Product, Storefront, StorefrontDetail } from "../api";
import { Banner, Working } from "../components";
import { useJob } from "../useJob";

// The stores the agent's niches became. Expand one to see its products and
// resolve their CJ search seeds into real sourced products (Feature 2).
export function Storefronts({ refreshKey }: { refreshKey: number }) {
  const [stores, setStores] = useState<Storefront[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<number | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .storefronts()
      .then(setStores)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [refreshKey]);

  if (loading) return <div className="spinner">loading storefronts…</div>;
  if (err) return <Banner>{err}</Banner>;

  if (stores.length === 0)
    return (
      <div className="card muted">
        No storefronts yet. Hit <b>Find opportunities</b>, then <b>Automate</b> a
        niche to create one.
      </div>
    );

  return (
    <>
      {stores.map((s) => (
        <StoreCard
          key={s.id}
          store={s}
          open={openId === s.id}
          onToggle={() => setOpenId(openId === s.id ? null : s.id)}
        />
      ))}
    </>
  );
}

function fmtPrice(p: number | null): string {
  return p == null ? "—" : `$${p.toFixed(2)}`;
}

function StoreCard({
  store,
  open,
  onToggle,
}: {
  store: Storefront;
  open: boolean;
  onToggle: () => void;
}) {
  const [detail, setDetail] = useState<StorefrontDetail | null>(null);
  const [err, setErr] = useState("");
  const resolveJob = useJob<{ products: Product[]; resolved: number }>();
  const genJob = useJob<{ slug: string; url: string; tagline: string }>();

  function load() {
    api.storefront(store.id).then(setDetail).catch((e) => setErr(e.message));
  }
  useEffect(() => {
    if (open && !detail) load();
  }, [open]);

  // The stream returns the fresh product list; use it the moment it lands.
  const products = resolveJob.result?.products ?? detail?.products ?? [];
  const unresolved = products.filter((p) => !p.cj_product_id).length;
  const resolvedCount = products.length - unresolved;
  const generated = !!genJob.result;

  function resolve() {
    if (!resolveJob.running)
      resolveJob.run(`/api/storefronts/${store.id}/resolve/stream`, {});
  }
  function generate() {
    if (!genJob.running)
      genJob.run(`/api/storefronts/${store.id}/generate/stream`, {});
  }

  return (
    <div className="card">
      <div
        className="row"
        style={{ justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}
        onClick={onToggle}
      >
        <div>
          <b>{store.name}</b>{" "}
          <span className="muted" style={{ fontSize: 12 }}>
            /{store.slug}
          </span>
          <div className="muted" style={{ fontSize: 13 }}>
            {store.audience}
          </div>
        </div>
        <div className="row" style={{ gap: 8, alignItems: "center" }}>
          <span className="pill">{store.status}</span>
          <span className="muted" style={{ fontSize: 13 }}>
            {store.product_count ?? products.length} products
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
            <div className="row" style={{ gap: 8 }}>
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
              <button
                className="primary"
                onClick={generate}
                disabled={genJob.running || resolvedCount === 0}
                title={resolvedCount === 0 ? "Resolve products first" : "Write store copy + build the storefront page"}
              >
                {genJob.running ? "Generating…" : generated ? "Regenerate store" : "Generate store"}
              </button>
              {(generated || store.status === "active") && (
                <a
                  className="pill"
                  href={`/store/${store.slug}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{ borderColor: "var(--good)", color: "var(--good)" }}
                >
                  View store ↗
                </a>
              )}
            </div>
          </div>

          {(resolveJob.running || resolveJob.steps.length > 0) && (
            <Working steps={resolveJob.steps} thinking={resolveJob.thinking} />
          )}
          {resolveJob.error && <Banner>{resolveJob.error}</Banner>}
          {(genJob.running || genJob.steps.length > 0) && (
            <Working steps={genJob.steps} thinking={genJob.thinking} />
          )}
          {genJob.error && <Banner>{genJob.error}</Banner>}
          {generated && (
            <div className="muted" style={{ fontSize: 13, marginBottom: 10 }}>
              ✓ “{genJob.result!.tagline}” —{" "}
              <a href={genJob.result!.url} target="_blank" rel="noreferrer">
                open the live store ↗
              </a>
            </div>
          )}

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
