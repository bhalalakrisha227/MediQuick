// Turns the existing [bootstrap-colour, label] status tables into the new pill style.
const TONES = { success: "ok", warning: "warn", danger: "danger", info: "info", primary: "info", secondary: "off" };

export default function StatusPill({ color = "secondary", label, large = false }) {
  return <span className={`mq-pill mq-pill--${TONES[color] || "off"} ${large ? "mq-pill--lg" : ""}`}><i />{label}</span>;
}
