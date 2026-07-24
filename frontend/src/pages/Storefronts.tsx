import { useEffect, useState } from "react";
import { api, Storefront } from "../api";
import { Banner } from "../components";

// The stores the agent's categories became. Products (Feature 2) will hang here.
export function Storefronts({ refreshKey }: { refreshKey: number }) {
  const [stores, setStores] = useState<Storefront[]>([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

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
        No storefronts yet. Run a niche <b>Research</b> and promote a candidate to
        create one.
      </div>
    );

  return (
    <div className="card">
      <table>
        <thead>
          <tr>
            <th>Store</th>
            <th>Audience</th>
            <th>Status</th>
            <th>Products</th>
          </tr>
        </thead>
        <tbody>
          {stores.map((s) => (
            <tr key={s.id}>
              <td>
                <b>{s.name}</b>
                <div className="muted" style={{ fontSize: 12 }}>
                  /{s.slug}
                </div>
              </td>
              <td className="muted">{s.audience}</td>
              <td>
                <span className="pill">{s.status}</span>
              </td>
              <td>{s.product_count ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
