import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";

// Hides pages from logged-out users. This is a convenience only: the backend
// enforces every permission itself.
export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <p className="container py-5">Loading...</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}
