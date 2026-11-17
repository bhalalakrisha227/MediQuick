import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import Field from "../components/Field";

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ full_name: "", email: "", phone: "", password: "" });
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const change = (e) => setForm({ ...form, [e.target.name]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    setMessage("");
    try {
      await register(form);
      navigate("/account", { replace: true });
    } catch (err) {
      const { message, fields } = apiError(err);
      setErrors(fields);
      setMessage(Object.keys(fields).length ? "" : message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="container py-5" style={{ maxWidth: 420 }}>
      <h1 className="h4 mb-3">Create your account</h1>
      {message && <div className="alert alert-danger">{message}</div>}
      <form onSubmit={submit}>
        <Field label="Full name" name="full_name" value={form.full_name} onChange={change} error={errors.full_name} autoComplete="name" required />
        <Field label="Email" name="email" type="email" value={form.email} onChange={change} error={errors.email} autoComplete="email" required />
        <Field label="Phone (optional)" name="phone" value={form.phone} onChange={change} error={errors.phone} autoComplete="tel" />
        <Field label="Password (at least 10 characters)" name="password" type="password" value={form.password} onChange={change} error={errors.password} autoComplete="new-password" required />
        <button className="btn btn-primary w-100" disabled={busy}>{busy ? "Creating..." : "Sign up"}</button>
      </form>
      <p className="mt-3 small">Already registered? <Link to="/login">Log in</Link></p>
    </main>
  );
}
