
import { useCallback, useEffect, useState } from "react";
import api, { apiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import Field from "../components/Field";

const EMPTY_ADDRESS = {
  label: "Home",
  recipient_name: "",
  phone: "",
  line1: "",
  line2: "",
  city: "",
  state: "",
  pincode: "",
};

function ProfileForm() {
  const { user, setUser } = useAuth();

  const [form, setForm] = useState({
    full_name: user.full_name,
    phone: user.phone || "",
  });

  const [errors, setErrors] = useState({});
  const [status, setStatus] = useState("");

  async function submit(e) {
    e.preventDefault();
    setErrors({});
    setStatus("");

    try {
      const res = await api.patch("/me/", form);
      setUser(res.data);
      setStatus("Saved.");
    } catch (err) {
      const { message, fields } = apiError(err);
      setErrors(fields);
      setStatus(Object.keys(fields).length ? "" : message);
    }
  }

  return (
    <form onSubmit={submit} className="card card-body mb-4">
      <h2 className="h6">Profile</h2>

      <p className="small text-muted mb-2">
        {user.email} ({user.role})
      </p>

      <Field
        label="Full name"
        name="full_name"
        value={form.full_name}
        onChange={(e) =>
          setForm({ ...form, full_name: e.target.value })
        }
        error={errors.full_name}
      />

      <Field
        label="Phone"
        name="phone"
        value={form.phone}
        onChange={(e) =>
          setForm({ ...form, phone: e.target.value })
        }
        error={errors.phone}
      />

      <div>
        <button className="btn btn-primary btn-sm">
          Save profile
        </button>

        <span className="small ms-2">{status}</span>
      </div>
    </form>
  );
}

function Addresses() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState(EMPTY_ADDRESS);
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState("");
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(() => {
    api
      .get("/me/addresses/")
      .then((res) => setItems(res.data.results))
      .catch((err) => setMessage(apiError(err).message));
  }, []);

  useEffect(load, [load]);

  const change = (e) =>
    setForm({
      ...form,
      [e.target.name]: e.target.value,
    });

  async function add(e) {
    e.preventDefault();
    setErrors({});
    setMessage("");

    try {
      await api.post("/me/addresses/", form);

      setForm(EMPTY_ADDRESS);
      setShowForm(false);
      setMessage("Address saved successfully.");

      load();
    } catch (err) {
      const { message, fields } = apiError(err);
      setErrors(fields);
      setMessage(Object.keys(fields).length ? "" : message);
    }
  }

  async function act(fn) {
    setMessage("");

    try {
      await fn();
      load();
    } catch (err) {
      setMessage(apiError(err).message);
    }
  }

  return (
    <section>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h2 className="h6 mb-0">Delivery addresses</h2>

        <button
          type="button"
          className="btn btn-outline-primary btn-sm"
          onClick={() => setShowForm((prev) => !prev)}
        >
          {showForm ? "Close" : "Edit"}
        </button>
      </div>

      {message && (
        <div className="alert alert-info py-2">
          {message}
        </div>
      )}

      {items.length === 0 && (
        <p className="text-muted small">
          No saved addresses yet.
        </p>
      )}

      <ul className="list-group mb-3">
        {items.map((a) => (
          <li
            key={a.id}
            className="list-group-item d-flex justify-content-between align-items-start"
          >
            <div className="small">
              <strong>{a.label}</strong>{" "}

              {a.is_default && (
                <span className="badge text-bg-success">
                  Default
                </span>
              )}

              <br />

              {a.recipient_name}, {a.phone}
              <br />

              {a.line1}
              {a.line2 ? `, ${a.line2}` : ""}, {a.city},{" "}
              {a.state} {a.pincode}
            </div>

            <div className="btn-group-vertical btn-group-sm">
              {!a.is_default && (
                <button
                  type="button"
                  className="btn btn-outline-secondary"
                  onClick={() =>
                    act(() =>
                      api.patch(`/me/addresses/${a.id}/`, {
                        is_default: true,
                      })
                    )
                  }
                >
                  Make default
                </button>
              )}

              <button
                type="button"
                className="btn btn-outline-danger"
                onClick={() =>
                  act(() =>
                    api.delete(`/me/addresses/${a.id}/`)
                  )
                }
              >
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>

      {showForm && (
        <form onSubmit={add} className="card card-body">
          <h3 className="h6">Add an address</h3>

          <Field
            label="Label"
            name="label"
            value={form.label}
            onChange={change}
            error={errors.label}
          />

          <Field
            label="Recipient name"
            name="recipient_name"
            value={form.recipient_name}
            onChange={change}
            error={errors.recipient_name}
          />

          <Field
            label="Phone"
            name="phone"
            value={form.phone}
            onChange={change}
            error={errors.phone}
          />

          <Field
            label="Address line 1"
            name="line1"
            value={form.line1}
            onChange={change}
            error={errors.line1}
          />

          <Field
            label="Address line 2 (optional)"
            name="line2"
            value={form.line2}
            onChange={change}
            error={errors.line2}
          />

          <Field
            label="City"
            name="city"
            value={form.city}
            onChange={change}
            error={errors.city}
          />

          <Field
            label="State"
            name="state"
            value={form.state}
            onChange={change}
            error={errors.state}
          />

          <Field
            label="PIN code"
            name="pincode"
            value={form.pincode}
            onChange={change}
            error={errors.pincode}
          />

          <div>
            <button className="btn btn-primary btn-sm">
              Save address
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

export default function AccountPage() {
  const { user } = useAuth();

  return (
    <main
      className="container py-4"
      style={{ maxWidth: 640 }}
    >
      <h1 className="h4 mb-3">My account</h1>

      <ProfileForm />

      {user?.role === "customer" && <Addresses />}
    </main>
  );
}
