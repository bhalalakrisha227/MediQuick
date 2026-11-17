import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { apiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { BarChart, Donut } from "../components/ui/Charts";
import Icon from "../components/ui/Icon";
import { EmptyState, ErrorState } from "../components/ui/States";
import { formatPaise } from "../utils/money";

const pct = (v) => (v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(1)}%`);

function Kpi({ label, value, hint, icon = "chart" }) {
  return (
    <div className="col-6 col-lg-3">
      <div className="card mq-stat h-100">
        <span className="mq-stat__icon"><Icon name={icon} size={22} /></span>
        <span className="min-w-0">
          <span className="mq-stat__label d-block">{label}</span>
          <span className="mq-stat__value d-block" style={{ fontSize: "1.35rem" }}>{value}</span>
          {hint && <span className="small text-muted">{hint}</span>}
        </span>
      </div>
    </div>
  );
}

const label = (k) => k.replace(/_/g, " ");

function Panel({ title, action, children }) {
  return (
    <div className="card mq-section-card">
      <div className="mq-section-card__head"><h2>{title}</h2>{action}</div>
      {children}
    </div>
  );
}

// Sales + operations data is loaded once here and shared by the Overview, Orders and Inventory tabs.
function useDashboardData() {
  const [range, setRange] = useState({ from: "", to: "" }); // empty = the server picks the last 30 days in Indian time
  const [sales, setSales] = useState(null);
  const [ops, setOps] = useState(null);
  const [error, setError] = useState("");
  const [opsError, setOpsError] = useState(false);
  const load = useCallback(() => {
    setError(""); setOpsError(false); setSales(null);
    const q = new URLSearchParams({ ...(range.from && { from: range.from }), ...(range.to && { to: range.to }) });
    api.get(`/admin/sales/?${q}`).then((r) => setSales(r.data)).catch((e) => setError(apiError(e).message));
    api.get("/admin/overview/").then((r) => setOps(r.data)).catch(() => setOpsError(true));
  }, [range]);
  useEffect(load, [load]);
  return { range, setRange, sales, ops, error, opsError, reload: load };
}

function RangePicker({ range, setRange }) {
  return (
    <div className="d-flex gap-2 align-items-end flex-wrap mb-3">
      <label className="small fw-semibold">From<input type="date" className="form-control form-control-sm" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} /></label>
      <label className="small fw-semibold">To<input type="date" className="form-control form-control-sm" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} /></label>
      <span className="small text-muted">Leave both empty for the last 30 days. Days are Indian time.</span>
    </div>
  );
}

function SalesNotices({ sales }) {
  return (
    <>
      {sales.includes_mock_payments && <div className="alert alert-warning small py-2">This period includes <strong>mock payments</strong>. No real money moved for those.</div>}
      {sales.truncated && <div className="alert alert-warning small py-2">Too many orders: only the first {sales.rows_scanned} were counted. Choose a shorter period.</div>}
    </>
  );
}

function Overview({ d }) {
  const { sales, ops, error } = d;
  return (
    <>
      <RangePicker range={d.range} setRange={d.setRange} />
      {error && <ErrorState message={error} onRetry={d.reload} />}
      {!sales && !error && <div className="mq-skeleton" style={{ height: 300 }} aria-busy="true" />}
      {sales && (
        <>
          <SalesNotices sales={sales} />
          <div className="row g-3 mb-4">
            <Kpi icon="box" label="Orders" value={sales.totals.orders} hint={`${sales.totals.paid_orders} paid`} />
            <Kpi icon="chart" label="Paid (gross)" value={formatPaise(sales.totals.gross_paise)} hint="orders whose payment succeeded" />
            <Kpi icon="arrow" label="Refunded" value={formatPaise(sales.totals.refunded_paise)} hint={`refund rate ${pct(sales.totals.refund_rate)}`} />
            <Kpi icon="check" label="Net" value={formatPaise(sales.totals.net_paise)} hint={sales.totals.average_order_paise ? `average order ${formatPaise(sales.totals.average_order_paise)}` : ""} />
          </div>
          <div className="row g-4">
            <div className="col-lg-8">
              <Panel title="Paid per day">
                <BarChart label="Paid amount per day" format={formatPaise}
                  data={sales.daily.map((x) => ({ key: x.date, label: x.date, value: x.gross_paise,
                    title: `${x.date}: ${x.orders} orders, paid ${formatPaise(x.gross_paise)}, refunded ${formatPaise(x.refunded_paise)}` }))} />
                <div className="small text-muted mt-2">Hover a bar for details. A refund counts on the day the order was placed.</div>
              </Panel>
            </div>
            <div className="col-lg-4">
              <Panel title="Top products (sold orders)">
                {sales.top_products.length === 0 && <p className="small text-muted mb-0">None in this period.</p>}
                {sales.top_products.map((p) => (
                  <div key={p.product_id} className="mq-row">
                    <span><span className="mq-row__title d-block">{p.name}</span><span className="small text-muted">{p.units} units</span></span>
                    <strong className="small">{formatPaise(p.revenue_paise)}</strong>
                  </div>
                ))}
              </Panel>
            </div>
            {ops && (
              <div className="col-lg-6">
                <Panel title="Prescriptions right now" action={<Link to="/staff/prescriptions" className="small fw-semibold">Open review</Link>}>
                  <Donut label="Prescriptions by status" centre="prescriptions"
                    parts={Object.entries(ops.prescriptions_by_status).map(([k, v]) => ({ label: label(k), value: v }))} />
                </Panel>
              </div>
            )}
            {d.opsError && <div className="col-lg-6"><ErrorState message="Could not load prescription and stock figures." onRetry={d.reload} /></div>}
            {ops && (
              <div className="col-lg-6">
                <Panel title="Stock to look at" action={<Link to="/staff/inventory" className="small fw-semibold">Open inventory</Link>}>
                  <div className="row g-2 text-center">
                    {[["Low stock", ops.inventory.low_stock?.length ?? 0], ["Expiring soon", ops.inventory.expiring_soon?.length ?? 0], ["Expired with stock", ops.inventory.expired_with_stock?.length ?? 0]].map(([t, n]) => (
                      <div key={t} className="col-4"><div className="mq-stat__value">{n}</div><div className="mq-stat__label">{t}</div></div>
                    ))}
                  </div>
                </Panel>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}

function OrdersTab({ d }) {
  const { sales, error } = d;
  return (
    <>
      <RangePicker range={d.range} setRange={d.setRange} />
      {error && <ErrorState message={error} onRetry={d.reload} />}
      {!sales && !error && <div className="mq-skeleton" style={{ height: 260 }} aria-busy="true" />}
      {sales && (
        <>
          <SalesNotices sales={sales} />
          <div className="row g-4">
            <div className="col-lg-7">
              <Panel title="Orders by status" action={<Link to="/staff/fulfilment" className="small fw-semibold">Open fulfilment</Link>}>
                {Object.keys(sales.orders_by_status).length === 0
                  ? <p className="small text-muted mb-0">No orders in this period.</p>
                  : <Donut label="Orders by status" centre="orders" parts={Object.entries(sales.orders_by_status).map(([k, v]) => ({ label: label(k), value: v }))} />}
              </Panel>
            </div>
            <div className="col-lg-5">
              <Panel title="Delivery and cancellations">
                <div className="mq-row"><span>Cancelled or expired</span><strong>{pct(sales.cancel_rate)}</strong></div>
                <div className="mq-row"><span>Avg hours, confirmed to delivered</span><strong>{sales.delivery.average_hours_confirmed_to_delivered ?? "n/a"}</strong></div>
                <div className="mq-row"><span>Orders with a failed delivery</span><strong>{sales.delivery.orders_with_failed_delivery} ({pct(sales.delivery.failed_delivery_rate)})</strong></div>
              </Panel>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function InventoryTab({ d }) {
  const { ops, opsError } = d;
  if (opsError) return <ErrorState message="Could not load inventory figures." onRetry={d.reload} />;
  if (!ops) return <div className="mq-skeleton" style={{ height: 260 }} aria-busy="true" />;
  const inv = ops.inventory;
  const batchRows = (rows) => rows.map((b) => (
    <div key={b.id} className="mq-row">
      <span><span className="mq-row__title d-block">{b.product_name || b.product_id}</span><span className="small text-muted">Batch {b.batch_number} · expires {b.expiry_date}</span></span>
      <strong className="small">{b.quantity_available} available</strong>
    </div>
  ));
  return (
    <div className="row g-4">
      <div className="col-lg-4">
        <Panel title={`Low stock (${inv.low_stock?.length ?? 0})`} action={<Link to="/staff/inventory" className="small fw-semibold">Manage</Link>}>
          {(inv.low_stock || []).length === 0 && <p className="small text-muted mb-0">Nothing is running low.</p>}
          {(inv.low_stock || []).map((p) => (
            <div key={p.product_id} className="mq-row"><span className="mq-row__title">{p.name}</span>
              <span className={`mq-pill ${p.sellable_units === 0 ? "mq-pill--danger" : "mq-pill--warn"}`}>{p.sellable_units} left</span></div>
          ))}
        </Panel>
      </div>
      <div className="col-lg-4">
        <Panel title={`Expiring soon (${inv.expiring_soon?.length ?? 0})`}>
          {(inv.expiring_soon || []).length === 0 ? <p className="small text-muted mb-0">No batches expiring soon.</p> : batchRows(inv.expiring_soon)}
        </Panel>
      </div>
      <div className="col-lg-4">
        <Panel title={`Expired with stock (${inv.expired_with_stock?.length ?? 0})`}>
          {(inv.expired_with_stock || []).length === 0 ? <p className="small text-muted mb-0">No expired stock on hand.</p> : batchRows(inv.expired_with_stock)}
        </Panel>
      </div>
    </div>
  );
}

function Attention({ onCount }) {
  const [items, setItems] = useState(null);
  const [notes, setNotes] = useState({});
  const [message, setMessage] = useState("");
  const [loadError, setLoadError] = useState("");
  const load = useCallback(() => {
    setLoadError("");
    api.get("/admin/attention/").then((r) => { setItems(r.data.results); onCount(r.data.results.length); }).catch((e) => setLoadError(apiError(e).message));
  }, [onCount]);
  useEffect(load, [load]);

  async function resolve(i) {
    setMessage("");
    try { await api.post(`/admin/attention/${encodeURIComponent(i.order_id)}/resolve/`, { flag: i.flag, note: notes[i.order_id + i.flag] || "" }); setMessage("Marked as handled."); }
    catch (e) { setMessage(apiError(e).message); }
    load();
  }
  return (
    <>
      <div className="alert alert-warning small">
        These are problems the system will not fix by itself because money or stock may be wrong. "Mark as handled" only records that a
        person checked and fixed it elsewhere (for example in the payment dashboard). It moves no money and changes no stock.
      </div>
      {message && <div className="alert alert-info py-2">{message}</div>}
      {loadError && <ErrorState message={loadError} onRetry={load} />}
      {!items && !loadError && <div className="mq-skeleton" style={{ height: 120 }} aria-busy="true" />}
      {items && items.length === 0 && <EmptyState icon="check" title="Nothing needs attention" />}
      <div className="d-grid gap-2">
        {(items || []).map((i) => (
          <div key={`${i.kind}-${i.order_id}-${i.reference}`} className="card card-body small">
            <div className="d-flex flex-wrap align-items-center gap-2">
              <span className="mq-pill mq-pill--danger">{label(i.kind)}</span>
              <strong>{i.order_number || ""}</strong> {i.reference && <code>{i.reference}</code>}
            </div>
            <div className="my-1">{i.detail}</div>
            <div className="text-muted">Since {new Date(i.since).toLocaleString("en-IN")}</div>
            {i.resolvable ? (
              <div className="input-group input-group-sm mt-2">
                <input className="form-control" maxLength={500} placeholder="What did you check or do? (5+ characters)" value={notes[i.order_id + i.flag] || ""}
                  onChange={(e) => setNotes({ ...notes, [i.order_id + i.flag]: e.target.value })} />
                <button className="btn btn-outline-primary" onClick={() => resolve(i)}>Mark as handled</button>
              </div>
            ) : (
              <div className="mt-1"><Link to="/staff/fulfilment" className="fw-semibold">Open Fulfilment</Link></div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}

function Users() {
  const { user: me } = useAuth();
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [data, setData] = useState(null);
  const [message, setMessage] = useState("");
  const [notes, setNotes] = useState({});
  const load = useCallback(() => {
    const params = new URLSearchParams({ ...(q && { q }), ...(role && { role }) });
    api.get(`/admin/users/?${params}`).then((r) => setData(r.data)).catch((e) => setMessage(apiError(e).message));
  }, [q, role]);
  useEffect(() => { const t = setTimeout(load, 300); return () => clearTimeout(t); }, [load]);

  async function toggle(u) {
    setMessage("");
    try { await api.post(`/admin/users/${encodeURIComponent(u.id)}/active/`, { active: !u.is_active, note: notes[u.id] || "" }); }
    catch (e) { setMessage(apiError(e).message); }
    load();
  }
  return (
    <>
      <div className="alert alert-info small">Roles cannot be changed here. Staff accounts are created on the server with <code>create_staff_user</code>. Switching an account off signs it out on its next request.</div>
      {message && <div className="alert alert-danger py-2">{message}</div>}
      <div className="d-flex gap-2 mb-3">
        <input className="form-control" placeholder="Search name or email" maxLength={100} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search accounts" />
        <select className="form-select w-auto" value={role} onChange={(e) => setRole(e.target.value)} aria-label="Filter by role">
          <option value="">All roles</option>
          {["customer", "pharmacist", "pharmacy_manager", "inventory_staff", "delivery_partner", "support_agent", "admin"].map((r) => <option key={r} value={r}>{label(r)}</option>)}
        </select>
      </div>
      {!data && !message && <div className="mq-skeleton" style={{ height: 160 }} aria-busy="true" />}
      {data && data.results.length === 0 && <EmptyState icon="users" title="No accounts match" />}
      {data && data.results.length > 0 && (
        <div className="card overflow-hidden">
          <div className="table-responsive">
            <table className="mq-table">
              <thead><tr><th>Account</th><th>Role</th><th>Status</th><th>Action</th></tr></thead>
              <tbody>
                {data.results.map((u) => (
                  <tr key={u.id}>
                    <td>{u.full_name}<div className="small text-muted">{u.email}</div></td>
                    <td className="text-capitalize">{label(u.role)}</td>
                    <td><span className={`mq-pill ${u.is_active ? "mq-pill--ok" : "mq-pill--off"}`}><i />{u.is_active ? "Active" : "Switched off"}</span></td>
                    <td style={{ minWidth: 280 }}>
                      {u.id === me.id ? <span className="text-muted small">you</span> : (
                        <div className="input-group input-group-sm">
                          <input className="form-control" placeholder="Reason (5+ characters)" maxLength={500} value={notes[u.id] || ""} onChange={(e) => setNotes({ ...notes, [u.id]: e.target.value })} aria-label={`Reason for ${u.full_name}`} />
                          <button className={`btn ${u.is_active ? "btn-outline-danger" : "btn-outline-primary"}`} disabled={(notes[u.id] || "").trim().length < 5}
                            onClick={() => toggle(u)}>{u.is_active ? "Switch off" : "Switch on"}</button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {data && <div className="small text-muted mt-2">{data.total} account(s). Showing the first {data.results.length}. Use search to narrow down.</div>}
    </>
  );
}

function Audit() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    api.get("/admin/audit/").then((r) => setData(r.data)).catch((e) => setError(apiError(e).message));
  }, []);
  useEffect(load, [load]);
  return (
    <>
      <p className="small text-muted">Every admin action here is recorded with who, when and why.</p>
      {error && <ErrorState message={error} onRetry={load} />}
      {!data && !error && <div className="mq-skeleton" style={{ height: 160 }} aria-busy="true" />}
      {data && data.results.length === 0 && <EmptyState icon="clipboard" title="Nothing recorded yet" />}
      <div className="d-grid gap-2">
        {(data?.results || []).map((a) => (
          <div key={a.id} className="card card-body small">
            <strong className="text-capitalize">{label(a.action)}</strong>
            <div>on {a.target_type} <code>{a.target_id}</code> by <code>{a.actor_id}</code> ({a.actor_role})</div>
            <div className="text-muted">{new Date(a.at).toLocaleString("en-IN")}{a.details?.note ? ` | ${a.details.note}` : ""}</div>
          </div>
        ))}
      </div>
    </>
  );
}

export default function AdminDashboardPage() {
  const { user } = useAuth();
  const isAdmin = user.role === "admin";
  const [tab, setTab] = useState("overview");
  const [attention, setAttention] = useState(null);
  const d = useDashboardData();
  useEffect(() => { api.get("/admin/attention/").then((r) => setAttention(r.data.results.length)).catch(() => {}); }, []);
  const tabs = [["overview", "Overview"], ["orders", "Orders"], ["inventory", "Inventory"],
    ["attention", `Needs attention${attention ? ` (${attention})` : ""}`], ...(isAdmin ? [["users", "Accounts"], ["audit", "Audit log"]] : [])];
  return (
    <main className="container py-4">
      <div className="mb-4">
        <h1 className="h3 mb-1">{isAdmin ? "Admin dashboard" : "Manager dashboard"}</h1>
        <p className="text-muted mb-0">Sales, orders, stock and accounts at a glance. Figures come straight from the server.</p>
      </div>
      <div className="mq-tabs mb-4" role="tablist" aria-label="Dashboard sections">
        {tabs.map(([k, text]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={`mq-tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>{text}</button>
        ))}
      </div>
      {tab === "overview" && <Overview d={d} />}
      {tab === "orders" && <OrdersTab d={d} />}
      {tab === "inventory" && <InventoryTab d={d} />}
      {tab === "attention" && <Attention onCount={setAttention} />}
      {tab === "users" && isAdmin && <Users />}
      {tab === "audit" && isAdmin && <Audit />}
    </main>
  );
}
