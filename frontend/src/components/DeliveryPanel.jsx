import { useEffect, useState } from "react";
import api from "../api/client";

// Shown to the customer on their order page. The handover code is for the delivery partner to type in,
// so keep it private until they are at the door.
export default function DeliveryPanel({ order }) {
  const [info, setInfo] = useState(null);
  const active = ["confirmed", "dispatched", "delivery_failed"].includes(order.status);
  useEffect(() => {
    if (!active) return undefined;
    const fetchInfo = () => api.get(`/orders/${encodeURIComponent(order.id)}/delivery/`).then((r) => setInfo(r.data)).catch(() => {});
    fetchInfo();
    const t = setInterval(fetchInfo, 30000);
    return () => clearInterval(t);
  }, [order.id, order.status, active]);
  if (!active || !info) return null;
  return (
    <div className="card card-body mb-3 small">
      {order.status === "confirmed" && <div>{info.partner_name ? `${info.partner_name} will pick up your order soon.` : "We are getting your order ready. A delivery partner will be assigned."}</div>}
      {order.status === "dispatched" && (
        <>
          <div>Your order is out for delivery{info.partner_name ? ` with ${info.partner_name}` : ""}.{info.failed_count > 0 && ` Previous failed attempts: ${info.failed_count}.`}</div>
          {info.handover_code && (
            <div className="mt-2">Give this code to the delivery partner only when you receive the parcel:
              <div className="fs-3 fw-bold font-monospace">{info.handover_code}</div></div>
          )}
          <div className="text-muted mt-1">There is no live map or tracking yet.</div>
        </>
      )}
      {order.status === "delivery_failed" && <div>We could not deliver after several attempts. Our team will contact you to arrange a new delivery or a refund.</div>}
    </div>
  );
}
