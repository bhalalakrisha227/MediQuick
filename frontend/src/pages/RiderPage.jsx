import { useCallback, useEffect, useState } from "react";
import api, { apiError } from "../api/client";
import Icon from "../components/ui/Icon";
import StatusPill from "../components/ui/StatusPill";
import { EmptyState, ErrorState } from "../components/ui/States";

const REASONS = {
  customer_unavailable: "Customer not available", wrong_address: "Address is wrong or not found",
  refused_by_customer: "Customer refused", unreachable_phone: "Customer phone unreachable",
};

export default function RiderPage() {
  const [rows, setRows] = useState(null);
  const [codes, setCodes] = useState({});
  const [reasons, setReasons] = useState({});
  const [message, setMessage] = useState("");
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoadError("");
    api.get("/rider/deliveries/").then((r) => setRows(r.data.results)).catch((e) => setLoadError(apiError(e).message));
  }, []);
  useEffect(load, [load]);

  async function run(path, payload, okText) {
    setBusy(true);
    setMessage("");
    try { await api.post(`/rider/deliveries/${path}/`, payload || {}); setMessage(okText); }
    catch (err) { setMessage(apiError(err).message); }
    setBusy(false);
    load();
  }

  const toPickUp = rows?.filter((o) => o.status === "confirmed").length ?? 0;
  const onRoad = rows?.filter((o) => o.status === "dispatched").length ?? 0;

  return (
    <main className="container py-4" style={{ maxWidth: 820 }}>
      <div className="mb-4">
        <h1 className="h3 mb-1">My deliveries</h1>
        <p className="text-muted mb-0">Orders assigned to you.</p>
      </div>
      <div className="alert alert-warning small d-flex gap-2">
        <Icon name="info" size={18} />
        <span>
          Hand the parcel only to the person named below. Ask them for the 6-digit code shown on their order page and type it here.
          You never collect money: all orders are prepaid. There is no live map or tracking in this app.
        </span>
      </div>
      {rows && (
        <div className="row g-3 mb-4">
          <div className="col-6"><div className="card mq-stat"><span className="mq-stat__icon"><Icon name="box" size={22} /></span><span><span className="mq-stat__value d-block">{toPickUp}</span><span className="mq-stat__label">To pick up</span></span></div></div>
          <div className="col-6"><div className="card mq-stat"><span className="mq-stat__icon"><Icon name="truck" size={22} /></span><span><span className="mq-stat__value d-block">{onRoad}</span><span className="mq-stat__label">Out for delivery</span></span></div></div>
        </div>
      )}
      {message && <div className="alert alert-info py-2" role="status">{message}</div>}
      {loadError && <ErrorState message={loadError} onRetry={load} />}
      {rows === null && !loadError && <div className="mq-skeleton" style={{ height: 180 }} aria-busy="true" />}
      {rows && rows.length === 0 && <EmptyState icon="truck" title="Nothing assigned to you right now">New assignments appear here.</EmptyState>}
      <div className="d-grid gap-3">
        {(rows || []).map((o) => (
          <div key={o.id} className="card card-body small mq-card-hover">
            <div className="d-flex justify-content-between align-items-center mb-2">
              <strong className="fs-6">{o.order_number}</strong>
              <StatusPill color={o.status === "confirmed" ? "warning" : "info"} label={o.status === "confirmed" ? "To pick up" : "Out for delivery"} />
            </div>
            <div className="fw-semibold">{o.recipient_name}, <a href={`tel:${o.phone}`}>{o.phone}</a></div>
            <div>{o.address}</div>
            <div className="text-muted">{o.item_count} item(s). Failed attempts: {o.failed_count} of {o.max_failed}.
              {o.last_failure && ` Last: ${REASONS[o.last_failure] || o.last_failure}.`}</div>
            {o.status === "confirmed" && (
              <button className="btn btn-teal btn-sm mt-3 align-self-start" disabled={busy}
                onClick={() => run(`${o.id}/pickup`, {}, "Picked up. Deliver it and ask for the code.")}>I have picked this up</button>
            )}
            {o.status === "dispatched" && (
              <>
                <div className="input-group input-group-sm mt-3">
                  <input className="form-control" inputMode="numeric" maxLength={6} placeholder="Customer's 6-digit code" aria-label="Customer's 6-digit code"
                    value={codes[o.id] || ""} onChange={(e) => setCodes({ ...codes, [o.id]: e.target.value.replace(/\D/g, "") })} />
                  <button className="btn btn-teal" disabled={busy || (codes[o.id] || "").length !== 6}
                    onClick={() => run(`${o.id}/deliver`, { code: codes[o.id] }, "Delivered. Thank you.")}>Confirm delivery</button>
                </div>
                <div className="small text-muted mt-1">Tries left: {o.code_tries_left}</div>
                <div className="input-group input-group-sm mt-3">
                  <select className="form-select" aria-label="Reason for failed delivery" value={reasons[o.id] || ""} onChange={(e) => setReasons({ ...reasons, [o.id]: e.target.value })}>
                    <option value="">Could not deliver? Choose why...</option>
                    {Object.entries(REASONS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                  <button className="btn btn-outline-danger" disabled={busy || !reasons[o.id]}
                    onClick={() => window.confirm("Record a failed attempt?") && run(`${o.id}/fail`, { reason: reasons[o.id] }, "Failed attempt recorded.")}>Record failed attempt</button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}
