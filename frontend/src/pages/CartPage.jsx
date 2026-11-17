import { useState } from "react";
import { Link } from "react-router-dom";
import { apiError } from "../api/client";
import { useCart } from "../cart/CartContext";
import { formatPaise } from "../utils/money";

const PROBLEMS = {
  unavailable: "No longer available. Remove it to continue.",
  prescription_required: "Needs a pharmacist-approved prescription that covers it. Upload one under Prescriptions, or remove this item.",
  exceeds_prescription: "Your approved prescription covers fewer units than this. Lower the quantity or remove it.",
  not_purchasable: "Not available for online ordering. Remove it to continue.",
};

export default function CartPage() {
  const { cart, setQuantity, remove } = useCart();
  const [error, setError] = useState("");

  async function run(fn) {
    setError("");
    try { await fn(); } catch (err) { setError(apiError(err).message); }
  }

  if (!cart) return <main className="container py-4">Loading...</main>;
  return (
    <main className="container py-4" style={{ maxWidth: 760 }}>
      <h1 className="h4 mb-3">Your cart</h1>
      {error && <div className="alert alert-danger">{error}</div>}
      {cart.items.length === 0 ? (
        <p className="text-muted">Your cart is empty. <Link to="/shop">Browse the shop</Link></p>
      ) : (
        <>
          <ul className="list-group mb-3">
            {cart.items.map((l) => (
              <li key={l.product_id} className="list-group-item">
                <div className="d-flex justify-content-between align-items-start gap-2">
                  <div>
                    {l.slug ? <Link to={`/product/${l.slug}`}>{l.name}</Link> : l.name}
                    <div className="small text-muted">{l.pack_size} | {formatPaise(l.unit_price_paise)} each</div>
                    {l.problem && (
                      <div className="small text-danger mt-1">
                        {l.problem === "insufficient_stock"
                          ? (l.available_units > 0 ? `Only ${l.available_units} available. Reduce the quantity to continue.` : "Out of stock. Remove it to continue.")
                          : PROBLEMS[l.problem]}
                      </div>
                    )}
                  </div>
                  <div className="text-end">
                    <div className="fw-bold">{formatPaise(l.line_total_paise)}</div>
                    <div className="d-flex gap-1 align-items-center justify-content-end mt-1">
                      {l.problem !== "unavailable" && (
                        <select className="form-select form-select-sm w-auto" aria-label={`Quantity for ${l.name}`} value={l.quantity}
                          onChange={(e) => run(() => setQuantity(l.product_id, Number(e.target.value)))}>
                          {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}
                        </select>
                      )}
                      <button className="btn btn-sm btn-outline-danger" onClick={() => run(() => remove(l.product_id))}>Remove</button>
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <div className="card card-body mb-3">
            <div className="d-flex justify-content-between"><span>Subtotal</span><span>{formatPaise(cart.subtotal_paise)}</span></div>
            <div className="d-flex justify-content-between"><span>Delivery</span><span>{cart.delivery_fee_paise ? formatPaise(cart.delivery_fee_paise) : "Free"}</span></div>
            <div className="d-flex justify-content-between fw-bold border-top mt-2 pt-2"><span>Total</span><span>{formatPaise(cart.total_paise)}</span></div>
          </div>
          {cart.can_checkout
            ? <Link to="/checkout" className="btn btn-primary">Continue to checkout</Link>
            : <button className="btn btn-primary" disabled>Fix the items above to continue</button>}
          <p className="small text-muted mt-2">Items are not reserved until you place the order.</p>
        </>
      )}
    </main>
  );
}
