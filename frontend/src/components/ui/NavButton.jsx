import { NavLink } from "react-router-dom";
import Icon from "./Icon";

// The ONE button used for Shop, Alerts and Cart.
// Because they all render this component with the same class, their height, padding,
// radius, weight and hover effect are identical by construction.
export default function NavButton({ to, icon, label, count = 0, variant = "", ariaLabel, end = false }) {
  const shown = count > 99 ? "99+" : count;
  return (
    <NavLink
      to={to}
      end={end}
      aria-label={ariaLabel || label}
      className={({ isActive }) => `mq-navbtn ${variant ? `mq-navbtn--${variant}` : ""} ${isActive ? "active" : ""}`}
    >
      <Icon name={icon} size={18} />
      <span>{label}</span>
      {count > 0 && <span className="mq-navbtn__count">{shown}</span>}
    </NavLink>
  );
}
