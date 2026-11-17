export default function Field({ label, name, value, onChange, error, type = "text", autoComplete, required }) {
  return (
    <div className="mb-3">
      <label htmlFor={name} className="form-label">{label}</label>
      <input id={name} name={name} type={type} value={value} onChange={onChange}
        autoComplete={autoComplete} required={required}
        className={`form-control ${error ? "is-invalid" : ""}`} />
      {error && <div className="invalid-feedback">{error}</div>}
    </div>
  );
}
