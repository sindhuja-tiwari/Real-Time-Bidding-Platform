import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function SystemPage() {
  let health;
  let healthError: string | null = null;
  try {
    health = await api.health();
  } catch (e) {
    healthError = e instanceof Error ? e.message : "unreachable";
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white">System</h1>
        <p className="text-slate-400 text-sm mt-1">
          Infrastructure health and links to the observability stack (Section 16/17 of the spec).
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card">
          <div className="stat-label">Backend API</div>
          <div className="stat-value">
            {health ? (
              <span className="text-emerald-400">Healthy</span>
            ) : (
              <span className="text-rose-400">Unreachable</span>
            )}
          </div>
          {healthError && <p className="text-xs text-slate-500 mt-2">{healthError}</p>}
          {health && (
            <p className="text-xs text-slate-500 mt-2">
              env={health.env} · service={health.service}
            </p>
          )}
        </div>

        <div className="card">
          <div className="stat-label">Observability</div>
          <div className="mt-3 flex flex-col gap-2 text-sm">
            <a href="http://localhost:9090" target="_blank" rel="noreferrer" className="text-accent hover:underline">
              Prometheus →
            </a>
            <a href="http://localhost:3001" target="_blank" rel="noreferrer" className="text-accent hover:underline">
              Grafana (admin/admin) →
            </a>
            <a href="http://localhost:8000/api/v1/docs" target="_blank" rel="noreferrer" className="text-accent hover:underline">
              API Docs (OpenAPI) →
            </a>
            <a href="http://localhost:9000/admin/dsps" target="_blank" rel="noreferrer" className="text-accent hover:underline">
              DSP Simulator Admin →
            </a>
          </div>
        </div>
      </div>

      <div className="card">
        <h2 className="text-sm font-medium text-slate-300 mb-2">Simulate a failure</h2>
        <p className="text-sm text-slate-400">
          To demonstrate graceful degradation (Section 14), reconfigure a DSP&apos;s failure/timeout probability at
          runtime, without redeploying anything:
        </p>
        <pre className="mt-3 text-xs bg-slate-950 rounded-lg p-3 overflow-x-auto text-slate-300">
{`curl -X POST http://localhost:9000/admin/dsps/dsp-c \\
  -H "Content-Type: application/json" \\
  -d '{"campaign_id": "<existing-campaign-id>", "base_bid": 4.1, "latency_ms": 150, "timeout_probability": 0.9}'`}
        </pre>
        <p className="text-sm text-slate-400 mt-3">
          Then re-run a few auctions and watch DSP-C&apos;s timeout rate climb on the Dashboard / Grafana without the
          overall auction endpoint slowing down or failing.
        </p>
      </div>
    </div>
  );
}
