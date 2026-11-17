import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";
import StatusPill from "../components/ui/StatusPill";
import Icon from "../components/ui/Icon";
import { EmptyState, ErrorState } from "../components/ui/States";
import { RX_STATUS } from "./prescriptionStatus";

export default function PrescriptionsPage() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    setError(false);
    api.get("/prescriptions/").then((res) => setRows(res.data.results)).catch(() => setError(true));
  }, [reload]);

  return (
    <main className="container py-4" style={{ maxWidth: 820 }}>
      <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-4">
        <div>
          <h1 className="h3 mb-1">My prescriptions</h1>
          <p className="text-muted mb-0">A pharmacist reviews each prescription before you can order from it.</p>
        </div>
        <Link className="btn btn-teal" to="/prescriptions/new"><Icon name="upload" size={16} />Upload a prescription</Link>
      </div>
      {error && <ErrorState message="Could not load your prescriptions." onRetry={() => setReload((n) => n + 1)} />}
      {rows === null && !error && <div className="d-grid gap-2" aria-busy="true">{[0, 1, 2].map((i) => <div key={i} className="mq-skeleton" style={{ height: 72 }} />)}</div>}
      {rows && rows.length === 0 && (
        <EmptyState icon="clipboard" title="No prescriptions yet" action={<Link to="/prescriptions/new" className="btn btn-primary">Upload a prescription</Link>}>
          Upload a photo or PDF to order prescription medicines.
        </EmptyState>
      )}
      <div className="d-grid gap-2">
        {rows?.map((r) => {
          const [color, label] = RX_STATUS[r.status] || ["secondary", r.status];
          return (
            <Link key={r.id} to={`/prescriptions/${r.id}`} className="card mq-notif mq-card-hover align-items-center justify-content-between">
              <span className="d-flex gap-3 align-items-center">
                <span className="mq-notif__icon"><Icon name="clipboard" size={20} /></span>
                <span>
                  <strong style={{ color: "var(--mq-navy)" }}>{r.original_name}</strong>
                  <span className="d-block small text-muted">{new Date(r.created_at).toLocaleString("en-IN")} · {r.item_count} medicine(s) listed</span>
                </span>
              </span>
              <StatusPill color={color} label={label} />
            </Link>
          );
        })}
      </div>
    </main>
  );
}
