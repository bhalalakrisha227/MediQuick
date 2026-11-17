const LABELS = {
  in_stock: ["ok", "In stock"],
  low_stock: ["warn", "Low stock"],
  out_of_stock: ["off", "Out of stock"],
};

// availability is null when the server has no inventory information; we then show nothing rather than guess.
export default function StockBadge({ availability }) {
  if (!availability || !LABELS[availability.status]) return null;
  const [tone, text] = LABELS[availability.status];
  return <span className={`mq-pill mq-pill--${tone}`}><i />{text}</span>;
}
