import { useEffect, useState } from "react";
import api from "../api/client";
import StatusPill from "../components/ui/StatusPill";

function StatusRow({ label, state }) {
  const badge = { checking: "secondary", ok: "success", down: "danger" }[state];
  const text = { checking: "Checking...", ok: "Connected", down: "Not reachable" }[state];
  return (
    <li className="list-group-item d-flex justify-content-between align-items-center">
      {label}
      <StatusPill color={badge} label={text} />
    </li>
  );
}

export default function StatusPage() {
  const [apiState, setApiState] = useState("checking");
  const [dbState, setDbState] = useState("checking");

  useEffect(() => {
    api.get("/health/").then(() => setApiState("ok")).catch(() => setApiState("down"));
    api.get("/health/db/").then(() => setDbState("ok")).catch(() => setDbState("down"));
  }, []);

  return (
    <main className="container py-5" style={{ maxWidth: 560 }}>
      <h1 className="h3 mq-brand mb-1">MediQuick</h1>
      <p className="text-muted">
        Phase 0 setup check. This is a development build, not a working pharmacy.
      </p>
      <ul className="list-group">
        <StatusRow label="Backend API (Django)" state={apiState} />
        <StatusRow label="Database (MongoDB Atlas)" state={dbState} />
      </ul>
    </main>
  );
}
