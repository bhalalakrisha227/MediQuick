import { useId, useState } from "react";

// Every product gets its own picture:
//  1. If the API ever supplies product.image_url, that photo is shown.
//  2. If there is none, or it fails to load, a pack illustration is drawn from the product itself:
//     the pack shape comes from the product type (strip, bottle, sachet, tube, ...), the colour from its
//     category and name, and the pack label from its name and strength. So two products never look the same.
//  3. If even that cannot be drawn, a neutral placeholder is shown.
// These are illustrations, not photographs of real packaging.

const CATEGORY_HUES = [
  ["pain", 172], ["fever", 172], ["cold", 200], ["allergy", 200], ["digest", 38], ["vitamin", 28],
  ["supplement", 28], ["first-aid", 350], ["aid", 350], ["device", 350], ["infection", 265], ["chronic", 222],
];

function hash(text) {
  let h = 0;
  for (let i = 0; i < text.length; i += 1) h = (h * 31 + text.charCodeAt(i)) >>> 0;
  return h;
}

export function packKind(p) {
  const name = `${p.name || ""}`.toLowerCase();
  const pack = `${p.pack_size || ""}`.toLowerCase();
  const all = `${name} ${pack} ${p.generic_name || ""}`.toLowerCase();
  if (/thermometer|monitor|glucometer|device|nebuli[sz]er|oximeter/.test(all)) return "device";
  if (/sachet|\bors\b|rehydration/.test(all)) return "sachet";
  if (/lozenge|pastille/.test(all)) return "lozenge";
  if (/cream|ointment|\bgel\b.*tube|tube/.test(all) && !/oral gel/.test(all)) return "tube";
  if (/drops/.test(name) && !/ml bottle/.test(pack)) return "dropper";
  if (/injection|vial|insulin/.test(all)) return "vial";
  if (/tablet|capsule/.test(name) && /bottle|jar/.test(pack)) return "jar";
  if (/capsule/.test(name)) return "capsules";
  if (/tablet/.test(name)) return "tablets";
  if (/syrup|suspension|liquid|solution|lotion|oral gel|\bgel\b|antiseptic|bottle|ml/.test(all)) return "bottle";
  return "box";
}

function palette(p) {
  const key = `${p.category || ""}`.toLowerCase();
  const base = (CATEGORY_HUES.find(([k]) => key.includes(k)) || [null, 175])[1];
  const hue = (base + (hash(p.name || "") % 25) - 12 + 360) % 360;
  return {
    main: `hsl(${hue} 55% 38%)`, dark: `hsl(${hue} 60% 22%)`, light: `hsl(${hue} 60% 92%)`, mid: `hsl(${hue} 55% 70%)`,
  };
}

function labelParts(p) {
  const strength = (p.name || "").match(/\d+(?:\.\d+)?\s?(?:mg|mcg|g|ml|iu)\b/i)?.[0] || "";
  const words = (p.name || "").replace(/\d+(?:\.\d+)?\s?(?:mg|mcg|g|ml|iu)\b/gi, "").split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const w of words) {
    if ((`${line} ${w}`).trim().length > 13 && line) { lines.push(line); line = w; } else { line = (`${line} ${w}`).trim(); }
    if (lines.length === 2) break;
  }
  if (line && lines.length < 3) lines.push(line);
  return { lines: lines.slice(0, 3).map((l) => (l.length > 15 ? `${l.slice(0, 14)}.` : l)), strength };
}

function Label({ x, y, w, c, p }) {
  const { lines, strength } = labelParts(p);
  return (
    <g>
      {lines.map((l, i) => <text key={l + i} x={x + w / 2} y={y + i * 11} textAnchor="middle" fontSize="9.5" fontWeight="700" fill={c.dark} fontFamily="Inter, Arial, sans-serif">{l}</text>)}
      {strength && <text x={x + w / 2} y={y + lines.length * 11 + 3} textAnchor="middle" fontSize="8.5" fontWeight="600" fill={c.main} fontFamily="Inter, Arial, sans-serif">{strength}</text>}
    </g>
  );
}

function Art({ kind, c, p, uid }) {
  const g = `g${uid}`;
  const defs = (
    <defs>
      <linearGradient id={g} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor={c.mid} /><stop offset="1" stopColor={c.main} /></linearGradient>
    </defs>
  );
  const shadow = <ellipse cx="100" cy="132" rx="62" ry="6" fill="#101b35" opacity="0.10" />;
  switch (kind) {
    case "tablets":
    case "capsules": {
      const cells = [0, 1, 2, 3, 4].map((i) => 34 + i * 33);
      return (
        <>{defs}{shadow}
          <rect x="22" y="22" width="156" height="104" rx="10" fill="#fff" stroke={c.mid} strokeWidth="2" />
          <rect x="22" y="22" width="156" height="30" rx="10" fill={`url(#${g})`} />
          <rect x="22" y="40" width="156" height="12" fill={`url(#${g})`} />
          <text x="100" y="42" textAnchor="middle" fontSize="11" fontWeight="800" fill="#fff" fontFamily="Inter, Arial, sans-serif">{kind === "tablets" ? "TABLETS" : "CAPSULES"}</text>
          {cells.map((x) => (kind === "tablets"
            ? <circle key={x} cx={x + 7} cy="66" r="8" fill={c.light} stroke={c.mid} strokeWidth="1.5" />
            : <rect key={x} x={x - 2} y="60" width="18" height="12" rx="6" fill={c.light} stroke={c.mid} strokeWidth="1.5" />))}
          <Label x={22} y={92} w={156} c={c} p={p} />
        </>
      );
    }
    case "jar":
      return (
        <>{defs}{shadow}
          <rect x="66" y="18" width="68" height="18" rx="5" fill={c.dark} />
          <rect x="58" y="34" width="84" height="94" rx="14" fill="#fff" stroke={c.mid} strokeWidth="2" />
          <rect x="58" y="52" width="84" height="56" fill={`url(#${g})`} opacity="0.18" />
          <Label x={58} y={68} w={84} c={c} p={p} />
          <circle cx="82" cy="118" r="4" fill={c.mid} /><circle cx="100" cy="120" r="4" fill={c.mid} /><circle cx="118" cy="118" r="4" fill={c.mid} />
        </>
      );
    case "bottle":
      return (
        <>{defs}{shadow}
          <rect x="84" y="14" width="32" height="18" rx="4" fill={c.dark} />
          <rect x="88" y="30" width="24" height="12" fill={c.mid} />
          <path d="M70 46 Q70 40 82 40 H118 Q130 40 130 46 V122 Q130 130 122 130 H78 Q70 130 70 122 Z" fill={`url(#${g})`} />
          <rect x="70" y="62" width="60" height="50" fill="#fff" />
          <Label x={70} y={76} w={60} c={c} p={p} />
        </>
      );
    case "sachet":
      return (
        <>{defs}{shadow}
          <g transform="rotate(-8 100 74)">
            <rect x="52" y="20" width="96" height="104" rx="6" fill={`url(#${g})`} />
            <path d="M52 20h96v8H52zM52 116h96v8H52z" fill={c.dark} opacity="0.35" />
            <rect x="62" y="44" width="76" height="56" rx="6" fill="#fff" />
            <Label x={62} y={58} w={76} c={c} p={p} />
          </g>
        </>
      );
    case "lozenge":
      return (
        <>{defs}{shadow}
          <rect x="40" y="38" width="120" height="78" rx="12" fill={`url(#${g})`} />
          <rect x="40" y="38" width="120" height="14" fill={c.dark} opacity="0.35" />
          <rect x="52" y="60" width="96" height="48" rx="8" fill="#fff" />
          <Label x={52} y={74} w={96} c={c} p={p} />
          {[0, 1, 2].map((i) => <circle key={i} cx={78 + i * 22} cy="30" r="9" fill={c.light} stroke={c.mid} strokeWidth="2" />)}
        </>
      );
    case "tube":
      return (
        <>{defs}{shadow}
          <path d="M44 56 H156 L148 112 H52 Z" fill={`url(#${g})`} />
          <rect x="52" y="104" width="96" height="14" rx="3" fill={c.dark} />
          <rect x="156" y="62" width="22" height="38" rx="4" fill={c.dark} />
          <rect x="62" y="64" width="76" height="34" rx="5" fill="#fff" />
          <Label x={62} y={76} w={76} c={c} p={p} />
        </>
      );
    case "dropper":
      return (
        <>{defs}{shadow}
          <rect x="88" y="10" width="24" height="34" rx="10" fill={c.dark} />
          <rect x="92" y="40" width="16" height="12" fill={c.mid} />
          <path d="M74 60 Q74 52 86 52 H114 Q126 52 126 60 V120 Q126 130 116 130 H84 Q74 130 74 120 Z" fill={`url(#${g})`} />
          <rect x="74" y="70" width="52" height="44" fill="#fff" />
          <Label x={74} y={82} w={52} c={c} p={p} />
        </>
      );
    case "vial":
      return (
        <>{defs}{shadow}
          <rect x="80" y="14" width="40" height="16" rx="4" fill={c.dark} />
          <rect x="84" y="28" width="32" height="12" fill={c.mid} />
          <path d="M78 42 H122 V122 Q122 130 114 130 H86 Q78 130 78 122 Z" fill={c.light} stroke={c.mid} strokeWidth="2" />
          <rect x="78" y="62" width="44" height="46" fill="#fff" /><rect x="78" y="100" width="44" height="22" fill={`url(#${g})`} opacity="0.5" />
          <Label x={78} y={74} w={44} c={c} p={p} />
        </>
      );
    case "device":
      return (
        <>{defs}{shadow}
          <g transform="rotate(-18 100 74)">
            <rect x="30" y="58" width="130" height="32" rx="16" fill={`url(#${g})`} />
            <rect x="46" y="66" width="38" height="16" rx="3" fill="#fff" />
            <text x="65" y="78" textAnchor="middle" fontSize="10" fontWeight="800" fill={c.dark} fontFamily="Inter, Arial, sans-serif">36.5</text>
            <circle cx="108" cy="74" r="6" fill={c.dark} />
            <path d="M160 74 L178 74" stroke={c.dark} strokeWidth="5" strokeLinecap="round" />
          </g>
        </>
      );
    default:
      return (
        <>{defs}{shadow}
          <rect x="50" y="26" width="100" height="100" rx="8" fill={`url(#${g})`} />
          <rect x="58" y="48" width="84" height="62" rx="6" fill="#fff" />
          <path d="M92 34h16M100 26v16" stroke="#fff" strokeWidth="5" strokeLinecap="round" />
          <Label x={58} y={64} w={84} c={c} p={p} />
        </>
      );
  }
}

export default function ProductImage({ product, ratio = "card" }) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const [photoFailed, setPhotoFailed] = useState(false);
  const url = typeof product.image_url === "string" && product.image_url.startsWith("https://") ? product.image_url : "";
  const c = palette(product);
  const kind = packKind(product);

  return (
    <div className={`mq-img mq-img--${ratio}`} style={{ background: `linear-gradient(135deg, ${c.light}, #fff)` }}>
      {url && !photoFailed ? (
        <img src={url} alt={product.name} loading="lazy" onError={() => setPhotoFailed(true)} className="mq-img__photo" />
      ) : (
        <svg viewBox="0 0 200 150" role="img" aria-label={`${product.name} pack illustration`} className="mq-img__art">
          <Art kind={kind} c={c} p={product} uid={uid} />
        </svg>
      )}
    </div>
  );
}
