import { useOutletContext } from "react-router-dom";
import { getReport } from "../api.js";
import useAsync from "../hooks/useAsync.js";
import PageHeader from "../components/PageHeader.jsx";
import StatCard from "../components/StatCard.jsx";
import DataQualityNotice from "../components/DataQualityNotice.jsx";
import { ErrorState, Loading } from "../components/State.jsx";
import { formatINR, plural } from "../format.js";

const MODE_NAMES = { cash: "Cash", card: "Card", upi: "UPI" };

export default function Reconciliation() {
  const { date, clinicId, version } = useOutletContext();
  const { data: r, error, loading, reload } = useAsync(() => getReport(date, clinicId), [date, clinicId, version]);

  const subtitle = r ? `${r.clinic.name}${r.clinic.location ? " \u2014 " + r.clinic.location : ""}` : "";
  const t = r?.totals;

  return (
    <>
      <PageHeader title="EOD reconciliation" subtitle={subtitle} />
      {loading && !r ? <Loading /> : error ? <ErrorState error={error} onRetry={reload} /> : (
        <>
          <DataQualityNotice quality={r.data_quality} />
          <section className="stat-grid" aria-label="Totals">
            <StatCard label="Total billed" value={formatINR(t.billed_paise)} sub={plural(r.visit_count, "visit")} tone="blue" />
            <StatCard label="Total collected" value={formatINR(t.collected_paise)}
              sub={r.collection_rate_pct == null ? "Nothing billed" : `${r.collection_rate_pct}% of billed`} tone="green" />
            <StatCard label="Outstanding" value={formatINR(t.outstanding_paise)} sub={plural(r.pending_visit_count, "pending visit")} tone="amber" />
            <StatCard label="Refunds" value={formatINR(t.refunds_paise)} sub={plural(r.refund_count, "refund")} tone="red" />
          </section>

          <section className="card">
            <h2>Payment mode breakdown</h2>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr><th>Mode</th><th>Billed</th><th>Collected</th><th>Outstanding</th><th>Refunds</th></tr>
                </thead>
                <tbody>
                  {r.by_payment_mode.map((m) => (
                    <tr key={m.mode}>
                      <th scope="row">{MODE_NAMES[m.mode]}</th>
                      <td>{formatINR(m.billed_paise)}</td>
                      <td>{formatINR(m.collected_paise)}</td>
                      <td>{formatINR(m.outstanding_paise)}</td>
                      <td>{formatINR(m.refunds_paise)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th scope="row">Total</th>
                    <td>{formatINR(t.billed_paise)}</td>
                    <td>{formatINR(t.collected_paise)}</td>
                    <td>{formatINR(t.outstanding_paise)}</td>
                    <td>{formatINR(t.refunds_paise)}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
            <p className="muted small">
              Billed is after discounts ({formatINR(t.discount_paise)} given). Refund rows are counted only under Refunds.
            </p>
          </section>
        </>
      )}
    </>
  );
}
