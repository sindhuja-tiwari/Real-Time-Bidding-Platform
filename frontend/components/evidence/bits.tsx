"use client";

import { EVIDENCE_URL, useEvidence } from "@/lib/evidence";
import { T } from "@/lib/theme";

/** Says where the incident data comes from, and how to switch to live. */
export function SourceBanner() {
  const { live } = useEvidence();
  if (live === null) return null;
  return (
    <div
      className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-2xl border px-5 py-4 text-[13px]"
      style={{ borderColor: live ? "rgba(255,184,41,0.35)" : T.cork, background: live ? "rgba(255,184,41,0.06)" : T.raised }}
    >
      <span className="flex items-center gap-2 font-medium uppercase">
        <span className="h-2 w-2 rounded-full" style={{ background: live ? T.saffron : T.drift }} />
        {live ? "Live EvidenceOps" : "Demo data"}
      </span>
      <span style={{ color: T.drift }}>
        {live ? (
          <>Connected to <span className="font-mono">{EVIDENCE_URL}</span>. Runs, reports and approvals are real.</>
        ) : (
          <>
            The scenarios and suite results are real; the five case files are samples built from each scenario&apos;s ground
            truth. Start the API with <span className="font-mono" style={{ color: T.cream }}>python -m evidenceops serve</span> to
            use your own runs.
          </>
        )}
      </span>
    </div>
  );
}

/** A tick or a cross, drawn rather than typed. */
export function Mark({ ok, size = 14 }: { ok: boolean; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" aria-label={ok ? "correct" : "wrong"} role="img">
      {ok ? (
        <path d="M2 7.5 5.5 11 12 3" fill="none" stroke={T.saffron} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      ) : (
        <path d="M3 3l8 8M11 3l-8 8" fill="none" stroke={T.flame} strokeWidth="2" strokeLinecap="round" />
      )}
    </svg>
  );
}
