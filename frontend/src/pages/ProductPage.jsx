import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import api, { apiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useCart } from "../cart/CartContext";
import ProductImage from "../components/ProductImage";
import { canShop } from "../utils/roles";
import StockBadge from "../components/StockBadge";
import { formatPaise } from "../utils/money";

export default function ProductPage() {
  const { slug } = useParams();
  const { user } = useAuth();
  const { add } = useCart();
  const navigate = useNavigate();
  const location = useLocation();
  const [product, setProduct] = useState(null);
  const [state, setState] = useState("loading");
  const [qty, setQty] = useState(1);
  const [cartMsg, setCartMsg] = useState({ type: "", text: "" });
  const [rxLeft, setRxLeft] = useState(0);   // units a single approved prescription still covers (0 = none)

  async function addToCart() {
    if (!user) { navigate("/login", { state: { from: location.pathname } }); return; }
    setCartMsg({ type: "", text: "" });
    try {
      await add(product.id, qty);
      setCartMsg({ type: "success", text: "Added to your cart." });
    } catch (err) {
      setCartMsg({ type: "danger", text: apiError(err).message });
    }
  }

  useEffect(() => {
    if (!user || !product?.requires_prescription) { setRxLeft(0); return undefined; }
    let stale = false;
    api.get("/prescriptions/allowances/").then((res) => {
      if (stale) return;
      const left = res.data.results.flatMap((r) => r.items).filter((i) => i.product_id === product.id).map((i) => i.remaining);
      setRxLeft(left.length ? Math.max(...left) : 0);
    }).catch(() => !stale && setRxLeft(0));
    return () => { stale = true; };
  }, [user, product]);

  useEffect(() => {
    let stale = false;
    setState("loading");
    api.get(`/products/${encodeURIComponent(slug)}/`)
      .then((res) => { if (!stale) { setProduct(res.data); setState("ok"); } })
      .catch((err) => { if (!stale) setState(err.response?.status === 404 ? "missing" : "error"); });
    return () => { stale = true; };
  }, [slug]);

  if (state === "loading") return <main className="container py-4">Loading...</main>;
  if (state === "missing") return <main className="container py-4"><p>This product was not found.</p><Link to="/shop">Back to shop</Link></main>;
  if (state === "error") return <main className="container py-4"><div className="alert alert-danger">Could not load this product.</div></main>;

  const p = product;
  return (
    <main className="container py-4" style={{ maxWidth: 760 }}>
      <Link to="/shop" className="small">&larr; Back to shop</Link>
      <div className="d-flex gap-1 flex-wrap my-2">
        {p.requires_prescription
          ? <span className="mq-pill mq-pill--rx">Prescription required</span>
          : <span className="mq-pill mq-pill--ok">No prescription needed</span>}
        {p.is_demo && <span className="mq-pill mq-pill--demo">Demo data: fictional details</span>}
      </div>
      <div className="row g-4 align-items-start mb-2">
        <div className="col-md-5"><ProductImage product={p} ratio="square" /></div>
        <div className="col-md-7">
      <h1 className="h4">{p.name}</h1>
      <p className="text-muted">{p.pack_size}{p.generic_name ? ` | ${p.generic_name}` : ""}</p>
      <p className="fs-5 mb-1">
        <strong>{formatPaise(p.price_paise)}</strong>{" "}
        {p.mrp_paise > p.price_paise && <><s className="small text-muted">{formatPaise(p.mrp_paise)}</s> <span className="small text-success">{p.discount_percent}% off</span></>}
      </p>
        </div>
      </div>

      {p.requires_prescription && (
        <div className="alert alert-warning">
          This medicine can only be supplied against a valid prescription that a pharmacist has approved.
          {rxLeft > 0
            ? <> Your approved prescription covers up to <strong>{rxLeft}</strong> unit(s) of it.</>
            : canShop(user) ? <> You can <Link to="/prescriptions/new">upload your prescription</Link> for a pharmacist to review.</> : null}
        </div>
      )}
      {!p.purchasable_online && (
        <div className="alert alert-danger">This product is not available for online ordering.</div>
      )}
      {p.availability && (
        <div className="alert alert-light border">
          <StockBadge availability={p.availability} />{" "}
          {p.availability.status === "out_of_stock"
            ? "Currently unavailable."
            : p.availability.earliest_expiry && (
                <span className="small">
                  Earliest expiry among available stock: {new Date(p.availability.earliest_expiry).toLocaleDateString("en-IN", { month: "short", year: "numeric", timeZone: "UTC" })}
                </span>
              )}
        </div>
      )}

      {(!user || user.role === "customer") && (!p.requires_prescription || rxLeft > 0) && p.purchasable_online && p.availability?.status !== "out_of_stock" && (
        <div className="mb-3">
          <div className="d-flex gap-2 align-items-center">
            <select className="form-select w-auto" aria-label="Quantity" value={qty} onChange={(e) => setQty(Number(e.target.value))}>
              {Array.from({ length: p.requires_prescription ? Math.min(10, rxLeft) : 10 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            <button className="btn btn-primary" onClick={addToCart}>{user ? "Add to cart" : "Log in to add to cart"}</button>
            {cartMsg.type === "success" && <Link to="/cart">View cart</Link>}
          </div>
          {cartMsg.text && <div className={`small mt-2 text-${cartMsg.type}`}>{cartMsg.text}</div>}
        </div>
      )}

      {p.description && <><h2 className="h6">About</h2><p>{p.description}</p></>}
      <dl className="row small">
        {p.manufacturer && <><dt className="col-4">Manufacturer</dt><dd className="col-8">{p.manufacturer}</dd></>}
        {p.storage_info && <><dt className="col-4">Storage</dt><dd className="col-8">{p.storage_info}</dd></>}
      </dl>
    </main>
  );
}
