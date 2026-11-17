import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import api, { apiError } from "../api/client";
import OcrNotice from "../components/OcrNotice";
import RxFilePreview from "../components/RxFilePreview";
import { RX_STATUS } from "./prescriptionStatus";
import StatusPill from "../components/ui/StatusPill";

const BLANK = { name: "", strength: "", dosage: "", duration: "", quantity: "", product_id: null, product_name: "" };

function toRow(item) {
  return { name: item.name || "", strength: item.strength || "", dosage: item.dosage || "", duration: item.duration || "",
    quantity: item.quantity ?? "", product_id: item.product_id || null, product_name: item.product_name || "" };
}

function toPayload(rows) {
  return rows.map((r) => ({
    name: r.name, strength: r.strength, dosage: r.dosage, duration: r.duration,
    quantity: r.quantity === "" ? null : Number(r.quantity), product_id: r.product_id,
  }));
}

export default function PrescriptionPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [rx, setRx] = useState(null);
  const [state, setState] = useState("loading");
  const [rows, setRows] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;

  const load = useCallback(() => {
    return api.get(`/prescriptions/${encodeURIComponent(id)}/`)
      .then((res) => {
        setRx(res.data);
        if (!dirtyRef.current) { setRows(res.data.items.map(toRow)); setNotes(res.data.notes || ""); }
        setState("ok");
        return res.data;
      })
      .catch((err) => setState(err.response?.status === 404 ? "missing" : "error"));
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // While the server is reading the file, check again every 2 seconds.
  useEffect(() => {
    if (rx?.status !== "processing") return undefined;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [rx?.status, load]);

  function setRow(i, patch) {
    setRows((prev) => prev.map((r, n) => (n === i ? { ...r, ...patch } : r)));
    setDirty(true);
  }
  function addRow(row) { setRows((prev) => (prev.length >= 30 ? prev : [...prev, row])); setDirty(true); }
  function removeRow(i) { setRows((prev) => prev.filter((_, n) => n !== i)); setDirty(true); }

  function addCandidate(c, suggestion) {
    addRow({ ...BLANK, name: c.name_guess, strength: c.strength?.text || "", dosage: c.dosage || "", duration: c.duration || "",
      quantity: c.quantity ?? "", product_id: suggestion?.product_id || null, product_name: suggestion?.name || "" });
  }

  async function call(fn) {
    setBusy(true);
    setMessage("");
    setErrors({});
    try { await fn(); } catch (err) {
      const { message: m, fields } = apiError(err);
      setMessage(m);
      setErrors(fields);
      return false;
    } finally { setBusy(false); }
    return true;
  }

  async function save() {
    const ok = await call(async () => {
      const res = await api.patch(`/prescriptions/${id}/`, { items: toPayload(rows), notes });
      setRx(res.data);
      setRows(res.data.items.map(toRow));
      setDirty(false);
    });
    if (ok) setMessage("Saved.");
    return ok;
  }

  async function submitToPharmacist() {
    if (dirty && !(await save())) return;
    if (!window.confirm("Send this to a pharmacist? You will not be able to change it while they check it.")) return;
    await call(async () => { const res = await api.post(`/prescriptions/${id}/submit/`); setRx(res.data); });
  }

  async function withdraw() {
    if (!window.confirm("Withdraw this prescription? Your file will be deleted.")) return;
    const ok = await call(async () => { await api.post(`/prescriptions/${id}/withdraw/`); });
    if (ok) navigate("/prescriptions");
  }

  async function retry() {
    await call(async () => { const res = await api.post(`/prescriptions/${id}/retry-ocr/`); setRx(res.data); });
  }

  if (state === "loading") return <main className="container py-4">Loading...</main>;
  if (state === "missing") return <main className="container py-4"><p>Prescription not found.</p><Link to="/prescriptions">My prescriptions</Link></main>;
  if (state === "error") return <main className="container py-4"><div className="alert alert-danger">Could not load this prescription.</div></main>;

  const [color, label] = RX_STATUS[rx.status] || ["secondary", rx.status];
  const ocr = rx.ocr;
  const editable = rx.editable;
  const candidates = ocr.candidates || [];

  return (
    <main className="container py-4" style={{ maxWidth: 820 }}>
      <Link to="/prescriptions" className="small">&larr; My prescriptions</Link>
      <h1 className="h4 mt-2">{rx.file.original_name} <StatusPill color={color} label={label} large /></h1>
      <OcrNotice />
      {message && <div className={`alert ${message === "Saved." ? "alert-success" : "alert-danger"}`}>{message}</div>}

      {(rx.status === "submitted" || rx.status === "in_review") && (
        <div className="alert alert-primary">
          {rx.status === "in_review" ? "A pharmacist is checking your prescription now." : "Sent to the pharmacists."}{" "}
          It is <strong>not approved yet</strong>. You cannot change it while it is being checked.
        </div>
      )}
      {rx.status === "clarification_requested" && rx.review?.clarification && (
        <div className="alert alert-warning">
          <strong>The pharmacist asked:</strong> {rx.review.clarification.message}
          <div className="small mt-1">Update your medicines or notes below, then press &ldquo;Send reply to the pharmacist&rdquo;.</div>
        </div>
      )}
      {rx.status === "rejected" && (
        <div className="alert alert-danger">
          <strong>This prescription was not approved.</strong> Reason given: {rx.review?.rejection?.reason}
          <div className="mt-2"><Link to="/prescriptions/new" className="btn btn-sm btn-outline-danger">Upload a new prescription</Link></div>
        </div>
      )}
      {rx.status === "approved" && rx.review?.approval && (
        <div className="alert alert-success">
          <strong>Approved by pharmacist {rx.review.approval.pharmacist_name}.</strong> Valid until {new Date(rx.review.approval.valid_until).toLocaleDateString("en-IN")}.
          <ul className="mb-2 mt-2">
            {rx.review.approval.items.map((i) => (
              <li key={i.product_id}>{i.name}: up to {i.max_quantity} unit(s), {i.remaining} left</li>
            ))}
          </ul>
          <div className="small">Only these medicines and quantities can be ordered with this prescription, and only until the date above.</div>
          <Link to="/shop?rx=prescription" className="btn btn-sm btn-success mt-2">Shop prescription medicines</Link>
        </div>
      )}

      {rx.status !== "withdrawn" && (
        <section className="mb-4">
          <h2 className="h6">Your original file</h2>
          <RxFilePreview id={id} />
        </section>
      )}

      {rx.status === "processing" && <p className="text-muted">Reading your prescription. This page updates by itself.</p>}

      {rx.status === "needs_customer_review" && ocr.status !== "done" && (
        <div className="alert alert-warning">
          {ocr.status === "unavailable"
            ? "Automatic reading is not available on this server right now."
            : "Automatic reading did not work for this file."}{" "}
          You can add your medicines by hand below, try again, or send it as it is so a pharmacist can read the original.
          <div className="mt-2"><button className="btn btn-sm btn-outline-secondary" disabled={busy} onClick={retry}>Try reading again</button></div>
        </div>
      )}

      {ocr.status === "done" && rx.status !== "withdrawn" && (
        <section className="mb-4">
          <h2 className="h6">Text the computer read (may be wrong)</h2>
          {ocr.text.trim() ? <pre className="bg-light border rounded p-2 small" style={{ whiteSpace: "pre-wrap" }}>{ocr.text}</pre>
            : <p className="small text-muted">No text could be read from this file.</p>}
          {editable && candidates.length > 0 && (
            <>
              <h3 className="h6 mt-3">Possible medicine lines</h3>
              <p className="small text-muted">These are guesses. Add the ones that match your prescription, then check every detail.</p>
              <ul className="list-group">
                {candidates.map((c) => (
                  <li key={c.line_index} className="list-group-item">
                    <div className="small text-muted">Read as: {c.raw}</div>
                    <div className="d-flex flex-wrap gap-2 align-items-center mt-1">
                      <strong>{c.name_guess}</strong>
                      {c.strength && <span className="badge text-bg-light border">{c.strength.text}</span>}
                      {c.dosage && <span className="badge text-bg-light border">{c.dosage}</span>}
                      {c.duration && <span className="badge text-bg-light border">{c.duration}</span>}
                      <button className="btn btn-sm btn-outline-primary ms-auto" onClick={() => addCandidate(c, null)}>Add to my list</button>
                    </div>
                    {c.suggestions.length > 0 && (
                      <div className="mt-2 small">
                        Catalogue matches (not a decision, please check):
                        {c.suggestions.map((s) => (
                          <div key={s.product_id} className="d-flex flex-wrap gap-2 align-items-center mt-1">
                            <span>{s.name}</span>
                            {s.strength_match === false && <span className="badge text-bg-danger">Different strength</span>}
                            {s.requires_prescription && <span className="badge text-bg-warning">Prescription medicine</span>}
                            <button className="btn btn-sm btn-link p-0" onClick={() => addCandidate(c, s)}>Add and link</button>
                          </div>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      {rx.status !== "processing" && rx.status !== "withdrawn" && (
        <section className="mb-4">
          <h2 className="h6">Medicines on your prescription</h2>
          {rows.length === 0 && <p className="small text-muted">{editable ? "Nothing added yet. Adding the medicines helps the pharmacist, but you can also send the prescription as it is." : "No medicines were listed."}</p>}
          {rows.map((r, i) => (
            <div key={i} className="card card-body mb-2">
              <div className="row g-2">
                <div className="col-md-5">
                  <input className={`form-control form-control-sm ${errors[`items.${i}.name`] ? "is-invalid" : ""}`} placeholder="Medicine name as written"
                    aria-label="Medicine name" value={r.name} disabled={!editable} maxLength={120} onChange={(e) => setRow(i, { name: e.target.value })} />
                  {errors[`items.${i}.name`] && <div className="invalid-feedback">{errors[`items.${i}.name`]}</div>}
                </div>
                <div className="col-6 col-md-2"><input className="form-control form-control-sm" placeholder="Strength" aria-label="Strength" value={r.strength} disabled={!editable} maxLength={40} onChange={(e) => setRow(i, { strength: e.target.value })} /></div>
                <div className="col-6 col-md-2"><input className="form-control form-control-sm" placeholder="Dosage" aria-label="Dosage" value={r.dosage} disabled={!editable} maxLength={60} onChange={(e) => setRow(i, { dosage: e.target.value })} /></div>
                <div className="col-6 col-md-2"><input className="form-control form-control-sm" placeholder="Duration" aria-label="Duration" value={r.duration} disabled={!editable} maxLength={40} onChange={(e) => setRow(i, { duration: e.target.value })} /></div>
                <div className="col-6 col-md-1">
                  <input className={`form-control form-control-sm ${errors[`items.${i}.quantity`] ? "is-invalid" : ""}`} type="number" min="1" max="999" placeholder="Qty" aria-label="Quantity"
                    value={r.quantity} disabled={!editable} onChange={(e) => setRow(i, { quantity: e.target.value })} />
                </div>
              </div>
              <div className="d-flex justify-content-between small mt-2">
                <span>{r.product_id ? <>Linked to catalogue item: <strong>{r.product_name}</strong>{editable && <button className="btn btn-link btn-sm py-0" onClick={() => setRow(i, { product_id: null, product_name: "" })}>Unlink</button>}</> : <span className="text-muted">Not linked to a catalogue item</span>}</span>
                {editable && <button className="btn btn-link btn-sm py-0 text-danger" onClick={() => removeRow(i)}>Remove</button>}
              </div>
            </div>
          ))}
          {editable && (
            <>
              <button className="btn btn-sm btn-outline-secondary" disabled={rows.length >= 30} onClick={() => addRow({ ...BLANK })}>+ Add a medicine by hand</button>
              <div className="mt-3">
                <label htmlFor="notes" className="form-label small">Notes for the pharmacist</label>
                <textarea id="notes" className="form-control" rows={2} maxLength={300} value={notes} onChange={(e) => { setNotes(e.target.value); setDirty(true); }} />
              </div>
            </>
          )}
          {!editable && rx.notes && <p className="small mt-2">Your note: {rx.notes}</p>}
        </section>
      )}

      {editable && (
        <div className="d-flex gap-2 flex-wrap">
          <button className="btn btn-outline-primary" disabled={busy || !dirty} onClick={save}>Save changes</button>
          <button className="btn btn-primary" disabled={busy} onClick={submitToPharmacist}>{rx.status === "clarification_requested" ? "Send reply to the pharmacist" : "Send to a pharmacist"}</button>
          <button className="btn btn-outline-danger ms-auto" disabled={busy} onClick={withdraw}>Withdraw and delete</button>
        </div>
      )}
      {rx.status === "processing" && (
        <button className="btn btn-outline-danger" disabled={busy} onClick={withdraw}>Withdraw and delete</button>
      )}
    </main>
  );
}
