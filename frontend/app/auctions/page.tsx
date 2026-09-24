import Link from "next/link";
import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

export const dynamic = "force-dynamic";

export default async function AuctionsPage() {
  let auctions;
  let error: string | null = null;
  try {
    auctions = await api.auctions(100);
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load auctions";
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white">Auctions</h1>
        <p className="text-slate-400 text-sm mt-1">Most recent auctions, newest first.</p>
      </div>

      {error && <div className="card border-rose-900 text-rose-300">{error}</div>}

      {auctions && (
        <div className="card overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Request ID</th>
                <th>Status</th>
                <th>Latency</th>
                <th>Winning DSP</th>
                <th>Clearing Price</th>
                <th>Started</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {auctions.map((a) => (
                <tr key={a.id}>
                  <td className="font-mono text-xs">{a.request_id}</td>
                  <td>
                    <StatusBadge status={a.status} />
                  </td>
                  <td>{a.duration_ms != null ? `${a.duration_ms}ms` : "-"}</td>
                  <td>{a.winning_dsp_name || "-"}</td>
                  <td>{a.clearing_price != null ? `$${a.clearing_price.toFixed(2)}` : "-"}</td>
                  <td className="text-slate-400">{new Date(a.started_at).toLocaleTimeString()}</td>
                  <td>
                    <Link href={`/auctions/${a.id}`} className="text-accent hover:underline">
                      View
                    </Link>
                  </td>
                </tr>
              ))}
              {auctions.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-center text-slate-500 py-6">
                    No auctions yet. Send a request to POST /api/v1/auctions to see one here.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
