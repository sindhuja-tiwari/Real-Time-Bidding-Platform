export function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "COMPLETED" || status === "WON" || status === "VALID"
      ? "badge-success"
      : status === "FAILED" || status === "BELOW_FLOOR" || status === "BUDGET_EXCEEDED" || status === "INVALID"
        ? "badge-fail"
        : "badge-warn";
  return <span className={`badge ${cls}`}>{status}</span>;
}
