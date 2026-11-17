import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";

// Convenience only: hides pages from the wrong roles. The backend enforces every permission itself.
export default function RoleRoute({ roles, children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <p className="container py-5">Loading...</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (!roles.includes(user.role)) {
    return <main className="container py-5"><div className="alert alert-warning">You do not have access to this page.</div></main>;
  }
  return children;
}
