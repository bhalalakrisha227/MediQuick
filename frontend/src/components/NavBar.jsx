import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useCart } from "../cart/CartContext";
import { canShop, isCustomer, isStaff, workspaceLinks } from "../utils/roles";
import NotificationBell from "./NotificationBell";
import Brand from "./ui/Brand";
import Icon from "./ui/Icon";
import NavButton from "./ui/NavButton";

const initials = (name = "") =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("") || "U";

export default function NavBar() {
  const { user, logout } = useAuth();
  const { cart } = useCart();
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);       // mobile menu
  const [menuOpen, setMenuOpen] = useState(false); // profile dropdown
  const profileRef = useRef(null);

  useEffect(() => { setOpen(false); setMenuOpen(false); }, [location.pathname]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const onDown = (e) => { if (profileRef.current && !profileRef.current.contains(e.target)) setMenuOpen(false); };
    const onKey = (e) => { if (e.key === "Escape") setMenuOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [menuOpen]);

  // Customers and visitors get the shopping navigation. Staff get their own work links instead
  // (these are rendered only for the right role, not just hidden with CSS).
  const customer = isCustomer(user);
  const staff = isStaff(user);
  const work = staff ? workspaceLinks(user.role) : [];

  async function doLogout() {
    setMenuOpen(false);
    await logout();
    navigate("/");
  }

  const linkClass = ({ isActive }) => `mq-navlink ${isActive ? "active" : ""}`;

  return (
    <header className="mq-header">
      <div className="container mq-header__inner position-relative">
        <Brand />
        <button type="button" className="mq-toggle" aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          <Icon name={open ? "close" : "menu"} size={22} />
        </button>

        <nav className={`mq-nav ${open ? "open" : ""}`} aria-label="Main">
          <div className="mq-nav__links">
            <NavLink to="/" end className={linkClass}>Home</NavLink>
            {customer && <NavLink to="/orders" className={linkClass}>Orders</NavLink>}
            {customer && <NavLink to="/prescriptions" className={linkClass}>Prescriptions</NavLink>}
            {work.map((w) => <NavLink key={w.to} to={w.to} className={linkClass}>{w.short}</NavLink>)}
          </div>

          <div className="mq-nav__actions">
            {canShop(user) && <NavButton to="/shop" icon="bag" label="Shop" />}
            {user ? (
              <>
                <NotificationBell />
                {customer && (
                  <NavButton to="/cart" icon="cart" label="Cart" count={cart?.item_count || 0}
                    ariaLabel={`Cart, ${cart?.item_count || 0} items`} />
                )}
                <div className="mq-profile" ref={profileRef}>
                  <button type="button" className="mq-profile__btn" aria-haspopup="menu" aria-expanded={menuOpen}
                    onClick={() => setMenuOpen((v) => !v)}>
                    <span className="mq-avatar">{initials(user.full_name)}</span>
                    <span className="mq-profile__name">{user.full_name}</span>
                    <Icon name="chevron" size={16} />
                  </button>
                  {(menuOpen || open) && (
                    <div className="mq-menu" role="menu">
                      <div className="mq-menu__head">
                        <strong>{user.full_name}</strong>
                        <span className="mq-menu__role">{String(user.role).replace(/_/g, " ")}</span>
                      </div>
                      {customer && <Link className="mq-menu__item" role="menuitem" to="/dashboard"><Icon name="grid" size={17} />My dashboard</Link>}
                      <Link className="mq-menu__item" role="menuitem" to="/account"><Icon name="user" size={17} />My account</Link>
                      <button type="button" className="mq-menu__item mq-menu__item--danger" role="menuitem" onClick={doLogout}>
                        <Icon name="logout" size={17} />Log out
                      </button>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <>
                <Link className="btn btn-outline-secondary" to="/login">Log in</Link>
                <Link className="btn btn-teal" to="/register">Sign up</Link>
              </>
            )}
          </div>
        </nav>
      </div>
    </header>
  );
}
