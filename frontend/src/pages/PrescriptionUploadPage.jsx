import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api, { apiError } from "../api/client";
import OcrNotice from "../components/OcrNotice";

const MAX_MB = 5; // must match MAX_UPLOAD_SIZE_MB on the server (the server is what actually enforces it)
const CONSENT_TEXT = "I confirm this is my own (or my dependant's) prescription. I understand the text read from the image " +
  "is automatic, may be wrong, and a pharmacist will check the original before anything is approved.";

export default function PrescriptionUploadPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState(null);
  const [notes, setNotes] = useState("");
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  function pick(e) {
    const f = e.target.files?.[0] || null;
    setFile(f);
    if (f && f.size > MAX_MB * 1024 * 1024) setErrors({ file: `This file is larger than ${MAX_MB} MB.` });
    else setErrors({});
  }

  async function submit(e) {
    e.preventDefault();
    if (!file) return setErrors({ file: "Choose a photo or PDF of your prescription." });
    if (file.size > MAX_MB * 1024 * 1024) return setErrors({ file: `This file is larger than ${MAX_MB} MB.` });
    if (!consent) return setErrors({ consent: "Please confirm to continue." });
    const form = new FormData();
    form.append("file", file);
    form.append("notes", notes);
    form.append("consent", "true");
    setBusy(true);
    setErrors({});
    try {
      const res = await api.post("/prescriptions/", form, { timeout: 60000 });
      navigate(`/prescriptions/${res.data.id}`);
    } catch (err) {
      const { message, fields } = apiError(err);
      setErrors({ form: message, ...fields });
      setBusy(false);
    }
  }

  return (
    <main className="container py-4" style={{ maxWidth: 640 }}>
      <Link to="/prescriptions" className="small">&larr; My prescriptions</Link>
      <h1 className="h4 mt-2">Upload a prescription</h1>
      <OcrNotice />
      <form onSubmit={submit} noValidate>
        {errors.form && <div className="alert alert-danger">{errors.form}</div>}
        <div className="mb-3">
          <label htmlFor="file" className="form-label">Photo or PDF (JPEG, PNG or PDF, up to {MAX_MB} MB)</label>
          <input id="file" type="file" accept="image/jpeg,image/png,application/pdf" onChange={pick}
            className={`form-control ${errors.file ? "is-invalid" : ""}`} />
          {errors.file && <div className="invalid-feedback">{errors.file}</div>}
          <div className="form-text">Use a flat, well-lit photo with the whole page visible. Only you and, after you submit, our pharmacists can open the file.</div>
        </div>
        <div className="mb-3">
          <label htmlFor="notes" className="form-label">Notes for the pharmacist (optional)</label>
          <textarea id="notes" className={`form-control ${errors.notes ? "is-invalid" : ""}`} rows={2} maxLength={300}
            value={notes} onChange={(e) => setNotes(e.target.value)} />
          {errors.notes && <div className="invalid-feedback">{errors.notes}</div>}
        </div>
        <div className="form-check mb-3">
          <input id="consent" type="checkbox" className={`form-check-input ${errors.consent ? "is-invalid" : ""}`}
            checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <label htmlFor="consent" className="form-check-label small">{CONSENT_TEXT}</label>
          {errors.consent && <div className="invalid-feedback d-block">{errors.consent}</div>}
        </div>
        <button className="btn btn-primary" disabled={busy}>{busy ? "Uploading..." : "Upload"}</button>
      </form>
    </main>
  );
}
