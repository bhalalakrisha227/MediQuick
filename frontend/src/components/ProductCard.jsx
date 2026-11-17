import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { apiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useCart } from "../cart/CartContext";
import { formatPaise } from "../utils/money";
import ProductImage from "./ProductImage";
import StockBadge from "./StockBadge";
import Icon from "./ui/Icon";

export default function ProductCard({ product: p }) {
  const { user } = useAuth();
  const { add } = useCart();
  const location = useLocation();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState({ type: "", text: "" });

  const isCustomer = user?.role === "customer";
  const outOfStock = p.availability?.status === "out_of_stock";

  async function addToCart() {
    setBusy(true);
    setMsg({ type: "", text: "" });
    try {
      await add(p.id, 1);
      setMsg({ type: "success", text: "Added to cart" });
      setTimeout(() => setMsg((m) => (m.type === "success" ? { type: "", text: "" } : m)), 2500);
    } catch (err) {
      setMsg({ type: "danger", text: apiError(err).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card mq-product mq-card-hover">
      <Link to={`/product/${p.slug}`} aria-label={p.name}><ProductImage product={p} /></Link>
      <div className="mq-product__body">
        <div className="d-flex gap-1 flex-wrap mb-2">
          {p.requires_prescription
            ? <span className="mq-pill mq-pill--rx">Prescription required</span>
            : <span className="mq-pill">No prescription</span>}
          {p.is_demo && <span className="mq-pill mq-pill--demo">Demo data</span>}
          <StockBadge availability={p.availability} />
        </div>
        <Link to={`/product/${p.slug}`} className="mq-product__name">{p.name}</Link>
        <p className="small text-muted mb-2">{p.pack_size}</p>
        <div className="mt-auto pt-2">
          <div className="mb-3">
            <span className="mq-price">{formatPaise(p.price_paise)}</span>{" "}
            {p.mrp_paise > p.price_paise && (
              <>
                <s className="small text-muted">{formatPaise(p.mrp_paise)}</s>{" "}
                <span className="small fw-semibold text-success">{p.discount_percent}% off</span>
              </>
            )}
          </div>
          {isCustomer ? (
            <button className="btn btn-primary btn-sm w-100" onClick={addToCart} disabled={busy || outOfStock}>
              <Icon name="cart" size={16} />{outOfStock ? "Out of stock" : busy ? "Adding..." : "Add to Cart"}
            </button>
          ) : user ? (
            <Link className="btn btn-outline-primary btn-sm w-100" to={`/product/${p.slug}`}>View details</Link>
          ) : (
            <Link className="btn btn-outline-primary btn-sm w-100" to="/login" state={{ from: location }}>Log in to add to cart</Link>
          )}
          {msg.text && <div className={`small mt-2 text-${msg.type}`} role="status">{msg.text}</div>}
        </div>
      </div>
    </div>
  );
}
