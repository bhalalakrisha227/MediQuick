import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api, { apiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import Icon from "../components/ui/Icon";
import StatusPill from "../components/ui/StatusPill";
import { EmptyState, ErrorState } from "../components/ui/States";
import { RX_STATUS } from "./prescriptionStatus";

// The server has these lists: queue (waiting + in review), clarification, approved, rejected.
// "Waiting" and "In Review" are the two halves of the server's queue list, split here by status.
const TABS = [
  { key: "waiting", label: "Waiting", scope: "queue", filter: (r) => r.status === "submitted", empty: "No prescriptions are waiting for a pharmacist." },
  { key: "in_review", label: "In Review", scope: "queue", filter: (r) => r.status === "in_review", empty: "Nothing is being reviewed right now." },
  { key: "approved", label: "Approved", scope: "approved", empty: "No approved prescriptions yet." },
  { key: "rejected", label: "Rejected", scope: "rejected", empty: "No rejected prescriptions." },
  { key: "clarification", label: "Clarification", scope: "clarification", empty: "No prescriptions are waiting for a customer's answer." },
];

export default function StaffPrescriptionsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState("waiting");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [claimError, setClaimError] = useState("");
  const [claiming, setClaiming] = useState("");
  const [reload, setReload] = useState(0);

  const current = TABS.find((t) => t.key === tab);
  const isPharmacist = user.role === "pharmacist"; // the server decides who may really claim

  const load = useCallback(() => {
    setRows(null);
    setError("");
    api.get("/staff/prescriptions/", { params: { scope: current.scope } })
      .then((res) => setRows(current.filter ? res.data.results.filter(current.filter) : res.data.results))
      .catch((err) => setError(apiError(err).message));
  }, [current]);
  useEffect(() => { load(); }, [load, reload]);

  async function claim(id) {
    setClaiming(id);
    setClaimError("");
    try {
      await api.post(`/staff/prescriptions/${encodeURIComponent(id)}/claim/`);
      navigate(`/staff/prescriptions/${id}`);
    } catch (err) {
      setClaimError(apiError(err).message);
      setClaiming("");
      setReload((n) => n + 1);
    }
  }

  return (
    <main className="container py-4">
      <div className="mb-4">
        <h1 className="h3 mb-1">Prescription review</h1>
        <p className="text-muted mb-0">
          Oldest first. Only a pharmacist can claim and decide; managers and admins can view and release stuck claims.
          Every time a file is opened it is logged.
        </p>
      </div>

      <div className="mq-tabs mb-3" role="tablist" aria-label="Prescription lists">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className={`mq-tab ${tab === t.key ? "active" : ""}`}
            onClick={() => { setTab(t.key); setClaimError(""); }}>{t.label}</button>
        ))}
      </div>

      {claimError && <div className="alert alert-danger" role="alert">{claimError}</div>}
      {error && <ErrorState message={error} onRetry={() => setReload((n) => n + 1)} />}
      {rows === null && !error && <div className="mq-skeleton" style={{ height: 220 }} aria-busy="true" />}
      {rows && rows.length === 0 && <EmptyState icon="clipboard" title={current.empty} />}
      {rows && rows.length > 0 && (
        <div className="card overflow-hidden">
          <div className="table-responsive">
            <table className="mq-table">
              <thead><tr><th>Submitted</th><th>File</th><th>Customer lists</th><th>Status</th><th>With</th><th /></tr></thead>
              <tbody>
                {rows.map((r) => {
                  const [color, label] = RX_STATUS[r.status] || ["secondary", r.status];
                  const mine = r.assigned_to_id === user.id;
                  return (
                    <tr key={r.id}>
                      <td className="text-nowrap">{r.submitted_at ? new Date(r.submitted_at).toLocaleString("en-IN") : "-"}</td>
                      <td>{r.file_name}</td>
                      <td>{r.item_count} medicine(s)</td>
                      <td><StatusPill color={color} label={label} /></td>
                      <td>{r.assigned_to ? <>{r.assigned_to}{mine && <span className="mq-pill mq-pill--ok ms-1">You</span>}</> : "-"}</td>
                      <td className="text-end text-nowrap">
                        {r.status === "submitted" && isPharmacist && (
                          <button className="btn btn-teal btn-sm me-2" disabled={claiming === r.id} onClick={() => claim(r.id)}>
                            {claiming === r.id ? "Claiming..." : "Claim"}
                          </button>
                        )}
                        <Link className="btn btn-outline-primary btn-sm" to={`/staff/prescriptions/${r.id}`}>
                          {mine ? "Continue" : "Open"}<Icon name="arrow" size={14} />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </main>
  );
}
