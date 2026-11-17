import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { apiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import Field from "../components/Field";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const change = (e) => setForm({ ...form, [e.target.name]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(form.email, form.password);
      navigate(location.state?.from || "/account", { replace: true });
    } catch (err) {
      setError(apiError(err).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container py-5" style={{ maxWidth: 420 }}>
      <h1 className="h4 mb-3">Log in</h1>
      {error && <div className="alert alert-danger">{error}</div>}
      <form onSubmit={submit}>
        <Field label="Email" name="email" type="email" value={form.email} onChange={change} autoComplete="email" required />
        <Field label="Password" name="password" type="password" value={form.password} onChange={change} autoComplete="current-password" required />
        <button className="btn btn-primary w-100" disabled={busy}>{busy ? "Logging in..." : "Log in"}</button>
      </form>
      <p className="mt-3 small">No account? <Link to="/register">Sign up</Link></p>
    </main>
  );
}
