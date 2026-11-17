import Icon from "./Icon";

// Maps the real order status to a position on a 4-step line. No live GPS tracking exists,
// so this only shows the stage the order has reached.
const STEPS = ["Placed", "Confirmed", "Out for delivery", "Delivered"];
const POSITION = {
  pending_payment: 0, processing_payment: 0, confirming_payment: 0, payment_review: 0,
  confirmed: 1, dispatched: 2, delivery_failed: 2, delivered: 3,
};

export default function OrderTracker({ status }) {
  const at = POSITION[status];
  if (at === undefined) return null; // cancelled / expired: no progress line
  return (
    <ol className="mq-tracker" aria-label="Order progress">
      {STEPS.map((label, i) => (
        <li key={label} className={`${i <= at ? "done" : ""} ${i === at ? "current" : ""}`} aria-current={i === at ? "step" : undefined}>
          <span className="mq-tracker__dot">{i <= at && <Icon name="check" size={13} strokeWidth={3} />}</span>
          {label}
        </li>
      ))}
    </ol>
  );
}
