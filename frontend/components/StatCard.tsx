export function StatCard({
  label,
  value,
  suffix,
}: {
  label: string;
  value: string | number;
  suffix?: string;
}) {
  return (
    <div className="card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {value}
        {suffix && <span className="text-sm text-slate-400 ml-1">{suffix}</span>}
      </div>
    </div>
  );
}
