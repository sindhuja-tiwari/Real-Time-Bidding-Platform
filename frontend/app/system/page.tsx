"use client";

import { useState } from "react";
import { useData, useQuery } from "@/lib/data";
import { PageHeader, Panel } from "@/components/ui/primitives";
import { DashRule } from "@/components/motion/DashRule";
import { Reveal } from "@/components/motion/Reveal";
import { T } from "@/lib/theme";
import { EVIDENCE_URL, useEvidence } from "@/lib/evidence";
import Link from "next/link";

const LINKS = [
  { name: "API docs", note: "OpenAPI, FastAPI", href: "http://localhost:8000/api/v1/docs" },
  { name: "Grafana", note: "admin / admin", href: "http://localhost:3001" },
  { name: "Prometheus", note: "raw metrics", href: "http://localhost:9090" },
  { name: "DSP simulator", note: "admin endpoints", href: "http://localhost:9000/admin/dsps" },
];

export default function SystemPage() {
  const { backendUp, isDemo, preference, setPreference, adSlotId, setAdSlotId, apiBaseUrl } = useData();
  const health = useQuery((s) => s.health());
  const [slot, setSlot] = useState(adSlotId);

  const state = backendUp === null ? "Checking" : backendUp ? "Reachable" : "Offline";

  return (
    <div>
      <PageHeader kicker="System · Wiring and observability" title="What the engine is *talking* to.">
        The UI calls the backend at <span className="font-mono" style={{ color: T.cream }}>{apiBaseUrl}</span>. When it
        can&apos;t reach it, auctions run in an in-browser simulation that follows the same rules.
      </PageHeader>

      <div className="grid gap-5 lg:grid-cols-3">
        <Panel>
          <div className="label">Backend</div>
          <div className="mt-5 text-[40px] font-medium uppercase leading-none" style={{ color: backendUp ? T.saffron : T.cream }}>
            {state}
          </div>
          <p className="mt-4 text-sm" style={{ color: T.drift }}>
            {health.data ? `${health.data.service} · ${health.data.env}` : health.error ?? "…"}
          </p>
        </Panel>

        <Panel delay={0.08}>
          <div className="label">Data source</div>
          <div className="mt-5 flex gap-2">
            {(["auto", "live", "demo"] as const).map((p) => (
              <button
                key={p}
                onClick={() => setPreference(p)}
                className="rounded-full border px-4 py-2 text-[13px] uppercase transition-colors duration-300"
                style={{
                  borderColor: preference === p ? T.ember : T.cork,
                  background: preference === p ? T.ember : "transparent",
                  color: T.cream,
                }}
              >
                {p}
              </button>
            ))}
          </div>
          <p className="mt-4 text-sm" style={{ color: T.drift }}>
            Serving from {isDemo ? "the simulation" : "the live backend"}. Auto picks live when it&apos;s up.
          </p>
        </Panel>

        <Panel delay={0.16}>
          <div className="label">Ad slot for live auctions</div>
          <form
            className="mt-5 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setAdSlotId(slot.trim());
            }}
          >
            <input
              value={slot}
              onChange={(e) => setSlot(e.target.value)}
              placeholder="ad slot UUID from seed.py"
              className="min-w-0 flex-1 rounded-full border bg-transparent px-4 py-2 font-mono text-[12px] outline-none transition-colors focus:border-[#dc5000]"
              style={{ borderColor: T.cork, color: T.cream }}
            />
            <button className="rounded-full px-4 py-2 text-[13px] uppercase" style={{ background: T.bark, color: T.cream }}>
              Save
            </button>
          </form>
          <p className="mt-4 text-sm" style={{ color: T.drift }}>
            Printed by <span className="font-mono">python -m app.seed</span>. Not needed in demo mode.
          </p>
        </Panel>
      </div>

      <EvidenceOpsPanel />

      <section className="mt-24">
        <Reveal>
          <div className="label">Observability</div>
        </Reveal>
        <DashRule className="mt-5" />
        {LINKS.map((l, i) => (
          <Reveal key={l.href} delay={i * 0.06} y={30}>
            <a
              href={l.href}
              target="_blank"
              rel="noreferrer"
              className="group relative flex items-baseline justify-between overflow-hidden border-b border-dashed py-7"
              style={{ borderColor: T.cork }}
            >
              <span className="absolute inset-0 origin-bottom scale-y-0 transition-transform duration-500 ease-[cubic-bezier(.7,0,.2,1)] group-hover:scale-y-100" style={{ background: T.ember }} />
              <span className="relative text-[32px] font-medium uppercase leading-none transition-transform duration-500 ease-[cubic-bezier(.2,.8,.2,1)] group-hover:translate-x-4 md:text-[56px]">
                {l.name}
              </span>
              <span className="relative flex items-center gap-6 text-sm" style={{ color: T.cream }}>
                <span className="opacity-60">{l.note}</span>
                <span className="text-2xl transition-transform duration-500 group-hover:-rotate-45">→</span>
              </span>
            </a>
          </Reveal>
        ))}
      </section>

      <section className="mt-24 grid gap-10 lg:grid-cols-[1fr_1.4fr] [&>*]:min-w-0">
        <Reveal>
          <div className="label">Break something on purpose</div>
          <p className="mt-5 text-[28px] font-medium uppercase leading-[1.02]">
            Slow one DSP down and watch the auction shrug it off.
          </p>
          <p className="mt-5 max-w-md text-sm leading-relaxed" style={{ color: T.drift }}>
            Push DSP-C past the deadline at runtime. Its timeouts climb on the Field page and in Grafana, while every
            auction still closes inside 100 ms.
          </p>
        </Reveal>
        <Reveal delay={0.1}>
          <pre className="overflow-x-auto rounded-[28px] border p-7 font-mono text-[12px] leading-relaxed" style={{ borderColor: T.cork, background: T.raised, color: "#b5a690" }}>
{`curl -X POST http://localhost:9000/admin/dsps/dsp-c \\
  -H "Content-Type: application/json" \\
  -d '{"campaign_id": "<campaign-id>",
       "base_bid": 4.1,
       "latency_ms": 150,
       "timeout_probability": 0.9}'`}
          </pre>
        </Reveal>
      </section>
    </div>
  );
}

/** Where the incident investigator lives, whether it answers, and its token. */
function EvidenceOpsPanel() {
  const { live, token, setToken } = useEvidence();
  const [draft, setDraft] = useState<string | null>(null);
  const value = draft ?? token;
  const state = live === null ? "Checking" : live ? "Reachable" : "Offline";
  return (
    <div className="mt-5">
      <Panel delay={0.2}>
        <div className="grid gap-8 lg:grid-cols-[1fr_1.3fr] lg:items-end">
          <div>
            <div className="label">EvidenceOps investigator</div>
            <div className="mt-5 text-[40px] font-medium uppercase leading-none" style={{ color: live ? T.saffron : T.cream }}>
              {state}
            </div>
            <p className="mt-4 text-sm" style={{ color: T.drift }}>
              Calls <span className="font-mono" style={{ color: T.cream }}>{EVIDENCE_URL}</span>.{" "}
              {live ? (
                <>
                  <Link href="/incidents" className="underline decoration-dashed underline-offset-4 hover:text-[#ffedd7]">
                    Incidents
                  </Link>{" "}
                  is reading real runs.
                </>
              ) : (
                <>
                  Start it with <span className="font-mono" style={{ color: T.cream }}>python -m evidenceops serve</span>; until
                  then Incidents shows sample runs.
                </>
              )}
            </p>
          </div>
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              setToken(value.trim());
              setDraft(null);
            }}
          >
            <span className="text-xs" style={{ color: T.drift }}>
              API token, only if the server sets <span className="font-mono">EVIDENCEOPS_API_TOKEN</span>. Kept in this browser.
            </span>
            <div className="flex gap-2">
              <input
                type="password"
                value={value}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="no token"
                autoComplete="off"
                className="min-w-0 flex-1 rounded-full border bg-transparent px-4 py-2 font-mono text-[12px] outline-none transition-colors focus:border-[#dc5000]"
                style={{ borderColor: T.cork, color: T.cream }}
              />
              <button className="rounded-full px-4 py-2 text-[13px] uppercase transition-transform active:scale-95" style={{ background: T.bark, color: T.cream }}>
                {draft != null && draft !== token ? "Save" : "Saved"}
              </button>
            </div>
          </form>
        </div>
      </Panel>
    </div>
  );
}
