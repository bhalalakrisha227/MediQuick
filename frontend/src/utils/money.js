// Prices are stored and transferred as integer paise to avoid floating point errors.
export function formatPaise(paise) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(paise / 100);
}

export function rupeesToPaise(text) {
  const value = Number.parseFloat(text);
  return Number.isFinite(value) && value >= 0 ? Math.round(value * 100) : null;
}
