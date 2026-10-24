"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { gsap } from "gsap";
import { SwapText } from "@/components/motion/SwapText";
import { DashRule } from "@/components/motion/DashRule";
import { Reveal } from "@/components/motion/Reveal";
import { useReady } from "@/components/motion/ready";
import { AlertChart } from "@/components/evidence/AlertChart";
import { Mark, SourceBanner } from "@/components/evidence/bits";
import {
  label,
  methodLabel,
  scenarioOf,
  useEvidence,
  useEvidenceQuery,
  waitForJob,
  type Change,
  type Deployment,
  type EvidenceItem,
  type Proposal,
  type Report,
} from "@/lib/evidence";
import { T } from "@/lib/theme";

const METHODS = ["agent_offline", "fixed_workflow", "agent", "log_only"];
const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export default function CaseFile() {
  const { runId } = useParams<{ runId: string }>();
  const run = useEvidenceQuery((s) => s.run(runId), [runId]);
  const scenarios = useEvidenceQuery((s) => s.scenarios());
  const ready = useReady();
  const sid = scenarioOf(runId);
  const title = scenarios.data?.find((s) => s.id === sid)?.title ?? sid.replace(/^s\d\d-/, "").replace(/-/g, " ");
  const done = Object.keys(run.data?.investigations ?? {});
  const [method, setMethod] = useState<string | null>(null);
  const active = method ?? (done.includes("agent_offline") ? "agent_offline" : done[0] ?? "agent_offline");

  if (run.error) {
    return (
      <div className="py-20">
        <p style={{ color: T.flame }}>{run.error.message}</p>
        <Link href="/incidents" className="mt-6 inline-block underline">Back to incidents</Link>
      </div>
    );
  }
  const r = run.data;

  return (
    <div>
      <Link href="/incidents" className="group inline-flex items-center gap-2 text-[12px] font-medium uppercase" style={{ color: T.drift }}>
        <span className="transition-transform duration-500 group-hover:-translate-x-1">←</span> Case files
      </Link>

      <header className="mt-10">
        <div className="font-mono text-[12px] uppercase" style={{ color: T.drift }}>
          {r?.incident_id ?? "…"} · {sid.slice(0, 3)} · {r ? `${clock(r.telemetry_window[0])} → ${clock(r.telemetry_window[1])}` : ""}
        </div>
        <h1 className="mt-6 max-w-[20ch] text-[40px] font-medium uppercase leading-[0.94] md:text-[68px]">
          {ready ? <SwapText text={title} stagger={0.05} /> : <span className="opacity-0">{title}</span>}
        </h1>
        {r && (
          <blockquote className="mt-10 max-w-3xl border-l-2 pl-6 font-serif text-[24px] italic leading-[1.3] md:text-[30px]" style={{ borderColor: T.ember }}>
            &ldquo;{r.report.trim()}&rdquo;
            <footer className="mt-3 font-sans text-[12px] not-italic uppercase" style={{ color: T.drift }}>
              The page that opened the incident. Every incident with this alert gets the same words, so they give nothing away.
            </footer>
          </blockquote>
        )}
      </header>

      <div className="mt-12">
        <SourceBanner />
      </div>

      {/* 01 THE ALERT */}
      <Chapter n="01" title="What the pager saw">
        {r ? (
          <>
            <AlertChart incident={r.incident} deployments={r.deployments} />
            <p className="mt-4 text-[13px]" style={{ color: T.drift }}>{r.incident.alert.definition}</p>
            {r.deployments.length > 0 && (
              <div className="mt-10 grid gap-4 md:grid-cols-2">
                {r.deployments.map((d) => <DeployCard key={d.started_at} d={d} />)}
              </div>
            )}
          </>
        ) : (
          <div className="h-[260px] animate-pulse rounded-3xl" style={{ background: T.raised }} />
        )}
      </Chapter>

      {/* 02 THE INVESTIGATION */}
      <Chapter n="02" title="What the evidence says">
        <div className="flex flex-wrap gap-2" role="tablist">
          {METHODS.map((m) => {
            const on = m === active;
            const has = done.includes(m);
            return (
              <button
                key={m}
                role="tab"
                aria-selected={on}
                onClick={() => setMethod(m)}
                className="relative overflow-hidden rounded-full border px-5 py-2.5 text-[12px] font-medium uppercase transition-colors duration-300"
                style={{ borderColor: on ? T.ember : T.cork, background: on ? T.ember : "transparent", color: T.cream }}
              >
                {methodLabel(m)}
                {!has && <span className="ml-2 opacity-60">○</span>}
              </button>
            );
          })}
        </div>
        <div className="mt-10">
          <Investigation runId={runId} method={active} done={done.includes(active)} />
        </div>
      </Chapter>

      {/* 03 THE FIX */}
      <Chapter n="03" title="Test a fix, safely">
        <Remediation runId={runId} method={active} investigated={done.includes(active)} />
      </Chapter>

      {/* 04 ANSWER KEY */}
      <Chapter n="04" title="The answer key">
        <AnswerKey runId={runId} />
      </Chapter>
    </div>
  );
}

function Chapter({ n, title, children }: { n: string; title: string; children: React.ReactNode }) {
  return (
    <section className="mt-28">
      <DashRule />
      <div className="mt-8 grid gap-8 lg:grid-cols-[220px_1fr]">
        <Reveal>
          <div className="font-serif text-[64px] italic leading-none" style={{ color: T.ember }}>{n}</div>
          <h2 className="mt-3 text-[20px] font-medium uppercase leading-tight">{title}</h2>
        </Reveal>
        <div className="min-w-0">{children}</div>
      </div>
    </section>
  );
}

function DeployCard({ d }: { d: Deployment }) {
  return (
    <div className="rounded-[24px] border p-6" style={{ borderColor: T.cork, background: T.raised }}>
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-[13px] font-medium uppercase">
          Deploy <span className="font-mono">{d.from_version} → {d.to_version}</span>
        </span>
        <span className="font-mono text-[11px]" style={{ color: T.drift }}>{clock(d.started_at)}</span>
      </div>
      <div className="mt-4 space-y-2 font-mono text-[12px]">
        {Object.entries(d.changes).map(([k, v]) => (
          <div key={k} className="flex flex-wrap items-baseline gap-x-3">
            <span style={{ color: T.cream }}>{k}</span>
            <span style={{ color: T.drift }}>{v.from}</span>
            <span style={{ color: T.drift }}>→</span>
            <span style={{ color: T.saffron }}>{v.to}</span>
          </div>
        ))}
        {(d.migrations ?? []).map((m) => (
          <div key={m}>
            <span style={{ color: T.drift }}>migration</span> <span style={{ color: T.saffron }}>{m}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Investigation({ runId, method, done }: { runId: string; method: string; done: boolean }) {
  const { source, bump } = useEvidence();
  const report = useEvidenceQuery((s) => (done ? s.report(runId, method) : Promise.resolve(null)), [runId, method, done]);
  const [job, setJob] = useState<{ progress: string[]; error: string | null; busy: boolean }>({ progress: [], error: null, busy: false });

  useEffect(() => setJob({ progress: [], error: null, busy: false }), [method]);

  const investigate = async () => {
    setJob({ progress: [], error: null, busy: true });
    try {
      const j = await source.investigate(runId, method);
      await waitForJob(source, j, (x) => setJob((s) => ({ ...s, progress: Array.isArray(x.progress) ? x.progress.map(String) : s.progress })), 700);
      setJob((s) => ({ ...s, busy: false }));
      bump();
    } catch (e) {
      setJob((s) => ({ ...s, busy: false, error: e instanceof Error ? e.message : String(e) }));
    }
  };

  if (!done) {
    return (
      <div className="rounded-[28px] border p-8" style={{ borderColor: T.cork, background: T.raised }}>
        <p className="max-w-xl text-[17px] leading-relaxed">
          {methodLabel(method)} hasn&apos;t looked at this incident yet.{" "}
          {method === "agent" || method === "log_only"
            ? "It calls a language model, so it needs an API key where EvidenceOps runs."
            : "It runs locally and needs no API key."}
        </p>
        <button
          onClick={investigate}
          disabled={job.busy}
          className="mt-6 rounded-full px-6 py-3 text-[13px] font-medium uppercase transition-colors duration-300 enabled:hover:bg-[#ff7a2f] disabled:opacity-50"
          style={{ background: T.ember, color: T.cream }}
        >
          {job.busy ? "Investigating…" : `Investigate with ${methodLabel(method)}`}
        </button>
        {job.progress.length > 0 && (
          <ol className="mt-6 space-y-1 font-mono text-[12px]">
            {job.progress.map((p, i) => (
              <li key={i} className="animate-[rowIn_500ms_cubic-bezier(.2,.8,.2,1)_both]" style={{ color: T.drift }}>
                <span style={{ color: T.saffron }}>✓</span> {p}
              </li>
            ))}
          </ol>
        )}
        {job.error && <p className="mt-4 text-[13px]" style={{ color: T.flame }}>{job.error}</p>}
      </div>
    );
  }
  if (!report.data) return <div className="h-60 animate-pulse rounded-3xl" style={{ background: T.raised }} />;
  return <ReportView report={report.data} />;
}

function ReportView({ report }: { report: Report }) {
  const [focus, setFocus] = useState<string | null>(null);
  const ids = Object.keys(report.evidence);

  const jump = (id: string) => {
    const el = document.getElementById(`ev-${id}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    gsap.fromTo(el, { boxShadow: `0 0 0 2px ${T.ember}` }, { boxShadow: "0 0 0 0px rgba(220,80,0,0)", duration: 1.6, ease: "power2.out" });
  };

  return (
    <div className="grid gap-12 xl:grid-cols-[1.25fr_1fr]">
      <div>
        <div className="flex flex-wrap gap-x-8 gap-y-2 font-mono text-[12px] uppercase" style={{ color: T.drift }}>
          <span>{report.tool_calls} tool calls</span>
          <span>{report.elapsed_seconds.toFixed(1)} s</span>
          <span>${report.cost_usd.toFixed(3)}</span>
        </div>

        {report.abstained && (
          <div className="mt-8 rounded-[24px] border p-6" style={{ borderColor: T.saffron, background: "rgba(255,184,41,0.06)" }}>
            <div className="text-[12px] font-medium uppercase" style={{ color: T.saffron }}>Abstained</div>
            <p className="mt-3 font-serif text-[24px] italic leading-snug">{report.abstain_reason}</p>
          </div>
        )}

        <ol className="mt-8 space-y-10">
          {report.hypotheses.map((h, i) => (
            <li key={h.category + i} className="grid grid-cols-[56px_1fr] gap-4">
              <span className="font-serif text-[56px] italic leading-[0.8]" style={{ color: i === 0 && !report.abstained ? T.ember : T.drift }}>
                {i + 1}
              </span>
              <div>
                <div className="flex flex-wrap items-baseline justify-between gap-3">
                  <span className="text-[22px] font-medium uppercase leading-none">{label(h.category)}</span>
                  <span className="font-mono text-[12px]" style={{ color: T.drift }}>{Math.round(h.confidence * 100)}% confident</span>
                </div>
                <div className="mt-3 h-[3px] w-full overflow-hidden rounded-full" style={{ background: "rgba(255,237,215,0.07)" }}>
                  <div className="h-full origin-left rounded-full" style={{ width: `${h.confidence * 100}%`, background: i === 0 ? T.ember : T.drift }} />
                </div>
                <p className="mt-4 text-[17px] leading-relaxed">
                  {h.statement}{" "}
                  {h.supporting.map((e) => (
                    <Cite key={e} id={e} onHover={setFocus} onClick={jump} />
                  ))}
                </p>
                {h.refuting.length > 0 && (
                  <p className="mt-2 text-[13px]" style={{ color: T.drift }}>
                    Rules out the others:{" "}
                    {h.refuting.map((e) => (
                      <Cite key={e} id={e} onHover={setFocus} onClick={jump} muted />
                    ))}
                  </p>
                )}
                {h.component && <p className="mt-2 font-mono text-[12px]" style={{ color: T.saffron }}>{h.component}</p>}
              </div>
            </li>
          ))}
        </ol>

        {report.timeline.length > 0 && (
          <div className="mt-14">
            <div className="text-[12px] font-medium uppercase" style={{ color: T.saffron }}>Reconstructed timeline</div>
            <ol className="relative mt-6 border-l pl-6" style={{ borderColor: T.cork }}>
              {report.timeline.map((t, i) => (
                <li key={i} className="relative pb-6">
                  <span className="absolute -left-[29px] top-1.5 h-2 w-2 rounded-full" style={{ background: T.ember }} />
                  <span className="font-mono text-[12px]" style={{ color: T.drift }}>{clock(t.at)}</span>
                  <p className="mt-1 text-[15px]">
                    {t.event}{" "}
                    {t.evidence.map((e) => (
                      <Cite key={e} id={e} onHover={setFocus} onClick={jump} />
                    ))}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>

      <aside className="xl:sticky xl:top-28 xl:max-h-[calc(100vh-8rem)] xl:self-start xl:overflow-y-auto" data-lenis-prevent>
        <div className="text-[12px] font-medium uppercase" style={{ color: T.saffron }}>Evidence · {ids.length} tool calls cited</div>
        <div className="mt-5 space-y-3">
          {ids.map((id) => (
            <EvidenceCard key={id} item={report.evidence[id]} focused={focus === id} />
          ))}
        </div>
      </aside>
    </div>
  );
}

function Cite({ id, onHover, onClick, muted }: { id: string; onHover: (id: string | null) => void; onClick: (id: string) => void; muted?: boolean }) {
  return (
    <button
      type="button"
      onPointerEnter={() => onHover(id)}
      onPointerLeave={() => onHover(null)}
      onFocus={() => onHover(id)}
      onBlur={() => onHover(null)}
      onClick={() => onClick(id)}
      className="mx-0.5 inline-flex -translate-y-[0.35em] items-center rounded-[6px] border px-1.5 font-mono text-[10px] leading-[16px] transition-colors duration-200 hover:bg-[#dc5000] hover:text-[#ffedd7]"
      style={{ borderColor: muted ? T.cork : T.ember, color: muted ? T.drift : T.flame }}
      aria-label={`Evidence ${id}`}
    >
      {id}
    </button>
  );
}

function EvidenceCard({ item, focused }: { item: EvidenceItem; focused: boolean }) {
  const [open, setOpen] = useState(false);
  const finding = (item.result as { finding?: string })?.finding;
  const args = Object.entries(item.args).filter(([k]) => k !== "start" && k !== "end");
  const json = useMemo(() => JSON.stringify(item.result, null, 2), [item.result]);
  return (
    <div
      id={`ev-${item.id}`}
      className="rounded-[20px] border p-5 transition-[border-color,transform,background-color] duration-300"
      style={{
        borderColor: focused ? T.ember : T.cork,
        background: focused ? "rgba(220,80,0,0.08)" : T.raised,
        transform: focused ? "translateX(-6px)" : "none",
      }}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-mono text-[13px]">
          <span style={{ color: T.flame }}>{item.id}</span> {item.tool}
        </span>
        <button onClick={() => setOpen((o) => !o)} className="text-[11px] uppercase underline-offset-4 hover:underline" style={{ color: T.drift }}>
          {open ? "Hide" : "Raw"}
        </button>
      </div>
      {args.length > 0 && (
        <div className="mt-2 font-mono text-[11px]" style={{ color: T.drift }}>
          {args.map(([k, v]) => `${k}=${JSON.stringify(v)}`).join("  ")}
        </div>
      )}
      {finding && <p className="mt-3 text-[14px] leading-relaxed">{finding}</p>}
      {(open || !finding) && (
        <pre className="mt-3 max-h-64 overflow-auto rounded-xl p-3 font-mono text-[11px] leading-relaxed" style={{ background: T.bg, color: "#b5a690" }} data-lenis-prevent>
          {json.length > 4000 ? json.slice(0, 4000) + "\n…" : json}
        </pre>
      )}
    </div>
  );
}

const describe = (c: Change) => {
  switch (c.kind) {
    case "deploy_setting":
      return { what: c.setting, to: String(c.value), verb: "set" };
    case "rollback_setting":
      return { what: c.setting, to: c.value != null ? String(c.value) : "previous value", verb: "roll back" };
    case "dsp_timeout_ms":
      return { what: `timeout for ${(c.dsps ?? []).join(", ")}`, to: `${c.value} ms`, verb: "set" };
    case "rollback_migration":
      return { what: c.migration, to: "down", verb: "roll back migration" };
    case "skip_stuck_message":
      return { what: (c.groups ?? []).join(", "), to: "+1 offset", verb: "skip stuck message in" };
    default:
      return { what: c.kind, to: "", verb: "" };
  }
};

function Remediation({ runId, method, investigated }: { runId: string; method: string; investigated: boolean }) {
  const { source, bump } = useEvidence();
  const loaded = useEvidenceQuery((s) => s.proposal(runId, method), [runId, method, investigated]);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [name, setName] = useState("");
  const [state, setState] = useState<{ busy: string | null; error: string | null; progress: string[] }>({ busy: null, error: null, progress: [] });

  useEffect(() => setProposal(loaded.data), [loaded.data]);
  useEffect(() => setState({ busy: null, error: null, progress: [] }), [method]);

  const act = async (what: string, fn: () => Promise<void>) => {
    setState({ busy: what, error: null, progress: [] });
    try {
      await fn();
      setState((s) => ({ ...s, busy: null }));
    } catch (e) {
      setState((s) => ({ ...s, busy: null, error: e instanceof Error ? e.message : String(e) }));
    }
  };

  const propose = () => act("propose", async () => setProposal(await source.propose(runId, method)));
  const approve = () =>
    act("approve", async () => {
      if (!proposal) return;
      setProposal(await source.approve(runId, method, name, proposal.digest));
    });
  const test = () =>
    act("test", async () => {
      const j = await source.test(runId, method);
      await waitForJob(source, j, (x) => setState((s) => ({ ...s, progress: Array.isArray(x.progress) ? x.progress.map(String) : s.progress })), 900);
      setProposal(await source.proposal(runId, method));
      bump();
    });

  if (!investigated) {
    return <p className="text-[17px]" style={{ color: T.drift }}>Investigate with {methodLabel(method)} first; a fix is built from its top hypothesis.</p>;
  }

  if (!proposal) {
    return (
      <div className="rounded-[28px] border p-8" style={{ borderColor: T.cork, background: T.raised }}>
        <p className="max-w-xl text-[17px] leading-relaxed">
          Turn the {methodLabel(method)} report into a fix. Only typed, allowlisted changes can be proposed (a setting, a
          per-DSP timeout, a migration rollback, skipping a stuck message), so there is nothing free-form to run.
        </p>
        <button onClick={propose} disabled={!!state.busy} className="mt-6 rounded-full px-6 py-3 text-[13px] font-medium uppercase transition-colors duration-300 enabled:hover:bg-[#ff7a2f] disabled:opacity-50" style={{ background: T.ember, color: T.cream }}>
          {state.busy === "propose" ? "Proposing…" : "Propose a fix"}
        </button>
        {state.error && <p className="mt-4 text-[13px]" style={{ color: T.flame }}>{state.error}</p>}
      </div>
    );
  }

  const approved = proposal.status === "approved";
  const result = proposal.result;
  return (
    <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
      <div className="rounded-[28px] border p-8" style={{ borderColor: T.cork, background: T.raised }}>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <span className="text-[12px] font-medium uppercase" style={{ color: T.saffron }}>
            Proposal · {proposal.hypothesis ? label(proposal.hypothesis) : "from an abstention"}
          </span>
          <span className="font-mono text-[11px]" style={{ color: T.drift }} title={proposal.digest}>
            digest {proposal.digest.slice(0, 12)}
          </span>
        </div>
        <ul className="mt-6 space-y-3">
          {proposal.changes.map((c, i) => {
            const d = describe(c);
            return (
              <li key={i} className="flex flex-wrap items-baseline gap-x-3 border-b border-dashed pb-3 font-mono text-[14px]" style={{ borderColor: T.cork }}>
                <span style={{ color: T.drift }}>{d.verb}</span>
                <span>{d.what}</span>
                {d.to && <span style={{ color: T.drift }}>→</span>}
                {d.to && <span style={{ color: T.saffron }}>{d.to}</span>}
              </li>
            );
          })}
        </ul>
        <p className="mt-5 text-[15px] leading-relaxed" style={{ color: "#b5a690" }}>{proposal.rationale}</p>
      </div>

      <div className="flex flex-col gap-6">
        <div className="rounded-[28px] border p-8" style={{ borderColor: approved ? "rgba(255,184,41,0.4)" : T.cork, background: T.raised }}>
          <div className="text-[12px] font-medium uppercase" style={{ color: approved ? T.saffron : T.drift }}>
            {approved ? "Approved" : "Needs a person"}
          </div>
          {approved ? (
            <p className="mt-3 font-serif text-[26px] italic leading-tight">
              {proposal.approved_by}
              <span className="block font-sans text-[12px] not-italic" style={{ color: T.drift }}>
                {proposal.approved_at ? new Date(proposal.approved_at).toLocaleString() : ""} · digest {proposal.digest.slice(0, 12)}
              </span>
            </p>
          ) : (
            <form
              className="mt-4 flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                approve();
              }}
            >
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                className="rounded-full border bg-transparent px-5 py-3 text-[14px] outline-none focus:border-[#dc5000]"
                style={{ borderColor: T.cork, color: T.cream }}
              />
              <button
                disabled={!name.trim() || !!state.busy}
                className="rounded-full px-6 py-3 text-[13px] font-medium uppercase transition-colors duration-300 enabled:hover:bg-[#ff7a2f] disabled:opacity-40"
                style={{ background: T.ember, color: T.cream }}
              >
                {state.busy === "approve" ? "Approving…" : "Approve this exact proposal"}
              </button>
              <span className="text-[12px]" style={{ color: T.drift }}>
                Approval is pinned to digest {proposal.digest.slice(0, 12)}. If the proposal changes, it has to be approved again.
              </span>
            </form>
          )}
        </div>

        <div className="rounded-[28px] border p-8" style={{ borderColor: T.cork, background: T.raised }}>
          <div className="text-[12px] font-medium uppercase" style={{ color: T.drift }}>Sandbox test</div>
          {result ? (
            <Verdict result={result} />
          ) : (
            <>
              <p className="mt-3 text-[15px] leading-relaxed">
                Replays the incident in a disposable copy of the platform, applies the fix, and checks it recovers.
              </p>
              <button
                onClick={test}
                disabled={!approved || !!state.busy}
                className="mt-5 rounded-full border px-6 py-3 text-[13px] font-medium uppercase transition-colors duration-300 enabled:hover:bg-[#ffedd7] enabled:hover:text-[#100904] disabled:opacity-40"
                style={{ borderColor: T.cream }}
              >
                {state.busy === "test" ? "Testing…" : approved ? "Test in sandbox" : "Approve first"}
              </button>
            </>
          )}
          {state.progress.length > 0 && !result && (
            <ol className="mt-5 space-y-1 font-mono text-[12px]">
              {state.progress.map((p, i) => (
                <li key={i} style={{ color: T.drift }}><span style={{ color: T.saffron }}>✓</span> {p}</li>
              ))}
            </ol>
          )}
          {state.error && <p className="mt-4 text-[13px]" style={{ color: T.flame }}>{state.error}</p>}
        </div>
      </div>
    </div>
  );
}

function Verdict({ result }: { result: NonNullable<Proposal["result"]> }) {
  const success = result.baseline_success_rate != null || result.recovered_success_rate != null;
  const fmt = (v: number | null | undefined) => (v == null ? "–" : success ? `${(v * 100).toFixed(0)}%` : String(v));
  const cells = success
    ? [["Before", result.baseline_success_rate], ["Incident", result.incident_success_rate], ["After fix", result.recovered_success_rate]]
    : [["Before", result.baseline_analytics_drift], ["Incident", result.incident_analytics_drift], ["After fix", result.recovered_analytics_drift]];
  const ok = result.verdict === "verified";
  return (
    <div className="mt-3">
      <div className="flex items-center gap-3">
        <Mark ok={ok} size={18} />
        <span className="font-serif text-[34px] italic leading-none" style={{ color: ok ? T.saffron : T.flame }}>
          {ok ? "Fix verified" : result.verdict === "not_fixed" ? "Didn't fix it" : "Inconclusive"}
        </span>
      </div>
      <div className="mt-5 grid grid-cols-3 gap-3">
        {cells.map(([k, v]) => (
          <div key={k as string}>
            <div className="text-[11px] uppercase" style={{ color: T.drift }}>{k}</div>
            <div className="mt-1 font-mono text-[20px]">{fmt(v as number | null)}</div>
          </div>
        ))}
      </div>
      {"sample" in result && <p className="mt-4 text-[12px]" style={{ color: T.drift }}>Simulated in demo mode; no sandbox was started.</p>}
    </div>
  );
}

function AnswerKey({ runId }: { runId: string }) {
  const [shown, setShown] = useState(false);
  const grading = useEvidenceQuery((s) => (shown ? s.grading(runId) : Promise.resolve(null)), [runId, shown]);
  if (!shown) {
    return (
      <div>
        <p className="max-w-xl text-[17px] leading-relaxed" style={{ color: T.drift }}>
          The recorded cause, kept away from every investigator. Look only after you&apos;ve read the report.
        </p>
        <button
          onClick={() => setShown(true)}
          className="mt-6 rounded-full border px-6 py-3 text-[13px] font-medium uppercase transition-colors duration-300 hover:bg-[#ffedd7] hover:text-[#100904]"
          style={{ borderColor: T.cream }}
        >
          Reveal the answer key
        </button>
      </div>
    );
  }
  if (grading.error) return <p style={{ color: T.flame }}>{grading.error.message}</p>;
  const g = grading.data;
  if (!g) return <div className="h-40 animate-pulse rounded-3xl" style={{ background: T.raised }} />;
  const gt = g.ground_truth;
  return (
    <div className="grid gap-10 lg:grid-cols-[1.2fr_1fr]">
      <div>
        <div className="text-[12px] font-medium uppercase" style={{ color: T.saffron }}>{gt.ambiguous ? "Ambiguous on purpose" : "True cause"}</div>
        <div className="mt-3 text-[36px] font-medium uppercase leading-none">
          {gt.ambiguous ? (gt.candidates ?? []).map(label).join(" or ") : label(gt.category)}
        </div>
        {gt.component && <div className="mt-3 font-mono text-[13px]" style={{ color: T.saffron }}>{gt.component}</div>}
        {gt.summary && <p className="mt-5 text-[16px] leading-relaxed">{gt.summary}</p>}
        {gt.distinguishing_evidence && (
          <ul className="mt-6 space-y-2 text-[14px]" style={{ color: "#b5a690" }}>
            {gt.distinguishing_evidence.map((e) => (
              <li key={e} className="flex gap-3"><span style={{ color: T.ember }}>—</span>{e}</li>
            ))}
          </ul>
        )}
      </div>
      <div className="space-y-3">
        {g.grades.map((x) => {
          const ok = x.correct_abstention ?? x.top1_correct;
          return (
            <div key={x.method} className="flex items-center justify-between gap-4 rounded-[20px] border px-5 py-4" style={{ borderColor: T.cork, background: T.raised }}>
              <span>
                <span className="block text-[11px] uppercase" style={{ color: T.drift }}>{methodLabel(x.method)}</span>
                <span className="mt-1 block text-[15px] uppercase">{x.abstained ? "Abstained" : label(x.predicted)}</span>
              </span>
              <Mark ok={!!ok} size={20} />
            </div>
          );
        })}
      </div>
    </div>
  );
}
