import { useEffect, useState } from "react";
import api from "../api/client";
import NavButton from "./ui/NavButton";

// Polls the unread count once a minute (no push yet). Stops when the tab is hidden.
// Renders the shared NavButton, so it looks exactly like the Shop button.
export default function NotificationBell() {
  const [unread, setUnread] = useState(0);
  useEffect(() => {
    let alive = true;
    const fetchCount = () => {
      if (document.hidden) return;
      api.get("/notifications/unread-count/").then((r) => alive && setUnread(r.data.unread)).catch(() => {});
    };
    fetchCount();
    const t = setInterval(fetchCount, 60000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  return (
    <NavButton to="/notifications" icon="bell" label="Alerts" count={unread} variant="alert"
      ariaLabel={`Alerts, ${unread} unread`} />
  );
}
