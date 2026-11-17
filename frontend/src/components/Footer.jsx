import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isStaff, workspaceLinks } from "../utils/roles";
import Brand from "./ui/Brand";

export default function Footer() {
  const { user } = useAuth();
  const staff = isStaff(user);
  const work = staff ? workspaceLinks(user.role) : [];
  return (
    <footer className="mq-footer">
      <div className="container pt-5 pb-4">
        <div className="row g-4">
          <div className="col-lg-5">
            <Brand />
            <p className="mt-3 mb-0 small" style={{ maxWidth: 360 }}>
              An online pharmacy for medicines in India. Prescription medicines are sold only
              after a pharmacist has reviewed your prescription.
            </p>
          </div>
          {staff ? (
            <div className="col-6 col-lg-4 offset-lg-1">
              <h4>Your workspace</h4>
              <ul>
                {work.map((w) => <li key={w.to}><Link to={w.to}>{w.label}</Link></li>)}
                <li><Link to="/notifications">Alerts</Link></li>
              </ul>
            </div>
          ) : (
            <>
              <div className="col-6 col-lg-2 offset-lg-1">
                <h4>Shop</h4>
                <ul>
                  <li><Link to="/shop">All medicines</Link></li>
                  <li><Link to="/shop?rx=otc">No prescription needed</Link></li>
                  <li><Link to="/shop?rx=prescription">Prescription medicines</Link></li>
                </ul>
              </div>
              <div className="col-6 col-lg-2">
                <h4>Account</h4>
                <ul>
                  <li><Link to="/orders">Orders</Link></li>
                  <li><Link to="/prescriptions">Prescriptions</Link></li>
                  <li><Link to="/notifications">Alerts</Link></li>
                </ul>
              </div>
            </>
          )}
          <div className="col-12 col-lg-2">
            <h4>Platform</h4>
            <ul>
              <li><Link to="/status">System status</Link></li>
            </ul>
          </div>
        </div>
        <div className="mq-footer__bottom mt-4 pt-3 d-flex flex-column flex-md-row justify-content-between gap-2">
          <span>&copy; {new Date().getFullYear()} MediQuick. Development build; catalogue entries marked "Demo data" are samples.</span>
          <span>Medicines information on this site is not medical advice.</span>
        </div>
      </div>
    </footer>
  );
}
