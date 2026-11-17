import { useEffect, useState } from "react";
import api from "../api/client";

// Fetches the original file with the user's login (a plain <img src> could not send it) and shows it.
// Opening it is what the server logs for staff, so staff pages remount this (via `key`) after claiming.
export default function RxFilePreview({ id }) {
  const [src, setSrc] = useState(null);
  const [kind, setKind] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let url = null;
    let cancelled = false;
    api.get(`/prescriptions/${encodeURIComponent(id)}/file/`, { responseType: "blob", timeout: 30000 })
      .then((res) => {
        if (cancelled) return;
        url = URL.createObjectURL(res.data);
        setKind(res.data.type);
        setSrc(url);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [id]);
  if (failed) return <p className="small text-muted">The original file could not be shown.</p>;
  if (!src) return <p className="small text-muted">Loading the file...</p>;
  if (kind.startsWith("image/")) return <img src={src} alt="The uploaded prescription" className="img-fluid border rounded" style={{ maxHeight: 520 }} />;
  return <a href={src} target="_blank" rel="noreferrer" className="btn btn-outline-secondary btn-sm">Open the PDF</a>;
}
