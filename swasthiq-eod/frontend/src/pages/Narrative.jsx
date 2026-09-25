import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import { getNarrative } from "../api.js";
import useAsync from "../hooks/useAsync.js";
import PageHeader from "../components/PageHeader.jsx";
import { ErrorState, Loading } from "../components/State.jsx";

export default function Narrative() {
  const { date, clinicId, version } = useOutletContext();
  // regen remembers which day the owner asked to regenerate, so switching days goes back to the cached summary
  const [regen, setRegen] = useState({ date: null, n: 0 });
  const refresh = regen.date === date && regen.n > 0;
  const { data: n, error, loading, reload } = useAsync(
    () => getNarrative(date, clinicId, refresh),
    [date, clinicId, version, regen.n]
  );
  const ok = n?.status === "success";

  return (
    <>
      <PageHeader title="AI narrative summary"
        subtitle={n ? `Generated from this day's reconciliation \u2014 ${n.clinic.name}` : ""} />
      {loading ? <Loading label={"Writing the summary\u2026"} /> : error ? <ErrorState error={error} onRetry={reload} /> : (
        <div className="two-col narrative-grid">
          <section className="bubble-card">
            <div className="bubble-head">
              Sent to {n.clinic.owner || "the owner"} &middot; WhatsApp
              <span className="badge badge-ai">AI suggested</span>
            </div>
            {/* white-space: pre-wrap keeps the paragraph breaks from the message */}
            <p className="bubble-text">
              {n.segments.map((s, i) =>
                s.key ? <mark key={i} title={`from ${s.key}`}>{s.text}</mark> : <span key={i}>{s.text}</span>
              )}
            </p>
            <div className="bubble-foot">
              <span className={"badge " + (ok ? "badge-ok" : "badge-warn")}>{ok ? "Success" : "Template fallback"}</span>
              <button className="btn" onClick={() => setRegen((r) => ({ date, n: r.date === date ? r.n + 1 : 1 }))}>Regenerate</button>
            </div>
            {!ok && <p className="small muted">{n.fallback_reason} This text was built from a fixed template, not the model.</p>}
            {n.notes.map((note) => <p key={note} className="small muted">{note}</p>)}
          </section>

          <section className="card">
            <h2>Traced figures</h2>
            <p className="muted small">Every number in the message is filled in by the server from these report fields.</p>
            <ul className="traced">
              {n.traced_figures.map((f) => (
                <li key={f.key}>
                  <strong>{f.display}</strong>
                  <code>{f.report_field}</code>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </>
  );
}
