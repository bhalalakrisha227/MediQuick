import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api, { apiError } from "../api/client";
import { useCart } from "../cart/CartContext";
import { formatPaise } from "../utils/money";

export default function CheckoutPage() {
  const { cart, refresh } = useCart();
  const navigate = useNavigate();
  const [addresses, setAddresses] = useState(null);
  const [addressId, setAddressId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get("/me/addresses/").then((res) => {
      setAddresses(res.data.results);
      const def = res.data.results.find((a) => a.is_default) || res.data.results[0];
      if (def) setAddressId(def.id);
    }).catch((err) => setError(apiError(err).message));
  }, []);

  async function place() {
    setBusy(true);
    setError("");
    try {
      const res = await api.post("/orders/", { address_id: addressId });
      await refresh();
      navigate(`/orders/${res.data.id}`, { replace: true });
    } catch (err) {
      const { message, fields } = apiError(err);
      setError(message + (Object.keys(fields).length ? " Please review your cart." : ""));
      refresh();
    } finally {
      setBusy(false);
    }
  }

  if (!cart || !addresses) return <main className="container py-4">{error || "Loading..."}</main>;
  if (cart.items.length === 0) return <main className="container py-4"><p>Your cart is empty. <Link to="/shop">Browse the shop</Link></p></main>;
  return (
    <main className="container py-4" style={{ maxWidth: 760 }}>
      <h1 className="h4 mb-3">Checkout</h1>
      {error && <div className="alert alert-danger">{error} <Link to="/cart">Go to cart</Link></div>}
      <h2 className="h6">Delivery address</h2>
      {addresses.length === 0 ? (
        <p>You have no saved addresses. <Link to="/account">Add one in your account</Link>, then come back.</p>
      ) : (
        <div className="mb-3">
          {addresses.map((a) => (
            <label key={a.id} className="list-group-item d-flex gap-2 border rounded p-2 mb-2">
              <input type="radio" name="address" checked={addressId === a.id} onChange={() => setAddressId(a.id)} />
              <span className="small"><strong>{a.label}</strong> {a.recipient_name}, {a.phone}<br />
                {a.line1}{a.line2 ? `, ${a.line2}` : ""}, {a.city}, {a.state} {a.pincode}</span>
            </label>
          ))}
          <p className="small text-muted">We check that we deliver to your PIN code when you place the order.</p>
        </div>
      )}
      <h2 className="h6">Order summary</h2>
      <ul className="list-group mb-3">
        {cart.items.map((l) => (
          <li key={l.product_id} className="list-group-item d-flex justify-content-between">
            <span>{l.name} x {l.quantity}</span><span>{formatPaise(l.line_total_paise)}</span>
          </li>
        ))}
        <li className="list-group-item d-flex justify-content-between fw-bold"><span>Total</span><span>{formatPaise(cart.total_paise)}</span></li>
      </ul>
      <p className="small text-muted">Placing the order holds your items for 15 minutes while you pay. Payment is a mock in this build.</p>
      <button className="btn btn-primary" disabled={busy || !addressId || !cart.can_checkout} onClick={place}>
        {busy ? "Placing order..." : "Place order"}
      </button>
      {!cart.can_checkout && <p className="small text-danger mt-2">Some items need attention. <Link to="/cart">Review your cart</Link></p>}
    </main>
  );
}
