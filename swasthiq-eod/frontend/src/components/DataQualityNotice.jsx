import { formatINR } from "../format.js";

// Rows we rejected change the totals, so the owner must be able to see them.
export default function DataQualityNotice({ quality }) {
  const { rejected_rows: rejected, warnings } = quality;
  if (!rejected.length && !warnings.length) return null;
  return (
    <section className="card notice-card" aria-label="Data quality">
      {rejected.length > 0 && (
        <>
          <h2>{rejected.length === 1 ? "1 row was left out of these totals" : `${rejected.length} rows were left out of these totals`}</h2>
          <ul>
            {rejected.map((r, i) => (
              <li key={i}>
                <strong>Row {r.row}{r.visit_id ? ` (${r.visit_id})` : ""}:</strong> {r.message}
                {r.amount_paid_paise != null && r.amount_paid_paise !== 0 && (
                  <> {formatINR(Math.abs(r.amount_paid_paise))} recorded on this row is not reconciled.</>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {warnings.length > 0 && (
        <>
          <h2>Adjustments made while reading the log</h2>
          <ul>{warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
        </>
      )}
    </section>
  );
}
