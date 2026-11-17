import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api, { apiError } from "../api/client";
import Icon from "../components/ui/Icon";
import { EmptyState, ErrorState } from "../components/ui/States";

// The icon is picked from where the alert links to, so no new field is needed from the server.
function iconFor(link = "") {
  if (link.startsWith("/orders")) return "box";
  if (link.startsWith("/prescriptions")) return "clipboard";
  return "bell";
}

export default function NotificationsPage() {
  const [data, setData] = useState(null);
  const [settings, setSettings] = useState(null);
  const [page, setPage] = useState(1);
  const [message, setMessage] = useState("");
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoadError("");
    api.get(`/notifications/?page=${page}`).then((r) => setData(r.data)).catch((e) => setLoadError(apiError(e).message));
  }, [page]);
  useEffect(load, [load]);
  useEffect(() => { api.get("/notifications/settings/").then((r) => setSettings(r.data)).catch(() => {}); }, []);

  async function toggleEmail(value) {
    setMessage("");
    try { setSettings((await api.patch("/notifications/settings/", { email: value })).data); }
    catch (e) { setMessage(apiError(e).message); }
  }
  async function readAll() {
    setBusy(true);
    setMessage("");
    try { await api.post("/notifications/read-all/"); load(); }
    catch (e) { setMessage(apiError(e).message); }
    finally { setBusy(false); }
  }
  async function open(n) { if (!n.read) await api.post(`/notifications/${encodeURIComponent(n.id)}/read/`).catch(() => {}); }

  const pages = data ? Math.max(1, Math.ceil(data.total / 20)) : 1;
  return (
    <main className="container py-4" style={{ maxWidth: 780 }}>
      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
        <div>
          <h1 className="h3 mb-1">Alerts</h1>
          <p className="text-muted mb-0">{data ? (data.unread ? `${data.unread} unread` : "You are all caught up") : "Updates about your orders and prescriptions"}</p>
        </div>
        <button className="btn btn-outline-primary" disabled={!data || data.unread === 0 || busy} onClick={readAll}>
          <Icon name="check" size={16} />Mark all as read
        </button>
      </div>

      {message && <div className="alert alert-danger py-2">{message}</div>}
      {loadError && <ErrorState message={loadError} onRetry={load} />}

      {settings && (
        <div className="card card-body mb-3 small">
          <div className="form-check form-switch">
            <input className="form-check-input" type="checkbox" id="emailOn" checked={settings.email} onChange={(e) => toggleEmail(e.target.checked)} />
            <label className="form-check-label fw-semibold" htmlFor="emailOn">Also email me about my orders and prescriptions</label>
          </div>
          <div className="text-muted mt-1">
            {settings.email_provider === "none"
              ? "Email is not set up on this server yet, so only the alerts below are shown."
              : "Emails go to your account address. Messages never include medicine names, your address or your delivery code."}
            {" "}SMS is not available.
          </div>
        </div>
      )}

      {!data && !loadError && (
        <div className="d-grid gap-2" aria-busy="true">{[0, 1, 2].map((i) => <div key={i} className="mq-skeleton" style={{ height: 78 }} />)}</div>
      )}
      {data && data.results.length === 0 && (
        <EmptyState icon="bell" title="No alerts yet">Updates about your orders and prescriptions appear here.</EmptyState>
      )}

      <div className="d-grid gap-2 mb-3">
        {(data?.results || []).map((n) => (
          <Link key={n.id} to={n.link} onClick={() => open(n)} className={`card mq-notif ${n.read ? "" : "unread"}`}>
            <span className="mq-notif__icon"><Icon name={iconFor(n.link)} size={20} /></span>
            <span className="flex-grow-1">
              <span className="d-flex justify-content-between gap-2">
                <strong className="text-navy" style={{ color: "var(--mq-navy)" }}>{n.title}</strong>
                <span className={`mq-pill ${n.read ? "mq-pill--off" : "mq-pill--ok"}`}>{n.read ? "Read" : "New"}</span>
              </span>
              <span className="d-block small text-secondary">{n.body}</span>
              <span className="d-block small text-muted mt-1">{new Date(n.created_at).toLocaleString("en-IN")}</span>
            </span>
          </Link>
        ))}
      </div>

      {pages > 1 && (
        <div className="d-flex gap-2 align-items-center justify-content-between">
          <button className="btn btn-outline-secondary btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Newer</button>
          <span className="small text-muted">Page {page} of {pages}</span>
          <button className="btn btn-outline-secondary btn-sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Older</button>
        </div>
      )}
    </main>
  );
}
