"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/ui/primitives";
import { Reveal } from "@/components/motion/Reveal";
import { DashRule } from "@/components/motion/DashRule";
import { Spark } from "@/components/evidence/AlertChart";
import { SourceBanner, Mark } from "@/components/evidence/bits";
import {
  label,
  methodLabel,
  scenarioOf,
  useEvidence,
  useEvidenceQuery,
  waitForJob,
  type ResultRow,
  type RunDetail,
} from "@/lib/evidence";
import { T } from "@/lib/theme";

export default function IncidentsPage() {
  const runs = useEvidenceQuery(async (s) => {
    const list = await s.runs();
    // Newest first, with detail for the sparkline.
    return Promise.all(list.slice().reverse().map((r) => s.run(r.run_id)));
  });
  const results = useEvidenceQuery((s) => s.results());
  const scenarios = useEvidenceQuery((s) => s.scenarios());
  const [key, setKey] = useState(false);

  return (
    <div>
      <PageHeader kicker="EvidenceOps · Incident investigator" title="Every outage has a *cause.* Prove it.">
        EvidenceOps breaks this platform on purpose, records everything, and has investigators find the cause from the
        evidence alone. Every claim cites a tool call. Fixes are proposed, approved by a person, and tested in a
        throwaway copy of the platform, never the live one.
      </PageHeader>

      <SourceBanner />

      <section className="mt-16">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <Reveal>
            <h2 className="text-[34px] font-medium uppercase leading-none md:text-[48px]">
              Case <span className="accent-serif">files</span>
            </h2>
          </Reveal>
          <button
            onClick={() => setKey((k) => !k)}
            aria-pressed={key}
            className="group flex items-center gap-3 rounded-full border px-5 py-2.5 text-[12px] font-medium uppercase transition-colors duration-300"
            style={{ borderColor: key ? T.ember : T.cork, background: key ? "rgba(220,80,0,0.12)" : "transparent" }}
          >
            <span className="relative h-4 w-7 rounded-full transition-colors" style={{ background: key ? T.ember : T.bark }}>
              <span
                className="absolute top-0.5 h-3 w-3 rounded-full bg-[#ffedd7] transition-transform duration-300"
                style={{ transform: `translateX(${key ? 14 : 2}px)` }}
              />
            </span>
            Answer key {key ? "shown" : "hidden"}
          </button>
        </div>
        <DashRule className="mt-6" />

        {runs.error && <p className="py-10 text-sm" style={{ color: T.flame }}>{runs.error.message}</p>}
        {runs.data?.length === 0 && (
          <p className="py-10 text-[15px]" style={{ color: T.drift }}>
            No recorded incidents yet. Record one below, or run <code className="font-mono">python -m evidenceops run --all</code>.
          </p>
        )}
        {(runs.data ?? []).map((r, i) => (
          <CaseRow key={r.run_id} run={r} index={i} showKey={key} result={results.data?.find((x) => x.scenario_id === scenarioOf(r.run_id))} />
        ))}
        {runs.loading && <div className="h-40 animate-pulse rounded-3xl" style={{ background: T.raised }} />}
      </section>

      <RecordIncident scenarios={scenarios.data ?? []} />

      {results.data && <Scoreboard rows={results.data} />}
    </div>
  );
}

function CaseRow({ run, index, showKey, result }: { run: RunDetail; index: number; showKey: boolean; result?: ResultRow }) {
  const { live } = useEvidence();
  const methods = Object.entries(run.investigations);
  const sid = scenarioOf(run.run_id);
  return (
    <Reveal delay={index * 0.05} y={30}>
      <Link
        href={`/incidents/${run.run_id}`}
        className="group relative grid grid-cols-1 items-center gap-4 overflow-hidden border-b border-dashed py-8 md:grid-cols-[90px_1.5fr_180px_1.2fr_40px]"
        style={{ borderColor: T.cork }}
      >
        <span
          className="absolute inset-0 origin-left scale-x-0 transition-transform duration-700 ease-[cubic-bezier(.7,0,.2,1)] group-hover:scale-x-100"
          style={{ background: "linear-gradient(90deg, rgba(220,80,0,0.14), rgba(220,80,0,0))" }}
        />
        <span className="relative font-serif text-[44px] italic leading-none" style={{ color: T.drift }}>
          {String(index + 1).padStart(2, "0")}
        </span>
        <span className="relative">
          <span className="block font-mono text-[11px] uppercase" style={{ color: T.drift }}>
            {run.incident_id} · {sid.slice(0, 3)}
          </span>
          <span className="mt-2 block text-[20px] font-medium uppercase leading-[1.05] transition-transform duration-500 group-hover:translate-x-2 md:text-[24px]">
            {result?.title ?? sid.replace(/^s\d\d-/, "").replace(/-/g, " ")}
          </span>
        </span>
        <span className="relative flex flex-col gap-1">
          <Spark incident={run.incident} />
          <span className="font-mono text-[11px]" style={{ color: T.drift }}>
            {run.alert_metric === "auction_success_rate" ? "success rate" : "analytics drift"}
            {!live && result ? ` · ${result.measured}` : ""}
          </span>
        </span>
        <span className="relative flex flex-wrap gap-2">
          {methods.length === 0 && <span className="text-[12px] uppercase" style={{ color: T.drift }}>Not investigated yet</span>}
          {methods.map(([m, v]) => {
            const truth = result?.truth;
            const correct = v.abstained ? truth?.startsWith("ambiguous") : v.top === truth;
            return (
              <span key={m} className="flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] uppercase" style={{ borderColor: T.cork }}>
                <span style={{ color: T.drift }}>{methodLabel(m)}</span>
                <span>{v.abstained ? "Abstained" : label(v.top)}</span>
                {showKey && truth && <Mark ok={!!correct} />}
              </span>
            );
          })}
        </span>
        <span className="relative hidden text-2xl transition-transform duration-500 group-hover:translate-x-1 group-hover:-rotate-45 md:block">→</span>
      </Link>
    </Reveal>
  );
}

function RecordIncident({ scenarios }: { scenarios: { id: string; title: string; ambiguous: boolean }[] }) {
  const { source, live, bump } = useEvidence();
  const [pick, setPick] = useState("s03-db-pool-exhaustion");
  const [state, setState] = useState<{ busy: boolean; note: string | null; error: string | null }>({ busy: false, note: null, error: null });

  const record = async () => {
    setState({ busy: true, note: "Queued", error: null });
    try {
      const job = await source.record([pick], true);
      await waitForJob(source, job, (j) => setState((s) => ({ ...s, note: `${j.status}…` })), 5000);
      setState({ busy: false, note: "Recorded. It's at the top of the list.", error: null });
      bump();
    } catch (e) {
      setState({ busy: false, note: null, error: e instanceof Error ? e.message : String(e) });
    }
  };

  return (
    <section className="mt-24 grid gap-10 lg:grid-cols-[1fr_1.2fr]">
      <Reveal>
        <div className="text-[12px] font-medium uppercase" style={{ color: T.saffron }}>Break it on purpose</div>
        <p className="mt-5 text-[30px] font-medium uppercase leading-[1.02] md:text-[38px]">
          Pick a failure. EvidenceOps injects it and <span className="accent-serif">records</span> the fallout.
        </p>
        <p className="mt-5 max-w-md text-[15px] leading-relaxed" style={{ color: T.drift }}>
          A recording resets the platform, drives open-loop traffic, fires the scenario&apos;s steps (decoys included)
          and captures logs, traces, database samples and metrics. About three minutes in quick mode.
        </p>
      </Reveal>
      <Reveal delay={0.1}>
        <div className="rounded-[28px] border p-7" style={{ borderColor: T.cork, background: T.raised }}>
          <label className="text-[12px] font-medium uppercase" style={{ color: T.drift }} htmlFor="scenario">
            Scenario
          </label>
          <select
            id="scenario"
            value={pick}
            onChange={(e) => setPick(e.target.value)}
            className="mt-3 w-full appearance-none rounded-2xl border bg-transparent px-4 py-3 font-mono text-[13px] outline-none focus:border-[#dc5000]"
            style={{ borderColor: T.cork, color: T.cream }}
          >
            {scenarios.map((s) => (
              <option key={s.id} value={s.id} style={{ background: T.raised }}>
                {s.id} {s.ambiguous ? "(ambiguous)" : ""}
              </option>
            ))}
          </select>
          <p className="mt-3 min-h-[40px] text-[14px]" style={{ color: T.cream }}>
            {scenarios.find((s) => s.id === pick)?.title}
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-4">
            <button
              onClick={record}
              disabled={state.busy || !live}
              className="rounded-full px-6 py-3 text-[13px] font-medium uppercase transition-colors duration-300 enabled:hover:bg-[#ff7a2f] disabled:cursor-not-allowed disabled:opacity-40"
              style={{ background: T.ember, color: T.cream }}
            >
              {state.busy ? "Recording…" : "Record incident"}
            </button>
            <span className="text-[13px]" style={{ color: state.error ? T.flame : T.drift }}>
              {state.error ?? state.note ?? (live ? "Needs Docker on the machine running EvidenceOps." : "Needs the live EvidenceOps API and Docker.")}
            </span>
          </div>
        </div>
      </Reveal>
    </section>
  );
}

function Scoreboard({ rows }: { rows: ResultRow[] }) {
  const stats = useMemo(() => {
    const clear = rows.filter((r) => !r.truth.startsWith("ambiguous"));
    const amb = rows.filter((r) => r.truth.startsWith("ambiguous"));
    const score = (m: "fixed_workflow" | "agent_offline") => ({
      clear: clear.filter((r) => r[m].correct).length,
      amb: amb.filter((r) => r[m].correct).length,
    });
    return { clear: clear.length, amb: amb.length, fixed: score("fixed_workflow"), agent: score("agent_offline") };
  }, [rows]);

  return (
    <section className="mt-28">
      <Reveal>
        <div className="text-[12px] font-medium uppercase" style={{ color: T.saffron }}>Measured across the whole suite</div>
        <h2 className="mt-4 max-w-[18ch] text-[34px] font-medium uppercase leading-[0.95] md:text-[56px]">
          22 incidents. Two investigators. <span className="accent-serif">One</span> gets them all.
        </h2>
      </Reveal>

      <div className="mt-12 grid gap-px overflow-hidden rounded-[28px] border md:grid-cols-2" style={{ borderColor: T.cork, background: T.cork }}>
        {([["fixed_workflow", stats.fixed], ["agent_offline", stats.agent]] as const).map(([m, s]) => (
          <div key={m} className="p-8" style={{ background: T.bg }}>
            <div className="text-[12px] font-medium uppercase" style={{ color: T.drift }}>{methodLabel(m)}</div>
            <div className="mt-4 flex items-baseline gap-3">
              <span className="font-serif text-[96px] italic leading-[0.8]" style={{ color: m === "agent_offline" ? T.flame : T.cream }}>
                {s.clear}
              </span>
              <span className="font-serif text-[40px] italic leading-none" style={{ color: T.drift }}>/ {stats.clear}</span>
            </div>
            <div className="mt-3 text-[14px]" style={{ color: T.drift }}>
              clear-cut causes named first · abstained correctly on {s.amb} of {stats.amb} ambiguous
            </div>
            <div className="mt-6 flex gap-[3px]">
              {rows.map((r) => (
                <span
                  key={r.scenario_id}
                  title={`${r.scenario_id}: ${r[m].abstained ? "abstained" : label(r[m].answer)}`}
                  className="h-7 flex-1 rounded-[3px]"
                  style={{ background: r[m].correct ? (m === "agent_offline" ? T.ember : T.saffron) : "rgba(255,237,215,0.08)" }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-10 overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-[13px]">
          <thead>
            <tr className="text-left text-[11px] uppercase" style={{ color: T.drift }}>
              <th className="py-3 pr-4 font-medium">Scenario</th>
              <th className="py-3 pr-4 font-medium">True cause</th>
              <th className="py-3 pr-4 font-medium">Measured</th>
              <th className="py-3 pr-4 font-medium">Fixed workflow</th>
              <th className="py-3 font-medium">Agent</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.scenario_id} className="border-t border-dashed transition-colors hover:bg-[rgba(56,36,22,0.45)]" style={{ borderColor: T.cork }}>
                <td className="py-3 pr-4">
                  <span className="font-mono text-[11px]" style={{ color: T.drift }}>{r.scenario_id.slice(0, 3)}</span>{" "}
                  {r.title}
                </td>
                <td className="py-3 pr-4 uppercase">{r.truth.startsWith("ambiguous") ? "Ambiguous" : label(r.truth)}</td>
                <td className="py-3 pr-4 font-mono">{r.measured}</td>
                <td className="py-3 pr-4"><Answer a={r.fixed_workflow} /></td>
                <td className="py-3"><Answer a={r.agent_offline} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-4 text-[12px]" style={{ color: T.drift }}>
          One recorded run of every scenario on a 4-core Linux machine, from the EvidenceOps README. &ldquo;Agent&rdquo; is the
          offline policy, which needs no API key.
        </p>
      </div>
    </section>
  );
}

function Answer({ a }: { a: { answer: string | null; abstained: boolean; correct: boolean } }) {
  return (
    <span className="flex items-center gap-2 uppercase">
      <Mark ok={a.correct} />
      {a.abstained ? "Abstained" : label(a.answer)}
    </span>
  );
}
