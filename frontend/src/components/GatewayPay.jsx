import { useState } from "react";
import api, { apiError } from "../api/client";
import { formatPaise } from "../utils/money";

const SCRIPT = "https://checkout.razorpay.com/v1/checkout.js";

function loadCheckout() {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = SCRIPT;
    s.onload = resolve;
    s.onerror = () => reject(new Error("The payment page could not be loaded. Check your connection and try again."));
    document.body.appendChild(s);
  });
}

// The browser only ever sees the public key id and the gateway order id. The server decides whether the
// order is paid: after the popup returns, it checks the signature AND asks the gateway for the real payment.
export default function GatewayPay({ order, config, resume, onDone, onError }) {
  const [busy, setBusy] = useState(false);

  async function pay() {
    setBusy(true);
    onError("");
    try {
      const { data: info } = await api.post(`/orders/${encodeURIComponent(order.id)}/payment/start/`);
      await loadCheckout();
      const rzp = new window.Razorpay({
        key: info.key_id, order_id: info.gateway_order_id, amount: info.amount_paise, currency: info.currency,
        name: "MediQuick", description: `Order ${info.order_number}`,
        handler: async (resp) => {
          try {
            await api.post(`/orders/${encodeURIComponent(order.id)}/payment/verify/`, {
              razorpay_order_id: resp.razorpay_order_id, razorpay_payment_id: resp.razorpay_payment_id,
              razorpay_signature: resp.razorpay_signature,
            });
          } catch (err) { onError(apiError(err).message); }
          setBusy(false);
          onDone();
        },
        modal: { ondismiss: () => { setBusy(false); onDone(); } },
      });
      rzp.on("payment.failed", (r) => onError(r?.error?.description || "The payment failed. You can try again."));
      rzp.open();
    } catch (err) {
      onError(err.response ? apiError(err).message : err.message);
      setBusy(false);
      onDone();
    }
  }

  return (
    <>
      {config.mode === "test" && (
        <div className="alert alert-warning small">
          <strong>PAYMENT TEST MODE.</strong> Use Razorpay's test cards or UPI only. No real money is charged.
        </div>
      )}
      <button className="btn btn-primary" disabled={busy} onClick={pay}>
        {resume ? "Resume payment" : "Pay"} {formatPaise(order.total_paise)}
      </button>
    </>
  );
}
