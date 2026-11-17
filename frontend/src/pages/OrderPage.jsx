import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api, { apiError } from "../api/client";
import DeliveryPanel from "../components/DeliveryPanel";
import GatewayPay from "../components/GatewayPay";
import MockPaymentBanner from "../components/MockPaymentBanner";
import ReturnsSection from "../components/ReturnsSection";
import { formatPaise } from "../utils/money";
import StatusPill from "../components/ui/StatusPill";

export const STATUS_LABELS = {
  pending_payment: ["warning", "Awaiting payment"], processing_payment: ["info", "Processing payment"], confirming_payment: ["info", "Confirming payment"],
  confirmed: ["success", "Confirmed"], cancelled: ["secondary", "Cancelled"],
  expired: ["secondary", "Expired (items released)"], payment_review: ["danger", "Needs review"],
  dispatched: ["info", "Out for delivery"], delivery_failed: ["danger", "Delivery failed"], delivered: ["success", "Delivered"],
};

function Countdown({ until, onDone }) {
  const [left, setLeft] = useState(() => Math.max(0, Math.floor((new Date(until) - Date.now()) / 1000)));
  useEffect(() => {
    const t = setInterval(() => {
      const next = Math.max(0, Math.floor((new Date(until) - Date.now()) / 1000));
      setLeft(next);
      if (next === 0) { clearInterval(t); onDone(); }
    }, 1000);
    return () => clearInterval(t);
  }, [until, onDone]);
  return <span>{Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}</span>;
}

export default function OrderPage() {
  const { id } = useParams();
  const [order, setOrder] = useState(null);
  const [state, setState] = useState("loading");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState({ provider: "mock" });
  useEffect(() => { api.get("/payments/config/").then((r) => setConfig(r.data)).catch(() => {}); }, []);

  const load = useCallback(() => {
    api.get(`/orders/${encodeURIComponent(id)}/`)
      .then((res) => { setOrder(res.data); setState("ok"); })
      .catch((err) => setState(err.response?.status === 404 ? "missing" : "error"));
  }, [id]);
  useEffect(load, [load]);

  async function act(path, payload) {
    setBusy(true);
    setError("");
    try { await api.post(`/orders/${id}/${path}/`, payload || {}); } catch (err) { setError(apiError(err).message); }
    setBusy(false);
    load();
  }

  if (state === "loading") return <main className="container py-4">Loading...</main>;
  if (state === "missing") return <main className="container py-4"><p>Order not found.</p><Link to="/orders">My orders</Link></main>;
  if (state === "error") return <main className="container py-4"><div className="alert alert-danger">Could not load this order.</div></main>;

  const [color, label] = STATUS_LABELS[order.status] || ["secondary", order.status];
  const pending = order.status === "pending_payment";
  const gateway = config.provider === "razorpay";
  return (
    <main className="container py-4" style={{ maxWidth: 760 }}>
      <Link to="/orders" className="small">&larr; My orders</Link>
      <h1 className="h4 mt-2">Order {order.order_number} <StatusPill color={color} label={label} large /></h1>
      {error && <div className="alert alert-danger">{error}</div>}
      {order.payment.is_mock && <MockPaymentBanner />}

      {pending && (
        <div className="card card-body mb-3">
          <p className="mb-2">Your items are held for <strong><Countdown until={order.reservation_expires_at} onDone={load} /></strong>. Pay before the timer ends.</p>
          {gateway ? (
            <div className="d-flex gap-2 flex-wrap align-items-start">
              <GatewayPay order={order} config={config} onDone={load} onError={setError} />
              <button className="btn btn-outline-danger" disabled={busy} onClick={() => act("cancel")}>Cancel order</button>
            </div>
          ) : (
            <div className="d-flex gap-2 flex-wrap">
              <button className="btn btn-primary" disabled={busy} onClick={() => act("pay", {})}>Pay {formatPaise(order.total_paise)} (mock)</button>
              <button className="btn btn-outline-secondary" disabled={busy} onClick={() => act("pay", { simulate: "fail" })}>Simulate a failed payment</button>
              <button className="btn btn-outline-danger" disabled={busy} onClick={() => act("cancel")}>Cancel order</button>
            </div>
          )}
          {order.payment.status === "failed" && <p className="small text-danger mt-2 mb-0">The last payment attempt failed. You were not charged. You can try again.</p>}
        </div>
      )}
      {gateway && order.status === "processing_payment" && (
        <div className="card card-body mb-3">
          <p className="mb-2">Waiting for your payment. Your items stay reserved for a short time. If you already paid, this page updates once the bank confirms it.</p>
          <div className="d-flex gap-2 flex-wrap align-items-start">
            <GatewayPay order={order} config={config} resume onDone={load} onError={setError} />
            <button className="btn btn-outline-secondary" disabled={busy} onClick={load}>Check payment status</button>
            <button className="btn btn-outline-danger" disabled={busy} onClick={() => window.confirm("Cancel this order? If a payment goes through anyway it is refunded automatically.") && act("cancel")}>Cancel order</button>
          </div>
        </div>
      )}
      {order.status === "confirmed" && (
        <div className="alert alert-success">
          Order confirmed ({order.payment.is_mock ? "mock payment" : "payment received"}, reference {order.payment.reference}). 
          <div className="mt-2">
            <button className="btn btn-sm btn-outline-danger" disabled={busy}
              onClick={() => window.confirm("Cancel this order and get a refund?") && act("cancel")}>Cancel order and refund</button>
            <span className="small ms-2">Possible until we dispatch it.</span>
          </div>
        </div>
      )}
      <DeliveryPanel order={order} />
      {order.status === "cancelled" && order.payment.refunded_paise > 0 && (
        <div className="alert alert-secondary">Cancelled. {formatPaise(order.payment.refunded_paise)} refunded{order.payment.is_mock ? " (mock: no real money moved)" : ""}.</div>
      )}
      {order.status === "expired" && <div className="alert alert-secondary">The hold on your items ran out, so they were released. Please add them to your cart and order again.</div>}

      <h2 className="h6">Items</h2>
      <ul className="list-group mb-3">
        {order.lines.map((l) => (
          <li key={l.product_id} className="list-group-item d-flex justify-content-between">
            <span>{l.name} ({l.pack_size}) x {l.quantity}</span><span>{formatPaise(l.line_total_paise)}</span>
          </li>
        ))}
        <li className="list-group-item d-flex justify-content-between"><span>Delivery</span><span>{order.delivery_fee_paise ? formatPaise(order.delivery_fee_paise) : "Free"}</span></li>
        <li className="list-group-item d-flex justify-content-between fw-bold"><span>Total</span><span>{formatPaise(order.total_paise)}</span></li>
      </ul>
      <h2 className="h6">Deliver to</h2>
      <p className="small">{order.address.recipient_name}, {order.address.phone}<br />
        {order.address.line1}{order.address.line2 ? `, ${order.address.line2}` : ""}, {order.address.city}, {order.address.state} {order.address.pincode}</p>
      <ReturnsSection order={order} onChanged={load} />
    </main>
  );
}
