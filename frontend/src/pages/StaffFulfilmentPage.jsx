import { useCallback, useEffect, useState } from "react";
import api, { apiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { RETURN_REASONS } from "../components/ReturnsSection";
import { formatPaise } from "../utils/money";

const FULFIL_ROLES = ["pharmacy_manager", "admin"];

export default function StaffFulfilmentPage() {
  const { user } = useAuth();
  const canFulfil = FULFIL_ROLES.includes(user.role);
  const [orders, setOrders] = useState([]);
  const [returns, setReturns] = useState([]);
  const [refunds, setRefunds] = useState([]);
  const [notes, setNotes] = useState({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [partners, setPartners] = useState([]);
  const [pick, setPick] = useState({});

  const load = useCallback(() => {
    api.get("/staff/returns/?status=requested").then((r) => setReturns(r.data.results)).catch(() => {});
    if (canFulfil) {
      api.get("/staff/orders/").then((r) => setOrders(r.data.results)).catch(() => {});
      api.get("/staff/delivery/partners/").then((r) => setPartners(r.data.results)).catch(() => {});
      api.get("/staff/refunds/").then((r) => setRefunds(r.data.results)).catch(() => {});
    }
  }, [canFulfil]);
  useEffect(load, [load]);

  async function run(fn, okText) {
    setBusy(true);
    setMessage("");
    try { await fn(); setMessage(okText); } catch (err) { setMessage(apiError(err).message); }
    setBusy(false);
    load();
  }

  return (
    <main className="container py-4" style={{ maxWidth: 960 }}>
      <div className="mb-4">
        <h1 className="h3 mb-1">Fulfilment, returns and refunds</h1>
        <p className="text-muted mb-0">{canFulfil ? "Hand over paid orders, decide returns and retry failed refunds." : "Review customer return requests."}</p>
      </div>
      <div className="alert alert-warning small">
        <strong>Delivery partners</strong> are our own staff accounts, not a courier service. Assign one and they pick up and hand over with the
        customer's code. "Mark dispatched/delivered" is a manual override that skips the code. Mock payments move no real money.
      </div>
      {message && <div className="alert alert-info py-2">{message}</div>}

      {canFulfil && (
        <section className="mb-4">
          <h2 className="h5 mb-3">Paid orders to hand over</h2>
          {orders.length === 0 && <div className="card card-body small text-muted">No paid orders are waiting.</div>}
          {orders.map((o) => (
            <div key={o.id} className="card card-body mb-3 small mq-card-hover">
              <div className="d-flex justify-content-between flex-wrap gap-2">
                <div>
                  <strong>{o.order_number}</strong> <span className="mq-pill mq-pill--info">{o.status.replace(/_/g, " ")}</span>
                  <div>{o.lines.map((l) => `${l.name} x ${l.quantity}`).join(", ")}</div>
                  <div className="text-muted">{o.address.recipient_name}, {o.address.line1}, {o.address.city} {o.address.pincode}</div>
                </div>
                <div>
                  {o.status === "delivery_failed" && (
                    <div className="d-flex flex-column gap-1">
                      <span className="text-danger">Delivery failed {o.delivery.failed_count}x</span>
                      <button className="btn btn-sm btn-outline-primary" disabled={busy}
                        onClick={() => run(() => api.post(`/staff/delivery/orders/${o.id}/redeliver/`), "Back to confirmed for a new delivery.")}>Redeliver</button>
                      <button className="btn btn-sm btn-outline-danger" disabled={busy}
                        onClick={() => window.confirm("Cancel and refund the full amount? The medicines are not restocked.") && run(() => api.post(`/staff/delivery/orders/${o.id}/refund/`), "Cancelled and refund started.")}>Refund in full</button>
                    </div>
                  )}
                  {["confirmed", "dispatched"].includes(o.status) && (
                    <div className="input-group input-group-sm mb-1">
                      <select className="form-select" value={pick[o.id] ?? o.delivery.partner_id ?? ""} onChange={(e) => setPick({ ...pick, [o.id]: e.target.value })}>
                        <option value="">Delivery partner...</option>
                        {partners.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
                      </select>
                      <button className="btn btn-outline-secondary" disabled={busy || !(pick[o.id] || "")}
                        onClick={() => run(() => api.post(`/staff/delivery/orders/${o.id}/assign/`, { partner_id: pick[o.id] }), "Assigned.")}>Assign</button>
                    </div>
                  )}
                  {o.status === "confirmed" && <button className="btn btn-sm btn-outline-primary" disabled={busy}
                    onClick={() => run(() => api.post(`/staff/orders/${o.id}/dispatch/`), "Marked dispatched.")}>Mark dispatched (manual)</button>}
                  {o.status === "dispatched" && <button className="btn btn-sm btn-outline-primary" disabled={busy}
                    onClick={() => run(() => api.post(`/staff/orders/${o.id}/deliver/`), "Marked delivered.")}>Mark delivered (manual)</button>}
                </div>
              </div>
            </div>
          ))}
        </section>
      )}

      <section className="mb-4">
        <h2 className="h5 mb-3">Return requests waiting</h2>
        {returns.length === 0 && <div className="card card-body small text-muted">No return requests are waiting.</div>}
        {returns.map((r) => (
          <div key={r.id} className="card card-body mb-3 small mq-card-hover">
            <div><strong>{r.order_number}</strong> | {RETURN_REASONS[r.reason] || r.reason} | refund if approved: <strong>{formatPaise(r.amount_paise)}</strong></div>
            <div>{r.items.map((i) => `${i.name} x ${i.quantity}`).join(", ")}</div>
            {r.details && <div className="text-muted">Customer says: {r.details}</div>}
            <div className="text-muted">Approving refunds the item price only. The medicine is never put back on sale.</div>
            <input className="form-control form-control-sm mt-2" placeholder="Note (required to reject, 5+ characters)" maxLength={500}
              value={notes[r.id] || ""} onChange={(e) => setNotes({ ...notes, [r.id]: e.target.value })} />
            <div className="d-flex gap-2 mt-2">
              <button className="btn btn-sm btn-primary" disabled={busy}
                onClick={() => window.confirm("Approve and refund?") && run(() => api.post(`/staff/returns/${r.id}/decision/`, { decision: "approve", note: notes[r.id] || "" }), "Return approved.")}>Approve and refund</button>
              <button className="btn btn-sm btn-outline-danger" disabled={busy}
                onClick={() => run(() => api.post(`/staff/returns/${r.id}/decision/`, { decision: "reject", note: notes[r.id] || "" }), "Return rejected.")}>Reject</button>
            </div>
          </div>
        ))}
      </section>

      {canFulfil && (
        <section>
          <h2 className="h5 mb-3">Refunds that failed</h2>
          {refunds.length === 0 && <div className="card card-body small text-muted">No failed refunds.</div>}
          {refunds.map((f) => (
            <div key={f.id} className="card card-body mb-2 small d-flex flex-row justify-content-between align-items-center">
              <span>{formatPaise(f.amount_paise)} ({f.kind}) - {f.message || "failed"}</span>
              <button className="btn btn-sm btn-outline-primary" disabled={busy}
                onClick={() => run(() => api.post(`/staff/refunds/${f.id}/retry/`), "Retry sent.")}>Retry</button>
            </div>
          ))}
        </section>
      )}
    </main>
  );
}
