import { api } from "@/lib/api";
import { StatCard } from "@/components/StatCard";
import { LatencyBarChart } from "@/components/LatencyBarChart";

export const dynamic = "force-dynamic";

export default async function AnalyticsPage() {
  let overview;
  let error: string | null = null;
  try {
    overview = await api.overview();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load analytics";
  }

  if (error || !overview) {
    return <div className="card border-rose-900 text-rose-300">{error}</div>;
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-white">Analytics</h1>
        <p className="text-slate-400 text-sm mt-1">
          Computed directly from the auction/bid tables. In production this would be backed by the Kafka analytics
          consumer&apos;s pre-aggregated rollups (see docs/architecture.md) rather than live queries.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <StatCard label="Total Auctions" value={overview.total_auctions} />
        <StatCard label="Completed" value={overview.completed_auctions} />
        <StatCard label="No Bid" value={overview.no_bid_auctions} />
        <StatCard label="Failed" value={overview.failed_auctions} />
        <StatCard label="Win Rate" value={(overview.win_rate * 100).toFixed(1)} suffix="%" />
        <StatCard label="Avg Winning Bid" value={`$${overview.avg_winning_bid.toFixed(2)}`} />
      </div>

      <div className="card">
        <h2 className="text-sm font-medium text-slate-300 mb-4">Latency Distribution</h2>
        <LatencyBarChart p50={overview.p50_latency_ms} p95={overview.p95_latency_ms} p99={overview.p99_latency_ms} />
        <p className="text-xs text-slate-500 mt-3">
          Average latency: {overview.avg_latency_ms}ms across {overview.total_auctions} auctions.
        </p>
      </div>
    </div>
  );
}
