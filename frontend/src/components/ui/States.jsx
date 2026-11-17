import Icon from "./Icon";

// Shared loading / empty / error states so every page looks the same.
export function EmptyState({ icon = "box", title, children, action }) {
  return (
    <div className="card mq-empty">
      <div className="mq-empty__icon"><Icon name={icon} size={28} /></div>
      <h2 className="h5">{title}</h2>
      {children && <p className="text-muted mb-3">{children}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="alert alert-danger d-flex justify-content-between align-items-center gap-3" role="alert">
      <span>{message}</span>
      {onRetry && <button className="btn btn-sm btn-outline-secondary" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function SkeletonGrid({ count = 8 }) {
  return (
    <div className="row g-3" aria-busy="true" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="col-6 col-md-4 col-xl-3"><div className="mq-skeleton" style={{ height: 260 }} /></div>
      ))}
    </div>
  );
}
