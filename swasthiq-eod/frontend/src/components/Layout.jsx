import { useState } from "react";
import { NavLink, Outlet, useLocation, useSearchParams } from "react-router-dom";
import { getDays, uploadDay } from "../api.js";
import useAsync from "../hooks/useAsync.js";
import { ChartIcon, MessageIcon, ReceiptIcon } from "./Icons.jsx";
import { Empty, ErrorState, Loading } from "./State.jsx";
import { formatDate, plural } from "../format.js";

const NAV = [
  { to: "/reconciliation", label: "Reconciliation", Icon: ReceiptIcon },
  { to: "/analytics", label: "Analytics", Icon: ChartIcon },
  { to: "/narrative", label: "AI narrative", Icon: MessageIcon },
];

export default function Layout() {
  const [params, setParams] = useSearchParams();
  const { search } = useLocation(); // keep ?date= when moving between screens
  const [version, setVersion] = useState(0); // bump after an upload so every screen refetches
  const [notice, setNotice] = useState(null);

  const { data, error, loading, reload } = useAsync(getDays, [version]);
  const days = data?.days ?? [];
  const selected = days.find((d) => d.business_date === params.get("date")) ?? days[0];

  async function onFile(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow picking the same file again
    if (!file) return;
    try {
      const records = JSON.parse(await file.text());
      const dateInName = file.name.match(/(\d{4}-\d{2}-\d{2})/)?.[1];
      const res = await uploadDay(records, dateInName);
      const skipped = res.rejected_count
        ? ` ${plural(res.rejected_count, "row")} rejected and left out of the totals.` : "";
      setNotice({
        kind: res.rejected_count ? "warn" : "ok",
        text: `${formatDate(res.business_date)} ${res.status}: ${plural(res.accepted_count, "row")} accepted.${skipped}`,
      });
      setVersion((v) => v + 1);
      setParams({ date: res.business_date });
    } catch (err) {
      const text = err instanceof SyntaxError ? "That file isn't valid JSON." : err.message;
      setNotice({ kind: "error", text });
    }
  }

  const ctx = {
    days, date: selected?.business_date, clinicId: selected?.clinic_id, version,
    setDate: (d) => setParams({ date: d }), onFile,
  };

  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main">
        <div className="brand">EOD Agent</div>
        {NAV.map(({ to, label, Icon }) => (
          <NavLink key={to} to={{ pathname: to, search }} className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}>
            <Icon /> <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <main className="content">
        {notice && (
          <div className={`notice notice-${notice.kind}`} role="status">
            <span>{notice.text}</span>
            <button className="link" onClick={() => setNotice(null)}>Dismiss</button>
          </div>
        )}
        {loading && !data ? <Loading />
          : error ? <ErrorState error={error} onRetry={reload} />
          : !selected ? (
            <Empty>
              <p>No billing logs yet.</p>
              <p className="muted">Upload a daily billing log (.json) to see its reconciliation.</p>
              <input type="file" accept="application/json,.json" onChange={onFile} />
            </Empty>
          ) : <Outlet context={ctx} />}
      </main>
    </div>
  );
}
