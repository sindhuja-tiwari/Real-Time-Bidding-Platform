import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

export const dynamic = "force-dynamic";

export default async function CampaignsPage() {
  let campaigns;
  let error: string | null = null;
  try {
    campaigns = await api.campaigns();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load campaigns";
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white">Campaigns</h1>
        <p className="text-slate-400 text-sm mt-1">Budgets, targeting, and floor prices per campaign.</p>
      </div>

      {error && <div className="card border-rose-900 text-rose-300">{error}</div>}

      {campaigns && (
        <div className="card overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Daily Budget</th>
                <th>Remaining</th>
                <th>Floor</th>
                <th>Countries</th>
                <th>Devices</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => (
                <tr key={c.id}>
                  <td className="font-medium text-white">{c.name}</td>
                  <td>
                    <StatusBadge status={c.status} />
                  </td>
                  <td>${c.daily_budget.toFixed(2)}</td>
                  <td>${c.remaining_budget.toFixed(2)}</td>
                  <td>${c.bid_floor.toFixed(2)}</td>
                  <td>{c.target_countries.length ? c.target_countries.join(", ") : "Any"}</td>
                  <td>{c.target_devices.length ? c.target_devices.join(", ") : "Any"}</td>
                </tr>
              ))}
              {campaigns.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-center text-slate-500 py-6">
                    No campaigns yet. Run the seed script or create one via POST /api/v1/campaigns.
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
