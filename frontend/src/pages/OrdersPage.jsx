import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { apiError } from "../api/client";
import OrderTracker from "../components/ui/OrderTracker";
import StatusPill from "../components/ui/StatusPill";
import { EmptyState, ErrorState } from "../components/ui/States";
import { formatPaise } from "../utils/money";
import { STATUS_LABELS } from "./OrderPage";

export default function OrdersPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    setError("");
    api.get("/orders/").then((res) => setData(res.data)).catch((err) => setError(apiError(err).message));
  }, [reload]);
  return (
    <main className="container py-4" style={{ maxWidth: 820 }}>
      <h1 className="h3 mb-1">My orders</h1>
      <p className="text-muted mb-4">Track each order from placement to delivery.</p>
      {error && <ErrorState message={error} onRetry={() => setReload((n) => n + 1)} />}
      {!data && !error && <div className="d-grid gap-3" aria-busy="true">{[0, 1, 2].map((i) => <div key={i} className="mq-skeleton" style={{ height: 130 }} />)}</div>}
      {data && data.results.length === 0 && (
        <EmptyState icon="box" title="No orders yet" action={<Link to="/shop" className="btn btn-primary">Browse the shop</Link>}>
          When you place an order it will show up here.
        </EmptyState>
      )}
      <div className="d-grid gap-3">
        {data?.results.map((o) => {
          const [color, label] = STATUS_LABELS[o.status] || ["secondary", o.status];
          return (
            <div key={o.id} className="card p-3 mq-card-hover">
              <div className="d-flex justify-content-between align-items-start gap-3 mb-3">
                <div>
                  <Link to={`/orders/${o.id}`} className="fw-bold text-decoration-none">{o.order_number}</Link>
                  <div className="small text-muted">{new Date(o.created_at).toLocaleString("en-IN")} · {o.lines.length} item type{o.lines.length === 1 ? "" : "s"}</div>
                </div>
                <div className="text-end">
                  <div className="fw-bold">{formatPaise(o.total_paise)}</div>
                  <StatusPill color={color} label={label} />
                </div>
              </div>
              <OrderTracker status={o.status} />
            </div>
          );
        })}
      </div>
    </main>
  );
}
