import { Fragment, useCallback, useEffect, useState } from "react";
import api, { apiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import Field from "../components/Field";

const REASONS = [
  ["stock_count", "Stock count"], ["correction", "Correction (note required)"], ["damage", "Damage (reduces)"],
  ["expired_writeoff", "Expired write-off (reduces)"], ["returned_to_supplier", "Returned to supplier (reduces)"],
];

function Alerts({ overview }) {
  if (!overview) return null;
  const rows = (title, items, render, color) => (
    <div className="col-md-4">
      <div className={`card border-${color} h-100`}>
        <div className="card-body">
          <h3 className="h6">{title} ({items.length})</h3>
          {items.length === 0 ? <p className="small text-muted mb-0">Nothing to show.</p> : (
            <ul className="small ps-3 mb-0">{items.map(render)}</ul>
          )}
        </div>
      </div>
    </div>
  );
  return (
    <section className="mb-4">
      <div className="row g-3">
        {rows("Expired, still in stock", overview.expired_with_stock,
          (b) => <li key={b.id}>{b.product_name} / {b.batch_number}: {b.quantity_on_hand} units (expired {b.expiry_date})</li>, "danger")}
        {rows(`Expiring within ${overview.thresholds.expiry_warning_days} days`, overview.expiring_soon,
          (b) => <li key={b.id}>{b.product_name} / {b.batch_number}: {b.days_to_expiry} days left</li>, "warning")}
        {rows(`Low or out of stock (${overview.thresholds.low_stock} or fewer sellable)`, overview.low_stock,
          (r) => <li key={r.product_id}>{r.name}: {r.sellable_units} sellable</li>, "secondary")}
      </div>
      <p className="small text-muted mt-2">
        Batches with under {overview.thresholds.min_sellable_shelf_life_days} days of shelf life, and quarantined or recalled batches, are not offered for sale.
      </p>
    </section>
  );
}

function ReceiveForm({ onDone }) {
  const [products, setProducts] = useState([]);
  const [find, setFind] = useState("");
  const [form, setForm] = useState({ product_id: "", batch_number: "", expiry_date: "", mfg_date: "", quantity: "", supplier: "" });
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState("");

  useEffect(() => {
    const t = setTimeout(() => {
      api.get("/products/", { params: { q: find || undefined, page_size: 50 } })
        .then((res) => setProducts(res.data.results)).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [find]);

  const change = (e) => setForm({ ...form, [e.target.name]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setErrors({});
    setMessage("");
    const payload = { ...form, quantity: form.quantity === "" ? undefined : Number(form.quantity) };
    if (!payload.mfg_date) delete payload.mfg_date;
    try {
      await api.post("/inventory/batches/", payload);
      setForm({ ...form, batch_number: "", expiry_date: "", mfg_date: "", quantity: "" });
      setMessage("Stock received.");
      onDone();
    } catch (err) {
      const { message: m, fields } = apiError(err);
      setErrors(fields);
      setMessage(Object.keys(fields).length ? "" : m);
    }
  }

  return (
    <form onSubmit={submit} className="card card-body mb-4">
      <h2 className="h6">Receive stock</h2>
      <div className="row g-2">
        <div className="col-md-6">
          <label className="form-label" htmlFor="find">Find product</label>
          <input id="find" className="form-control mb-2" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Type to filter" maxLength={60} />
          <select name="product_id" value={form.product_id} onChange={change} aria-label="Product"
            className={`form-select ${errors.product_id ? "is-invalid" : ""}`}>
            <option value="">Choose a product</option>
            {products.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.pack_size})</option>)}
          </select>
          {errors.product_id && <div className="invalid-feedback">{errors.product_id}</div>}
        </div>
        <div className="col-md-6">
          <Field label="Batch number" name="batch_number" value={form.batch_number} onChange={change} error={errors.batch_number} />
        </div>
        <div className="col-md-4"><Field label="Expiry date" name="expiry_date" type="date" value={form.expiry_date} onChange={change} error={errors.expiry_date} /></div>
        <div className="col-md-4"><Field label="Manufacturing date (optional)" name="mfg_date" type="date" value={form.mfg_date} onChange={change} error={errors.mfg_date} /></div>
        <div className="col-md-4"><Field label="Quantity" name="quantity" type="number" value={form.quantity} onChange={change} error={errors.quantity} /></div>
        <div className="col-12"><Field label="Supplier (optional)" name="supplier" value={form.supplier} onChange={change} error={errors.supplier} /></div>
      </div>
      <div><button className="btn btn-primary btn-sm">Receive</button> <span className="small ms-2">{message}</span></div>
    </form>
  );
}

function BatchPanel({ batch, canRecall, onChanged }) {
  const [adj, setAdj] = useState({ delta: "", reason: "stock_count", note: "" });
  const [status, setStatus] = useState({ status: batch.status === "active" ? "quarantined" : "active", note: "" });
  const [moves, setMoves] = useState([]);
  const [message, setMessage] = useState("");
  const [errors, setErrors] = useState({});

  const loadMoves = useCallback(() => {
    api.get(`/inventory/batches/${batch.id}/movements/`).then((res) => setMoves(res.data.results)).catch(() => {});
  }, [batch.id]);
  useEffect(loadMoves, [loadMoves]);

  async function send(path, payload) {
    setErrors({});
    setMessage("");
    try {
      await api.post(`/inventory/batches/${batch.id}/${path}/`, payload);
      loadMoves();
      onChanged();
      setMessage("Saved.");
    } catch (err) {
      const { message: m, fields } = apiError(err);
      setErrors(fields);
      setMessage(Object.keys(fields).length ? "" : m);
    }
  }

  const statuses = ["active", "quarantined", ...(canRecall ? ["recalled"] : [])];
  return (
    <div className="border rounded p-3 bg-light">
      {message && <div className="small mb-2">{message}</div>}
      <div className="row g-3">
        <div className="col-md-6">
          <h3 className="h6">Adjust stock</h3>
          <div className="d-flex gap-2 mb-2">
            <input type="number" className={`form-control form-control-sm ${errors.delta ? "is-invalid" : ""}`} placeholder="+/- units"
              value={adj.delta} onChange={(e) => setAdj({ ...adj, delta: e.target.value })} aria-label="Change in units" />
            <select className="form-select form-select-sm" value={adj.reason} onChange={(e) => setAdj({ ...adj, reason: e.target.value })} aria-label="Reason">
              {REASONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <input className={`form-control form-control-sm mb-2 ${errors.note ? "is-invalid" : ""}`} placeholder="Note" maxLength={200}
            value={adj.note} onChange={(e) => setAdj({ ...adj, note: e.target.value })} aria-label="Note" />
          {(errors.delta || errors.reason || errors.note) && <div className="small text-danger mb-2">{errors.delta || errors.reason || errors.note}</div>}
          <button className="btn btn-sm btn-outline-primary"
            onClick={() => send("adjust", { delta: adj.delta === "" ? undefined : Number(adj.delta), reason: adj.reason, note: adj.note })}>Apply change</button>
        </div>
        <div className="col-md-6">
          <h3 className="h6">Batch status</h3>
          <select className="form-select form-select-sm mb-2" value={status.status} onChange={(e) => setStatus({ ...status, status: e.target.value })} aria-label="New status">
            {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <input className={`form-control form-control-sm mb-2 ${errors.note ? "is-invalid" : ""}`} placeholder="Reason (required)" maxLength={200}
            value={status.note} onChange={(e) => setStatus({ ...status, note: e.target.value })} aria-label="Status reason" />
          <button className="btn btn-sm btn-outline-secondary" onClick={() => send("status", status)}>Change status</button>
          {!canRecall && <p className="small text-muted mt-1 mb-0">Recalls need a pharmacy manager or admin.</p>}
        </div>
      </div>
      <h3 className="h6 mt-3">History</h3>
      <table className="table table-sm small mb-0">
        <thead><tr><th>When</th><th>Type</th><th>Change</th><th>After</th><th>Reason / note</th></tr></thead>
        <tbody>
          {moves.map((m) => (
            <tr key={m.id}>
              <td>{new Date(m.created_at).toLocaleString("en-IN")}</td><td>{m.type}</td>
              <td>{m.delta > 0 ? `+${m.delta}` : m.delta}</td><td>{m.quantity_after}</td><td>{m.reason}{m.note ? `: ${m.note}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function InventoryPage() {
  const { user } = useAuth();
  const canWrite = user.role !== "pharmacist";
  const canRecall = ["pharmacy_manager", "admin"].includes(user.role);
  const [overview, setOverview] = useState(null);
  const [list, setList] = useState(null);
  const [state, setState] = useState("all");
  const [page, setPage] = useState(1);
  const [openId, setOpenId] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    api.get("/inventory/overview/").then((res) => setOverview(res.data)).catch((err) => setError(apiError(err).message));
    api.get("/inventory/batches/", { params: { state: state === "all" ? undefined : state, page } })
      .then((res) => setList(res.data)).catch((err) => setError(apiError(err).message));
  }, [state, page]);
  useEffect(load, [load]);

  return (
    <main className="container py-4">
      <div className="mb-4">
        <h1 className="h3 mb-1">Inventory</h1>
        <p className="text-muted mb-0">Stock by batch, earliest expiry first. Expired or recalled stock is never sold.</p>
      </div>
      {!canWrite && <div className="alert alert-info py-2">Read-only view for your role.</div>}
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      <Alerts overview={overview} />
      {canWrite && <ReceiveForm onDone={load} />}

      <div className="d-flex justify-content-between align-items-center mb-2">
        <h2 className="h6 mb-0">Batches (earliest expiry first)</h2>
        <select className="form-select form-select-sm w-auto" value={state} aria-label="Filter batches"
          onChange={(e) => { setState(e.target.value); setPage(1); setOpenId(null); }}>
          <option value="all">All batches</option><option value="in_stock">With stock</option>
          <option value="expiring">Expiring soon</option><option value="expired">Expired with stock</option>
        </select>
      </div>
      {!list && !error && <div className="mq-skeleton mb-3" style={{ height: 160 }} aria-busy="true" />}
      <div className="card overflow-hidden mb-3"><div className="table-responsive">
        <table className="mq-table">
          <thead><tr><th>Product</th><th>Batch</th><th>Expiry</th><th>On hand</th><th>Reserved</th><th>Status</th><th>Sellable</th><th /></tr></thead>
          <tbody>
            {list?.results.map((b) => (
              <Fragment key={b.id}>
                <tr style={b.is_expired ? { background: "#fef2f2" } : undefined}>
                  <td>{b.product_name}{b.is_demo && <span className="mq-pill mq-pill--demo ms-1">Demo</span>}</td>
                  <td>{b.batch_number}</td>
                  <td>{b.expiry_date} <span className="text-muted small">({b.is_expired ? "expired" : `${b.days_to_expiry}d`})</span></td>
                  <td>{b.quantity_on_hand}</td><td>{b.quantity_reserved}</td><td>{b.status}</td>
                  <td>{b.is_sellable ? "Yes" : "No"}</td>
                  <td>{canWrite && <button className="btn btn-sm btn-outline-secondary" onClick={() => setOpenId(openId === b.id ? null : b.id)}>{openId === b.id ? "Close" : "Manage"}</button>}</td>
                </tr>
                {openId === b.id && <tr><td colSpan={8}><BatchPanel batch={b} canRecall={canRecall} onChanged={load} /></td></tr>}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div></div>
      {list && list.results.length === 0 && <p className="text-muted">No batches match.</p>}
      {list && (
        <div className="d-flex justify-content-between align-items-center">
          <button className="btn btn-outline-secondary btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="small">Page {list.page} of {list.total_pages}</span>
          <button className="btn btn-outline-secondary btn-sm" disabled={page >= list.total_pages} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </main>
  );
}
