"use client";

/**
 * EvidenceOps client. Talks to the EvidenceOps HTTP API
 * (`python -m evidenceops serve`, default http://127.0.0.1:8100) when it is
 * up, and otherwise serves the bundled demo data so the incident pages still
 * work without Docker. Demo actions (investigate, propose, approve, test) are
 * simulated in memory and never leave the browser.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import demo from "./evidence-demo.json";

export const EVIDENCE_URL = (process.env.NEXT_PUBLIC_EVIDENCEOPS_URL || "http://127.0.0.1:8100").replace(/\/$/, "");

// ------------------------------------------------------------------ types

export type Category =
  | "external_dsp_latency"
  | "config_regression"
  | "db_pool_exhaustion"
  | "missing_index"
  | "poison_message"
  | "duplicate_delivery_idempotency";

export interface Scenario {
  id: string;
  title: string;
  report: string;
  alert: string;
  ambiguous: boolean;
}

export interface Hypothesis {
  category: string;
  statement: string;
  confidence: number;
  supporting: string[];
  refuting: string[];
  component?: string;
}

export interface EvidenceItem {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  result: unknown;
}

export interface Report {
  method: string;
  incident_id: string;
  hypotheses: Hypothesis[];
  abstained: boolean;
  abstain_reason?: string;
  timeline: { at: string; event: string; evidence: string[] }[];
  evidence: Record<string, EvidenceItem>;
  tool_calls: number;
  elapsed_seconds: number;
  cost_usd: number;
  meta?: Record<string, unknown>;
}

export interface SuccessPoint {
  window_start: string;
  requests: number;
  success_rate: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  errors?: Record<string, number>;
}
export interface DriftPoint {
  sampled_at: string;
  finished_auctions: number;
  rolled_up: number;
  not_yet_counted: number;
}

export interface Incident {
  incident_id: string;
  report: string;
  telemetry_window: [string, string];
  services?: string[];
  alert: { metric: string; definition: string; timeline: (SuccessPoint | DriftPoint)[] };
}

export interface Deployment {
  started_at: string;
  finished_at?: string;
  from_version: string;
  to_version: string;
  services?: string[];
  changes: Record<string, { from: string; to: string }>;
  migrations?: string[];
}

export interface RunSummary {
  run_id: string;
  incident_id: string;
  report: string;
  alert_metric: string;
  telemetry_window: [string, string];
  investigations: Record<string, { top: string | null; abstained: boolean; tool_calls: number }>;
  remediations: Record<string, { status: string; verdict: string | null }>;
}

export interface RunDetail extends RunSummary {
  incident: Incident;
  deployments: Deployment[];
}

export interface Change {
  kind: string;
  setting?: string;
  value?: string | number;
  dsps?: string[];
  migration?: string;
  groups?: string[];
}

export interface Proposal {
  run_id: string;
  method: string;
  hypothesis: string | null;
  changes: Change[];
  resolved_changes?: Change[];
  rationale: string;
  status: "awaiting_approval" | "approved" | string;
  digest: string;
  created_at: string;
  approved_by?: string;
  approved_at?: string;
  result?: SandboxResult | null;
}

export interface SandboxResult {
  verdict: "verified" | "not_fixed" | "inconclusive";
  proposal_digest?: string;
  incident_reproduced?: boolean;
  recovered?: boolean;
  baseline_success_rate?: number | null;
  incident_success_rate?: number | null;
  recovered_success_rate?: number | null;
  baseline_analytics_drift?: number | null;
  incident_analytics_drift?: number | null;
  recovered_analytics_drift?: number | null;
  [k: string]: unknown;
}

export interface Grading {
  ground_truth: {
    scenario_id: string;
    category: string;
    ambiguous: boolean;
    component?: string;
    summary?: string;
    distinguishing_evidence?: string[];
    candidates?: string[] | null;
  };
  verification?: Record<string, unknown> | null;
  grades: {
    method: string;
    predicted: string | null;
    top1_correct: boolean;
    abstained: boolean;
    correct_abstention: boolean | null;
    supported: boolean | null;
    tool_calls: number;
  }[];
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress?: string[] | string | null;
  error?: string | null;
  result?: unknown;
}

export type ResultRow = (typeof demo.results)[number];

// ------------------------------------------------------------------ helpers

export const CATEGORY_LABEL: Record<string, string> = {
  external_dsp_latency: "Slow external bidders",
  config_regression: "Bad config deploy",
  db_pool_exhaustion: "DB pool exhaustion",
  missing_index: "Missing index",
  poison_message: "Poison message",
  duplicate_delivery_idempotency: "Duplicate delivery",
};
export const label = (c: string | null | undefined) => (c ? CATEGORY_LABEL[c] ?? c.replace(/_/g, " ") : "Abstained");

export const METHOD_LABEL: Record<string, string> = {
  fixed_workflow: "Fixed workflow",
  agent_offline: "Agent (offline policy)",
  agent: "Agent (LLM)",
  log_only: "Logs only (LLM)",
};
export const methodLabel = (m: string) => METHOD_LABEL[m] ?? m.replace(/_/g, " ");

/** "20261020T140200Z-s03-db-pool-exhaustion" → "s03-db-pool-exhaustion" */
export const scenarioOf = (runId: string) => runId.replace(/^\d{8}T\d{6}Z-/, "");

export const isSuccess = (p: SuccessPoint | DriftPoint): p is SuccessPoint => "success_rate" in p;

// ------------------------------------------------------------------ sources

type DemoRun = (typeof demo.runs)[number];

interface Source {
  scenarios(): Promise<Scenario[]>;
  runs(): Promise<RunSummary[]>;
  run(id: string): Promise<RunDetail>;
  report(id: string, method: string): Promise<Report>;
  proposal(id: string, method: string): Promise<Proposal>;
  grading(id: string): Promise<Grading>;
  investigate(id: string, method: string): Promise<Job>;
  propose(id: string, method: string): Promise<Proposal>;
  approve(id: string, method: string, approver: string, digest: string): Promise<Proposal>;
  test(id: string, method: string): Promise<Job>;
  record(scenarioIds: string[], quick: boolean): Promise<Job>;
  job(id: string): Promise<Job>;
  results(): Promise<ResultRow[]>;
}

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function liveSource(token: string): Source {
  const call = async <T,>(path: string, init?: RequestInit): Promise<T> => {
    const res = await fetch(`${EVIDENCE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* not json */
      }
      throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return res.json();
  };
  const post = <T,>(path: string, body: unknown) => call<T>(path, { method: "POST", body: JSON.stringify(body) });
  return {
    scenarios: () => call("/scenarios"),
    runs: () => call("/runs"),
    run: (id) => call(`/runs/${id}`),
    report: (id, m) => call(`/runs/${id}/investigations/${m}`),
    proposal: (id, m) => call(`/runs/${id}/remediation/${m}`),
    grading: (id) => call(`/runs/${id}/grading`),
    investigate: (id, method) => post(`/runs/${id}/investigations`, { method }),
    propose: (id, method) => post(`/runs/${id}/remediation/propose`, { method }),
    approve: (id, method, approver, digest) => post(`/runs/${id}/remediation/approve`, { method, approver, digest }),
    test: (id, method) => post(`/runs/${id}/remediation/test`, { method, quick: true }),
    record: (scenario_ids, quick) => post("/runs", { scenario_ids, quick }),
    job: (id) => call(`/jobs/${id}`),
    // The measured suite table is the published one; live grading is per run.
    results: async () => demo.results,
  };
}

/** In-memory copy of the demo data, so demo actions can change it. */
function demoSource(): Source {
  const runs: DemoRun[] = JSON.parse(JSON.stringify(demo.runs));
  // Start each sample with only the fixed workflow investigated, so the agent can be run live.
  const investigated: Record<string, Set<string>> = Object.fromEntries(runs.map((r) => [r.run_id, new Set(["fixed_workflow"])]));
  const proposals: Record<string, Proposal> = {};
  const results: Record<string, SandboxResult> = {};
  const jobs: Record<string, { job: Job; done: number; finish: () => unknown; steps: string[] }> = {};
  let seq = 0;

  const find = (id: string) => {
    const r = runs.find((x) => x.run_id === id);
    if (!r) throw new ApiError(404, `no run '${id}'`);
    return r;
  };
  const wait = <T,>(v: T, ms = 220) => new Promise<T>((res) => setTimeout(() => res(v), ms));
  const summary = (r: DemoRun): RunSummary => ({
    run_id: r.run_id,
    incident_id: r.incident.incident_id,
    report: r.incident.report,
    alert_metric: r.incident.alert.metric,
    telemetry_window: r.incident.telemetry_window as [string, string],
    investigations: Object.fromEntries(
      [...investigated[r.run_id]].map((m) => {
        const rep = (r.reports as Record<string, Report>)[m];
        return [m, { top: rep.abstained ? null : rep.hypotheses[0]?.category ?? null, abstained: rep.abstained, tool_calls: rep.tool_calls }];
      }),
    ),
    remediations: Object.fromEntries(
      Object.entries(proposals)
        .filter(([k]) => k.startsWith(r.run_id + "|"))
        .map(([k, p]) => [k.split("|")[1], { status: p.status, verdict: results[k]?.verdict ?? null }]),
    ),
  });
  const startJob = (kind: string, steps: string[], finish: () => unknown): Job => {
    const id = `demo-${++seq}`;
    const job: Job = { id, kind, status: "running", progress: [] };
    jobs[id] = { job, done: 0, finish, steps };
    return { ...job };
  };

  return {
    scenarios: () => wait(demo.scenarios),
    runs: () => wait(runs.map(summary)),
    run: async (id) => {
      const r = find(id);
      return wait({ ...summary(r), incident: r.incident as Incident, deployments: r.deployments as Deployment[] });
    },
    report: async (id, m) => {
      const r = find(id);
      if (!investigated[id].has(m)) throw new ApiError(404, `no ${m} investigation for ${id}`);
      return wait((r.reports as Record<string, Report>)[m]);
    },
    proposal: async (id, m) => {
      const p = proposals[`${id}|${m}`];
      if (!p) throw new ApiError(404, `no ${m} proposal for ${id}`);
      return wait({ ...p, ...(results[`${id}|${m}`] ? { result: results[`${id}|${m}`] } : {}) } as Proposal);
    },
    grading: async (id) => wait(find(id).grading as Grading),
    investigate: async (id, method) => {
      const r = find(id);
      const rep = (r.reports as Record<string, Report>)[method];
      if (!rep) throw new ApiError(400, `${methodLabel(method)} needs an API key, so it only runs against the live EvidenceOps API`);
      const steps = Object.values(rep.evidence).map((e) => `${e.id} ${e.tool}`);
      return startJob("investigate", [...steps, "writing report"], () => investigated[id].add(method));
    },
    propose: async (id, method) => {
      const r = find(id);
      if (!investigated[id].has(method)) throw new ApiError(404, "no saved investigation for that method; investigate first");
      const p = { ...(r.proposals as Record<string, Proposal>)[method] };
      proposals[`${id}|${method}`] = p;
      delete results[`${id}|${method}`];
      return wait(p);
    },
    approve: async (id, method, approver, digest) => {
      const p = proposals[`${id}|${method}`];
      if (!p) throw new ApiError(404, "no proposal to approve");
      if (p.digest !== digest) throw new ApiError(400, "the proposal changed since it was reviewed (digest mismatch); review it again");
      if (!approver.trim()) throw new ApiError(400, "approval needs a name");
      Object.assign(p, { status: "approved", approved_by: approver.trim(), approved_at: new Date().toISOString() });
      return wait({ ...p });
    },
    test: async (id, method) => {
      const r = find(id);
      const key = `${id}|${method}`;
      const p = proposals[key];
      if (!p || p.status !== "approved") throw new ApiError(400, "the proposal has not been approved");
      const truth = r.grading.ground_truth.category;
      const right = p.hypothesis === truth || (r.grading.ground_truth.ambiguous && p.changes.length > 0);
      const steps = ["reset sandbox stack", "seed demo data", "replay the incident", "apply the approved changes", "measure recovery"];
      return startJob("test", steps, () => {
        const v = r.grading.verification as { baseline: number; incident: number; unit: string };
        const success = r.incident.alert.metric === "auction_success_rate";
        results[key] = {
          verdict: right ? "verified" : "not_fixed",
          proposal_digest: p.digest,
          incident_reproduced: true,
          recovered: right,
          ...(success
            ? { baseline_success_rate: v.baseline / 100, incident_success_rate: v.incident / 100, recovered_success_rate: right ? 0.97 : 0.04 }
            : { baseline_analytics_drift: v.baseline, incident_analytics_drift: v.incident, recovered_analytics_drift: right ? 3 : v.incident }),
          sample: true,
        };
      });
    },
    record: async () => {
      throw new ApiError(400, "Recording a new incident rebuilds the platform with Docker, so it needs the live EvidenceOps API.");
    },
    job: async (id) => {
      const j = jobs[id];
      if (!j) throw new ApiError(404, "no such job");
      j.done = Math.min(j.steps.length, j.done + 1);
      j.job.progress = j.steps.slice(0, j.done);
      if (j.done >= j.steps.length && j.job.status === "running") {
        j.finish();
        j.job.status = "succeeded";
      }
      return wait({ ...j.job }, 350);
    },
    results: async () => demo.results,
  };
}

// ------------------------------------------------------------------ provider

interface EvidenceCtx {
  source: Source;
  live: boolean | null; // null while checking
  version: number;
  bump: () => void;
  token: string;
  setToken: (t: string) => void;
}

const Ctx = createContext<EvidenceCtx | null>(null);

export function EvidenceProvider({ children }: { children: React.ReactNode }) {
  const [live, setLive] = useState<boolean | null>(null);
  const [version, setVersion] = useState(0);
  const [token, setTokenState] = useState("");
  const demoRef = useRef<Source | null>(null);

  useEffect(() => {
    try {
      setTokenState(localStorage.getItem("rtb.evidenceToken") ?? "");
    } catch {
      /* storage blocked */
    }
    let cancelled = false;
    const check = () =>
      fetch(`${EVIDENCE_URL}/health`, { cache: "no-store", signal: AbortSignal.timeout(1500) })
        .then((r) => !cancelled && setLive(r.ok))
        .catch(() => !cancelled && setLive(false));
    check();
    const t = setInterval(check, 20000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const setToken = useCallback((t: string) => {
    setTokenState(t);
    try {
      localStorage.setItem("rtb.evidenceToken", t);
    } catch {
      /* storage blocked */
    }
  }, []);

  const source = useMemo(() => {
    if (live) return liveSource(token);
    demoRef.current ??= demoSource();
    return demoRef.current;
  }, [live, token]);

  const bump = useCallback(() => setVersion((v) => v + 1), []);
  const value = useMemo(() => ({ source, live, version, bump, token, setToken }), [source, live, version, bump, token, setToken]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useEvidence() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useEvidence must be used inside EvidenceProvider");
  return c;
}

/** Fetch with the current source; refetches when the source or version changes. */
export function useEvidenceQuery<T>(fn: (s: Source) => Promise<T>, deps: unknown[] = []) {
  const { source, live, version } = useEvidence();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);
  useEffect(() => {
    if (live === null) return;
    let cancelled = false;
    fn(source)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setData(null);
        setError({ status: e instanceof ApiError ? e.status : 0, message: e instanceof Error ? e.message : String(e) });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, live, version, ...deps]);
  return { data, error, loading: data === null && error === null };
}

/** Poll a job until it finishes. */
export async function waitForJob(source: Source, job: Job, onProgress?: (j: Job) => void, everyMs = 1200): Promise<Job> {
  let j = job;
  while (j.status === "queued" || j.status === "running") {
    await new Promise((r) => setTimeout(r, everyMs));
    j = await source.job(j.id);
    onProgress?.(j);
  }
  if (j.status === "failed") throw new Error(j.error || "job failed");
  return j;
}

export const DEMO_NOTE = demo._note;
