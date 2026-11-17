import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useCart } from "../cart/CartContext";
import Icon from "../components/ui/Icon";
import OrderTracker from "../components/ui/OrderTracker";
import StatusPill from "../components/ui/StatusPill";
import { formatPaise } from "../utils/money";
import { STATUS_LABELS } from "./OrderPage";
import { RX_STATUS } from "./prescriptionStatus";

const DONE_ORDER = ["delivered", "cancelled", "expired"];
const WAITING_RX = ["processing", "needs_customer_review", "submitted", "in_review", "clarification_requested"];

// Each section loads on its own, so one failing API does not blank the whole dashboard.
function useSection(path, pick) {
  const [state, setState] = useState({ loading: true, error: false, data: null });
  useEffect(() => {
    let alive = true;
    api.get(path)
      .then((r) => alive && setState({ loading: false, error: false, data: pick(r.data) }))
      .catch(() => alive && setState({ loading: false, error: true, data: null }));
    return () => { alive = false; };
  }, [path]); // eslint-disable-line react-hooks/exhaustive-deps
  return state;
}

function Stat({ to, icon, value, label }) {
  return (
    <Link to={to} className="card mq-stat mq-card-hover">
      <span className="mq-stat__icon"><Icon name={icon} size={22} /></span>
      <span><span className="mq-stat__value d-block">{value}</span><span className="mq-stat__label">{label}</span></span>
    </Link>
  );
}

function Body({ s, empty, children }) {
  if (s.loading) return <div className="mq-skeleton" style={{ height: 90 }} aria-busy="true" />;
  if (s.error) return <p className="small text-danger mb-0">Could not load this section. Reload the page to try again.</p>;
  if (!s.data || s.data.length === 0) return <p className="small text-muted mb-0">{empty}</p>;
  return children;
}

export default function CustomerDashboardPage() {
  const { user } = useAuth();
  const { cart } = useCart();
  const orders = useSection("/orders/", (d) => d.results);
  const rx = useSection("/prescriptions/", (d) => d.results);
  const addresses = useSection("/me/addresses/", (d) => d.results);

  const activeOrders = orders.data?.filter((o) => !DONE_ORDER.includes(o.status)) || [];
  const waitingRx = rx.data?.filter((r) => WAITING_RX.includes(r.status)) || [];
  const cartCount = cart?.item_count || 0;

  return (
    <main className="container py-4">
      <div className="mb-4">
        <h1 className="h3 mb-1">Hello, {user.full_name}</h1>
        <p className="text-muted mb-0">Your orders, prescriptions and account in one place.</p>
      </div>

      <div className="row g-3 mb-4">
        <div className="col-6 col-lg-3"><Stat to="/orders" icon="box" value={orders.data ? activeOrders.length : "–"} label="Active orders" /></div>
        <div className="col-6 col-lg-3"><Stat to="/prescriptions" icon="clipboard" value={rx.data ? waitingRx.length : "–"} label="Prescriptions in progress" /></div>
        <div className="col-6 col-lg-3"><Stat to="/cart" icon="cart" value={cart ? cartCount : "–"} label="Items in cart" /></div>
        <div className="col-6 col-lg-3"><Stat to="/account" icon="user" value={addresses.data ? addresses.data.length : "–"} label="Saved addresses" /></div>
      </div>

      <div className="row g-4">
        <div className="col-lg-7">
          <div className="card mq-section-card">
            <div className="mq-section-card__head">
              <h2>Order tracking</h2>
              <Link to="/orders" className="small fw-semibold">All orders</Link>
            </div>
            <Body s={orders} empty="No orders yet. Your latest orders and their progress will appear here.">
              {orders.data?.slice(0, 3).map((o) => {
                const [color, label] = STATUS_LABELS[o.status] || ["secondary", o.status];
                return (
                  <div key={o.id} className="mq-row d-block">
                    <div className="d-flex justify-content-between align-items-center mb-3">
                      <Link to={`/orders/${o.id}`} className="mq-row__title text-decoration-none">{o.order_number}</Link>
                      <span className="d-flex align-items-center gap-2"><strong>{formatPaise(o.total_paise)}</strong><StatusPill color={color} label={label} /></span>
                    </div>
                    <OrderTracker status={o.status} />
                  </div>
                );
              })}
            </Body>
          </div>
        </div>

        <div className="col-lg-5">
          <div className="card mq-section-card">
            <div className="mq-section-card__head">
              <h2>Prescriptions</h2>
              <Link to="/prescriptions/new" className="small fw-semibold">Upload new</Link>
            </div>
            <Body s={rx} empty="No prescriptions yet. Upload one to order prescription medicines.">
              {rx.data?.slice(0, 4).map((r) => {
                const [color, label] = RX_STATUS[r.status] || ["secondary", r.status];
                return (
                  <Link key={r.id} to={`/prescriptions/${r.id}`} className="mq-row">
                    <span className="mq-row__title text-truncate">{r.original_name}</span>
                    <StatusPill color={color} label={label} />
                  </Link>
                );
              })}
            </Body>
          </div>
        </div>

        <div className="col-lg-7">
          <div className="card mq-section-card">
            <div className="mq-section-card__head">
              <h2>Cart</h2>
              <Link to="/cart" className="small fw-semibold">Open cart</Link>
            </div>
            {!cart ? <div className="mq-skeleton" style={{ height: 60 }} /> : cartCount === 0 ? (
              <p className="small text-muted mb-0">Your cart is empty. <Link to="/shop">Browse medicines</Link></p>
            ) : (
              <div className="d-flex justify-content-between align-items-center">
                <span>{cartCount} item{cartCount === 1 ? "" : "s"} · <strong>{formatPaise(cart.total_paise)}</strong></span>
                <Link to="/checkout" className="btn btn-teal btn-sm">Checkout</Link>
              </div>
            )}
          </div>
        </div>

        <div className="col-lg-5">
          <div className="card mq-section-card">
            <div className="mq-section-card__head">
              <h2>Account & addresses</h2>
              <Link to="/account" className="small fw-semibold">Manage</Link>
            </div>
            <Body s={addresses} empty="No saved addresses yet. Add one in your account to check out faster.">
              {addresses.data?.slice(0, 2).map((a) => (
                <div key={a.id} className="mq-row">
                  <span className="small">{[a.line1, a.city, a.pincode].filter(Boolean).join(", ")}</span>
                  {a.is_default && <span className="mq-pill mq-pill--ok">Default</span>}
                </div>
              ))}
            </Body>
          </div>
        </div>
      </div>
    </main>
  );
}
