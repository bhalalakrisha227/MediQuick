// Small inline SVG icon set (no icon library needed). All icons are 24x24, stroke based.
const PATHS = {
  home: "M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10",
  bag: "M6 7h12l1 13H5L6 7zM9 7a3 3 0 016 0",
  bell: "M6 9a6 6 0 1112 0c0 6 2 7 2 7H4s2-1 2-7M10 20a2 2 0 004 0",
  cart: "M3 4h2l2.4 10.2a1 1 0 001 .8h8.7a1 1 0 001-.8L20 8H6M9 20h.01M17 20h.01",
  user: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0",
  menu: "M4 7h16M4 12h16M4 17h16",
  close: "M6 6l12 12M18 6L6 18",
  chevron: "M6 9l6 6 6-6",
  upload: "M12 16V4M7 9l5-5 5 5M5 20h14",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3zM8.5 12l2.5 2.5L16 9.5",
  lock: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 017 0v3",
  truck: "M2 6h11v10H2zM13 10h4l3 3v3h-7M7 19a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM17 19a1.5 1.5 0 100-3 1.5 1.5 0 000 3z",
  pill: "M10.5 3.5a4.2 4.2 0 016 6l-7 7a4.2 4.2 0 01-6-6l7-7zM8 8l6 6",
  search: "M11 18a7 7 0 100-14 7 7 0 000 14zM21 21l-5-5",
  logout: "M9 4H5v16h4M16 8l4 4-4 4M20 12H9",
  clipboard: "M9 4h6v3H9zM7 5H5v16h14V5h-2M9 12h6M9 16h4",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  check: "M5 12l5 5 9-10",
  filter: "M4 5h16l-6 7v6l-4 2v-8L4 5z",
  box: "M3 7l9-4 9 4v10l-9 4-9-4V7zM3 7l9 4 9-4M12 11v10",
  chart: "M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-3",
  users: "M9 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM2 20a7 7 0 0114 0M17 11a3 3 0 100-6M18 14a6 6 0 013 6",
  heart: "M12 20s-8-5-8-11a4.5 4.5 0 018-2.5A4.5 4.5 0 0120 9c0 6-8 11-8 11z",
  info: "M12 8h.01M11 12h1v5h1M12 21a9 9 0 100-18 9 9 0 000 18z",
  arrow: "M5 12h14M13 6l6 6-6 6",
};

export default function Icon({ name, size = 20, className = "", strokeWidth = 1.8 }) {
  const d = PATHS[name];
  if (!d) return null;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true" focusable="false">
      <path d={d} />
    </svg>
  );
}
