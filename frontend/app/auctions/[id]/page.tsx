import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

export const dynamic = "force-dynamic";

export default async function AuctionDetailPage({ params }: { params: { id: string } }) {
  let auction;
  let bids;
  let error: string | null = null;
  try {
    [auction, bids] = await Promise.all([api.auction(params.id), api.bidsForAuction(params.id)]);
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load auction";
  }

  if (error || !auction) {
    return <div className="card border-rose-900 text-rose-300">{error || "Auction not found"}</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white">Auction {auction.request_id}</h1>
        <p className="text-slate-400 text-sm mt-1">Auction ID: {auction.id}</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="card">
          <div className="stat-label">Status</div>
          <div className="mt-2">
            <StatusBadge status={auction.status} />
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Auction Latency</div>
          <div className="stat-value">{auction.duration_ms ?? "-"}ms</div>
        </div>
        <div className="card">
          <div className="stat-label">Winner</div>
          <div className="stat-value">{auction.winning_dsp_name || "None"}</div>
        </div>
        <div className="card">
          <div className="stat-label">Clearing Price</div>
          <div className="stat-value">
            {auction.clearing_price != null ? `$${auction.clearing_price.toFixed(2)}` : "-"}
          </div>
        </div>
      </div>

      <div className="card overflow-x-auto">
        <h2 className="text-sm font-medium text-slate-300 mb-4">DSP Responses</h2>
        <table className="data-table">
          <thead>
            <tr>
              <th>DSP</th>
              <th>Bid Amount</th>
              <th>Response Time</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {bids?.map((b) => (
              <tr key={b.id}>
                <td>{b.dsp_name || b.dsp_id}</td>
                <td>${b.amount.toFixed(2)}</td>
                <td>{b.response_time_ms != null ? `${b.response_time_ms}ms` : "-"}</td>
                <td>
                  <StatusBadge status={b.status} />
                </td>
              </tr>
            ))}
            {(!bids || bids.length === 0) && (
              <tr>
                <td colSpan={4} className="text-center text-slate-500 py-6">
                  No bids recorded for this auction.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
