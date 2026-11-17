import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api, { apiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import RxFilePreview from "../components/RxFilePreview";
import Icon from "../components/ui/Icon";
import StatusPill from "../components/ui/StatusPill";
import { ErrorState } from "../components/ui/States";
import { RX_STATUS } from "./prescriptionStatus";

function ProductPicker({ onPick }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  useEffect(() => {
    if (q.trim().length < 2) { setResults([]); return undefined; }
    let stale = false;
    const t = setTimeout(() => {
      api.get("/products/", { params: { q: q.trim(), page_size: 20 } })
        .then((res) => !stale && setResults(res.data.results.filter((p) => p.requires_prescription && p.purchasable_online)))
        .catch(() => !stale && setResults([]));
    }, 250);
    return () => { stale = true; clearTimeout(t); };
  }, [q]);
  return (
    <div className="mb-2">
      <input className="form-control form-control-sm" placeholder="Search a prescription medicine in the catalogue..." value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search catalogue" />
      {results.length > 0 && (
        <ul className="list-group mt-1">
          {results.map((p) => (
            <li key={p.id} className="list-group-item list-group-item-action py-2 small" role="button" onClick={() => { onPick(p); setQ(""); setResults([]); }}>
              {p.name} <span className="text-muted">({p.pack_size})</span> <span className="mq-pill mq-pill--warn">Schedule {p.schedule}</span>
            </li>
          ))}
        </ul>
      )}
      {q.trim().length >= 2 && results.length === 0 && <div className="small text-muted mt-1">No matching prescription medicine that can be sold online.</div>}
    </div>
  );
}

export default function StaffPrescriptionPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const [rx, setRx] = useState(null);
  const [state, setState] = useState("loading");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [errors, setErrors] = useState({});
  const [lines, setLines] = useState([]);       // the pharmacist's own approved list: {product_id, name, max_quantity}
  const [reg, setReg] = useState("");
  const [days, setDays] = useState(30);
  const [note, setNote] = useState("");
  const [attest, setAttest] = useState(false);
  const [reason, setReason] = useState("");
  const [question, setQuestion] = useState("");

  const load = useCallback(() => api.get(`/staff/prescriptions/${encodeURIComponent(id)}/`)
    .then((res) => { setRx(res.data); setState("ok"); })
    .catch((err) => setState(err.response?.status === 404 ? "missing" : "error")), [id]);
  useEffect(() => { load(); }, [load]);

  async function act(path, payload) {
    setBusy(true); setMessage(""); setErrors({});
    try {
      const res = await api.post(`/staff/prescriptions/${id}/${path}/`, payload || {});
      setRx(res.data);
      return true;
    } catch (err) {
      const { message: m, fields } = apiError(err);
      setMessage(m); setErrors(fields);
      return false;
    } finally { setBusy(false); }
  }

  if (state === "loading") return <main className="container py-4" aria-busy="true"><div className="mq-skeleton" style={{ height: 320 }} /></main>;
  if (state === "missing") return <main className="container py-4"><p>Prescription not found.</p><Link to="/staff/prescriptions">Back to the queue</Link></main>;
  if (state === "error") return <main className="container py-4"><ErrorState message="Could not load this prescription." onRetry={() => { setState("loading"); load(); }} /><Link to="/staff/prescriptions">Back to the queue</Link></main>;

  const isPharmacist = user.role === "pharmacist";
  const mine = rx.status === "in_review" && rx.assigned_to?.id === user.id;
  const [color, label] = RX_STATUS[rx.status] || ["secondary", rx.status];
  const claimedAt = rx.assigned_to?.at || "none";
  // Informational only: the server re-checks every one of these, including that the original was opened after claiming.
  const checks = [
    { ok: mine, text: "You have claimed this prescription" },
    { ok: false, server: true, text: "Original file opened after claiming (checked by the server from the access log)" },
    { ok: lines.length > 0 && lines.every((l) => Number(l.max_quantity) >= 1), text: "At least one medicine with a quantity, chosen by you" },
    { ok: reg.trim().length >= 3, text: "Your registration number entered (format check only, not verified with any council)" },
    { ok: attest, text: "You confirm you checked the original prescription" },
  ];
  const ready = lines.length > 0 && lines.every((l) => Number(l.max_quantity) >= 1) && reg.trim().length >= 3 && attest;

  return (
    <main className="container py-4" style={{ maxWidth: 960 }}>
      <Link to="/staff/prescriptions" className="small fw-semibold">&larr; Back to the queue</Link>
      <div className="d-flex flex-wrap align-items-center gap-3 mt-2 mb-3">
        <h1 className="h3 mb-0">Prescription review</h1>
        <StatusPill color={color} label={label} large />
      </div>
      <div className="alert alert-secondary small d-flex gap-2"><Icon name="info" size={18} /><span>{rx.notice}</span></div>
      {message && <div className="alert alert-danger" role="alert">{message}</div>}

      <div className="row g-4">
        <div className="col-lg-6">
          <h2 className="h6">Original prescription (decide from this)</h2>
          {/* Re-mounted after claiming so the server logs a view made AFTER the claim, which decisions require. */}
          <div className="mq-rx-file"><RxFilePreview key={`${rx.status}-${claimedAt}`} id={rx.id} /></div>
          {rx.notes && <p className="small mt-2"><strong>Customer&apos;s note:</strong> {rx.notes}</p>}
        </div>
        <div className="col-lg-6">
          <div className="card p-3 mb-3"><h2 className="h6">What the customer listed (not verified)</h2>
          {rx.items.length === 0 ? <p className="small text-muted">Nothing listed.</p> : (
            <ul className="small">{rx.items.map((i, n) => (
              <li key={n}>{i.name} {i.strength} {i.dosage} {i.duration}{i.quantity ? ` x${i.quantity}` : ""}{i.product_name ? ` (linked: ${i.product_name})` : ""}</li>
            ))}</ul>
          )}
          <details className="small">
            <summary>Automatic text reading (may be wrong)</summary>
            <pre className="bg-light border rounded p-2" style={{ whiteSpace: "pre-wrap" }}>{rx.ocr.text || "(none)"}</pre>
          </details>
          {rx.review?.clarification && <p className="small mt-2 mb-0"><strong>Question asked:</strong> {rx.review.clarification.message}</p>}
          </div>
          {mine && (
            <div className="card p-3">
              <h2 className="h6">Required confirmations</h2>
              <ul className="mq-checklist">
                {checks.map((c) => (
                  <li key={c.text} className={`${c.ok ? "ok" : ""} ${c.server ? "server" : ""}`}>
                    <span className="mq-checklist__dot">{c.ok && <Icon name="check" size={12} strokeWidth={3} />}</span>{c.text}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <hr />
      {rx.status === "submitted" && (isPharmacist
        ? <button className="btn btn-teal" disabled={busy} onClick={() => act("claim")}>Claim for review</button>
        : <p className="text-muted">Only a pharmacist can claim and decide.</p>)}

      {rx.status === "in_review" && !mine && (
        <div>
          <p>Being reviewed by <strong>{rx.assigned_to?.name}</strong>.</p>
          {user.role !== "customer" && <button className="btn btn-outline-secondary btn-sm" disabled={busy} onClick={() => act("release")}>Release this claim</button>}
        </div>
      )}

      {mine && (
        <section>
          <p className="small text-muted">You have claimed this. Decide only after reading the original file shown above.</p>

          <div className="mq-action-box mb-3"><h3>Approve</h3>
          <p className="small text-muted">List exactly what you approve. Nothing is filled in for you, and substitutes are never allowed.</p>
          <ProductPicker onPick={(p) => setLines((prev) => (prev.some((l) => l.product_id === p.id) ? prev : [...prev, { product_id: p.id, name: p.name, max_quantity: 1 }]))} />
          {rx.items.some((i) => i.product_id) && (
            <button className="btn btn-link btn-sm p-0 mb-2" onClick={() => setLines(rx.items.filter((i) => i.product_id).map((i) => ({ product_id: i.product_id, name: i.product_name, max_quantity: 1 })))}>
              Start from the customer&apos;s linked medicines (you still choose each quantity)
            </button>
          )}
          {errors.items && <div className="text-danger small">{errors.items}</div>}
          {lines.map((l, n) => (
            <div key={l.product_id} className="d-flex gap-2 align-items-center mb-1">
              <span className="flex-grow-1 small">{l.name}</span>
              <input type="number" min="1" max="100" className={`form-control form-control-sm ${errors[`items.${n}.max_quantity`] ? "is-invalid" : ""}`} style={{ width: 90 }}
                aria-label={`Maximum units of ${l.name}`} value={l.max_quantity}
                onChange={(e) => setLines((prev) => prev.map((x, i) => (i === n ? { ...x, max_quantity: e.target.value === "" ? "" : Number(e.target.value) } : x)))} />
              <button className="btn btn-sm btn-link text-danger" onClick={() => setLines((prev) => prev.filter((_, i) => i !== n))}>Remove</button>
              {errors[`items.${n}.product_id`] && <span className="text-danger small">{errors[`items.${n}.product_id`]}</span>}
            </div>
          ))}
          <div className="row g-2 mt-1">
            <div className="col-md-5">
              <input className={`form-control form-control-sm ${errors.registration_number ? "is-invalid" : ""}`} placeholder="Your pharmacist registration number" aria-label="Registration number" value={reg} onChange={(e) => setReg(e.target.value)} />
              {errors.registration_number && <div className="invalid-feedback">{errors.registration_number}</div>}
            </div>
            <div className="col-md-3">
              <input type="number" min="1" className={`form-control form-control-sm ${errors.valid_days ? "is-invalid" : ""}`} aria-label="Valid for days" value={days} onChange={(e) => setDays(Number(e.target.value))} />
              <div className="form-text">days valid</div>
              {errors.valid_days && <div className="invalid-feedback">{errors.valid_days}</div>}
            </div>
            <div className="col-12"><input className="form-control form-control-sm" placeholder="Note for the customer (optional)" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></div>
          </div>
          <div className="form-check my-2">
            <input id="attest" type="checkbox" className="form-check-input" checked={attest} onChange={(e) => setAttest(e.target.checked)} />
            <label htmlFor="attest" className="form-check-label small">I checked the original prescription and the medicines and quantities above are my own decision.</label>
          </div>
          {errors.attest_original_checked && <div className="text-danger small">{errors.attest_original_checked}</div>}
          <button className="btn btn-teal" disabled={busy || !ready}
            onClick={() => window.confirm("Approve this prescription for the medicines and quantities listed?") && act("approve", { items: lines, registration_number: reg, valid_days: days, note, attest_original_checked: attest })}>
            Approve
          </button>
          </div>

          <div className="mq-action-box mb-3"><h3>Ask the customer a question</h3>
          <textarea className={`form-control ${errors.message ? "is-invalid" : ""}`} rows={2} maxLength={500} value={question} onChange={(e) => setQuestion(e.target.value)} aria-label="Question for the customer" />
          {errors.message && <div className="invalid-feedback">{errors.message}</div>}
          <button className="btn btn-outline-primary btn-sm mt-1" disabled={busy} onClick={() => act("clarify", { message: question })}>Send question</button>
          </div>

          <div className="mq-action-box mb-3"><h3>Reject</h3>
          <textarea className={`form-control ${errors.reason ? "is-invalid" : ""}`} rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reason for rejecting" placeholder="The customer will see this reason" />
          {errors.reason && <div className="invalid-feedback">{errors.reason}</div>}
          <button className="btn btn-outline-danger btn-sm mt-1" disabled={busy}
            onClick={() => window.confirm("Reject this prescription?") && act("reject", { reason })}>Reject</button>
          </div>

          <div className="mt-4"><button className="btn btn-link btn-sm" disabled={busy} onClick={() => act("release")}>Release my claim</button></div>
        </section>
      )}

      {rx.status === "approved" && rx.review?.approval && (
        <div className="alert alert-success small">
          Approved by {rx.review.approval.pharmacist_name} (reg. {rx.review.approval.registration_number}), valid until {new Date(rx.review.approval.valid_until).toLocaleDateString("en-IN")}.
          <ul className="mb-0">{rx.review.approval.items.map((i) => <li key={i.product_id}>{i.name}: max {i.max_quantity}, {i.remaining} left</li>)}</ul>
        </div>
      )}
      {rx.status === "rejected" && rx.review?.rejection && <div className="alert alert-danger small">Rejected: {rx.review.rejection.reason}</div>}

      <h2 className="h6 mt-4">Audit trail</h2>
      {rx.audit.length === 0 ? <p className="small text-muted">No staff actions yet.</p> : (
        <ul className="small">{rx.audit.map((a, n) => <li key={n}>{new Date(a.at).toLocaleString()}: {a.actor_name} ({a.actor_role}) {a.action}</li>)}</ul>
      )}
    </main>
  );
}
