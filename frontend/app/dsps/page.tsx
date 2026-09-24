import { api } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";

export const dynamic = "force-dynamic";

export default async function DSPsPage() {
  let dsps;
  let error: string | null = null;
  try {
    dsps = await api.dsps();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load DSPs";
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white">DSPs</h1>
        <p className="text-slate-400 text-sm mt-1">
          Registered demand-side platforms. Behavior (latency, failure rate, timeout rate) is tuned live via the
          DSP simulator&apos;s admin API — see the System page for how each DSP is currently configured.
        </p>
      </div>

      {error && <div className="card border-rose-900 text-rose-300">{error}</div>}

      {dsps && (
        <div className="card overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Endpoint</th>
                <th>Timeout</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {dsps.map((d) => (
                <tr key={d.id}>
                  <td className="font-medium text-white">{d.name}</td>
                  <td className="font-mono text-xs text-slate-400">{d.endpoint}</td>
                  <td>{d.timeout_ms}ms</td>
                  <td>
                    <StatusBadge status={d.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
