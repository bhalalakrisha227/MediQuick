// Small dependency-free SVG charts. They draw exactly the numbers they are given.

export function BarChart({ data, format = (v) => String(v), height = 190, label = "Bar chart" }) {
  const W = 640, PAD = { l: 8, r: 8, t: 12, b: 26 };
  const max = Math.max(1, ...data.map((d) => d.value));
  const innerH = height - PAD.t - PAD.b;
  const step = (W - PAD.l - PAD.r) / Math.max(1, data.length);
  const barW = Math.max(2, Math.min(28, step * 0.7));
  const ticks = [0, 0.5, 1];
  return (
    <svg viewBox={`0 0 ${W} ${height}`} width="100%" role="img" aria-label={label} style={{ display: "block" }}>
      {ticks.map((t) => {
        const y = PAD.t + innerH * (1 - t);
        return <line key={t} x1={PAD.l} x2={W - PAD.r} y1={y} y2={y} stroke="#e2e8f0" strokeDasharray={t === 0 ? "" : "3 4"} />;
      })}
      {data.map((d, i) => {
        const h = d.value > 0 ? Math.max(2, (d.value / max) * innerH) : 0;
        const x = PAD.l + step * i + (step - barW) / 2;
        return (
          <g key={d.key ?? d.label}>
            <rect x={x} y={PAD.t + innerH - h} width={barW} height={h} rx="3" fill="#0f766e" opacity="0.9">
              <title>{d.title || `${d.label}: ${format(d.value)}`}</title>
            </rect>
          </g>
        );
      })}
      {data.length > 0 && <text x={PAD.l} y={height - 6} fontSize="11" fill="#64748b">{data[0].label}</text>}
      {data.length > 1 && <text x={W - PAD.r} y={height - 6} fontSize="11" fill="#64748b" textAnchor="end">{data[data.length - 1].label}</text>}
      <text x={W - PAD.r} y={PAD.t - 2} fontSize="11" fill="#64748b" textAnchor="end">max {format(max)}</text>
    </svg>
  );
}

const PALETTE = ["#0f766e", "#101b35", "#14b8a6", "#64748b", "#d97706", "#dc2626", "#7c3aed", "#0ea5e9", "#84cc16", "#94a3b8"];

export function Donut({ parts, label = "Breakdown", centre }) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  const R = 52, C = 2 * Math.PI * R;
  let offset = 0;
  return (
    <div className="d-flex flex-wrap align-items-center gap-4">
      <svg viewBox="0 0 140 140" width="150" height="150" role="img" aria-label={label}>
        <circle cx="70" cy="70" r={R} fill="none" stroke="#eef2f7" strokeWidth="18" />
        {total > 0 && parts.map((p, i) => {
          const len = (p.value / total) * C;
          const el = (
            <circle key={p.label} cx="70" cy="70" r={R} fill="none" stroke={PALETTE[i % PALETTE.length]} strokeWidth="18"
              strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-offset} transform="rotate(-90 70 70)">
              <title>{`${p.label}: ${p.value}`}</title>
            </circle>
          );
          offset += len;
          return el;
        })}
        <text x="70" y="68" textAnchor="middle" fontSize="22" fontWeight="800" fill="#101b35">{total}</text>
        <text x="70" y="86" textAnchor="middle" fontSize="10" fill="#64748b">{centre || "total"}</text>
      </svg>
      <ul className="list-unstyled small mb-0 flex-grow-1" style={{ minWidth: 160 }}>
        {parts.map((p, i) => (
          <li key={p.label} className="d-flex align-items-center gap-2 py-1">
            <span style={{ width: 10, height: 10, borderRadius: 3, background: PALETTE[i % PALETTE.length], flex: "none" }} />
            <span className="flex-grow-1">{p.label}</span><strong>{p.value}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}
