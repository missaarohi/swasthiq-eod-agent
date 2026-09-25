export function Loading({ label = "Loading\u2026" }) {
  return <div className="state" role="status">{label}</div>;
}

export function ErrorState({ error, onRetry }) {
  return (
    <div className="state state-error" role="alert">
      <p>{error?.message || "Something went wrong."}</p>
      {onRetry && <button className="btn" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Empty({ children }) {
  return <div className="state">{children}</div>;
}
