export default function StatCard({ label, value, sub, tone }) {
  return (
    <div className="card stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className={`stat-sub tone-${tone}`}>{sub}</div>
    </div>
  );
}
