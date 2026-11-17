import { useCallback, useEffect, useState } from "react";
import api, { apiError } from "../api/client";
import { formatPaise } from "../utils/money";
import StatusPill from "./ui/StatusPill";

export const RETURN_REASONS = {
  wrong_item: "I received the wrong item",
  damaged: "The item arrived damaged",
  expired_item: "The item is expired",
  missing_item: "An item is missing",
};
const RETURN_STATUS = { requested: ["warning", "Waiting for review"], approved: ["success", "Approved"], rejected: ["secondary", "Rejected"] };
const REFUND_STATUS = { pending: "In progress", succeeded: "Refunded", failed: "Delayed - our team will retry" };

export default function ReturnsSection({ order, onChanged }) {
  const [info, setInfo] = useState({ returns: [], refunds: [] });
  const [reason, setReason] = useState("damaged");
  const [qty, setQty] = useState({});
  const [details, setDetails] = useState("");
  const [error, setError] = useState("");
  const [fields, setFields] = useState({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get(`/orders/${encodeURIComponent(order.id)}/returns/`).then((res) => setInfo(res.data)).catch(() => {});
  }, [order.id]);
  useEffect(load, [load, order.status]);

  const open = info.returns.some((r) => r.status === "requested");
  const canRequest = order.status === "delivered" && !open;

  async function submit(e) {
    e.preventDefault();
    const items = Object.entries(qty).filter(([, n]) => Number(n) > 0).map(([product_id, n]) => ({ product_id, quantity: Number(n) }));
    setBusy(true);
    setError("");
    setFields({});
    try {
      await api.post(`/orders/${encodeURIComponent(order.id)}/returns/`, { reason, details, items });
      setQty({});
      setDetails("");
      load();
      onChanged();
    } catch (err) {
      const { message, fields: f } = apiError(err);
      setError(message);
      setFields(f);
    }
    setBusy(false);
  }

  if (!info.returns.length && !info.refunds.length && order.status !== "delivered") return null;
  return (
    <section className="mt-4">
      <h2 className="h6">Returns and refunds</h2>
      {info.refunds.length > 0 && (
        <ul className="list-group mb-3">
          {info.refunds.map((r) => (
            <li key={r.id} className="list-group-item d-flex justify-content-between">
              <span>{r.kind === "cancellation" ? "Cancellation refund" : "Return refund"}: {REFUND_STATUS[r.status] || r.status}</span>
              <span>{formatPaise(r.amount_paise)}</span>
            </li>
          ))}
        </ul>
      )}
      {info.returns.map((r) => {
        const [color, label] = RETURN_STATUS[r.status] || ["secondary", r.status];
        return (
          <div key={r.id} className="card card-body mb-2 small">
            <div className="d-flex justify-content-between">
              <span>{r.items.map((i) => `${i.name} x ${i.quantity}`).join(", ")} ({RETURN_REASONS[r.reason] || r.reason})</span>
              <StatusPill color={color} label={label} />
            </div>
            {r.decision_note && <div className="mt-1">Note from our team: {r.decision_note}</div>}
            {r.status === "approved" && <div className="mt-1 text-muted">Returned medicines are not put back on sale. Only the item price is refunded.</div>}
          </div>
        );
      })}
      {canRequest && (
        <form onSubmit={submit} className="card card-body" noValidate>
          <p className="small text-muted mb-2">
            Medicines can only be returned if something is wrong with what we sent (not if you changed your mind), and within 2 days of delivery.
            Our team reviews every request.
          </p>
          {error && <div className="alert alert-danger py-2">{error}</div>}
          <label className="form-label small" htmlFor="reason">What went wrong?</label>
          <select id="reason" className={`form-select form-select-sm mb-2 ${fields.reason ? "is-invalid" : ""}`} value={reason} onChange={(e) => setReason(e.target.value)}>
            {Object.entries(RETURN_REASONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {order.lines.map((l, i) => (
            <div key={l.product_id} className="d-flex align-items-center gap-2 mb-1 small">
              <input type="number" min="0" max={l.quantity} className={`form-control form-control-sm ${fields[`items.${i}`] ? "is-invalid" : ""}`} style={{ width: 70 }}
                aria-label={`Quantity of ${l.name} to return`} value={qty[l.product_id] ?? ""} onChange={(e) => setQty({ ...qty, [l.product_id]: e.target.value })} />
              <span>of {l.quantity} x {l.name}</span>
            </div>
          ))}
          {fields.items && <div className="text-danger small">{fields.items}</div>}
          <textarea className="form-control form-control-sm mt-2" rows={2} maxLength={500} placeholder="Tell us what happened (optional)" value={details} onChange={(e) => setDetails(e.target.value)} />
          <button className="btn btn-outline-primary btn-sm mt-2 align-self-start" disabled={busy}>Request a return</button>
        </form>
      )}
    </section>
  );
}
