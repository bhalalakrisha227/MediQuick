import { Link } from "react-router-dom";
import Icon from "./Icon";

export default function Brand({ to = "/" }) {
  return (
    <Link to={to} className="mq-brand" aria-label="MediQuick home">
      <span className="mq-brand__mark"><Icon name="pill" size={19} strokeWidth={2} /></span>
      <span>Medi<em>Quick</em></span>
    </Link>
  );
}
