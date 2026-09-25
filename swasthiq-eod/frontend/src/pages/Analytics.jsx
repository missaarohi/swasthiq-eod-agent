import { useOutletContext } from "react-router-dom";
import { getReport } from "../api.js";
import useAsync from "../hooks/useAsync.js";
import PageHeader from "../components/PageHeader.jsx";
import { ErrorState, Loading } from "../components/State.jsx";
import { formatDate, formatINR } from "../format.js";

function HourChart({ hours, peak }) {
  if (!hours.length) return <p className="muted">No sales were logged on this day, so there is no hourly revenue.</p>;
  const max = Math.max(...hours.map((h) => h.revenue_paise), 1);
  return (
    <div className="bars" role="list">
      {hours.map((h) => {
        const isPeak = peak && h.hour === peak.hour;
        const text = `${h.label}: ${formatINR(h.revenue_paise)} from ${h.visit_count} visits`;
        return (
          <div className="bar-col" key={h.hour} role="listitem" aria-label={text} title={text}>
            <div className="bar-track">
              <div className={"bar" + (isPeak ? " peak" : "")} style={{ height: `${Math.max((h.revenue_paise / max) * 100, 2)}%` }} />
            </div>
            <span className="bar-label">{h.label.split("\u2013")[0]}</span>
          </div>
        );
      })}
    </div>
  );
}

function Ranking({ title, rows, valueOf }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      {rows.length === 0 ? <p className="muted">No medicines sold on this day.</p> : (
        <ol className="ranking">
          {rows.map((row) => (
            <li key={row.drug_name}>
              <span className="rank">{row.rank}</span>
              <span className="drug">{row.drug_name}</span>
              <span className="value">{valueOf(row)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export default function Analytics() {
  const { date, clinicId, version } = useOutletContext();
  const { data: r, error, loading, reload } = useAsync(() => getReport(date, clinicId), [date, clinicId, version]);
  const a = r?.analytics;

  return (
    <>
      <PageHeader title="Analytics" subtitle={r ? `${r.clinic.name} \u2014 ${formatDate(r.business_date)}` : ""} />
      {loading && !r ? <Loading /> : error ? <ErrorState error={error} onRetry={reload} /> : (
        <>
          <section className="card">
            <div className="card-head">
              <h2>Revenue by hour of day</h2>
              {a.peak_hour && (
                <span className="peak-callout">Peak: {a.peak_hour.label} &mdash; {formatINR(a.peak_hour.revenue_paise)}</span>
              )}
            </div>
            <HourChart hours={a.revenue_by_hour} peak={a.peak_hour} />
            <p className="muted small">Hours are in UTC, as logged. Revenue is billed value after discounts.</p>
          </section>

          <div className="two-col">
            <Ranking title={"Top medicines \u2014 by quantity"} rows={a.top_by_quantity} valueOf={(row) => `${row.qty} units`} />
            <Ranking title={"Top medicines \u2014 by revenue"} rows={a.top_by_revenue} valueOf={(row) => formatINR(row.revenue_paise)} />
          </div>
        </>
      )}
    </>
  );
}
