"use client";

import type { Bid } from "@/lib/api";
import StatusMark from "@/components/reactbits/StatusMark";
import { COLORS, prettyStatus } from "./primitives";

const SCALE_MS = 120; // the track shows 0–120 ms, so the 100 ms deadline sits at 83%
const DEADLINE_MS = 100;

const markFor = (status: string) =>
  status === "WON" ? "done" : status === "TIMEOUT" || status === "INVALID" ? "failed" : "cancelled";

/**
 * One lane per DSP. Bars grow to each DSP's response time, staggered by that
 * time, so the bids appear to land in the order they arrived.
 */
export function DspRace({ names, bids, running }: { names: string[]; bids: Bid[] | null; running: boolean }) {
  const byName = new Map((bids ?? []).map((b) => [b.dsp_name ?? b.dsp_id, b]));
  const lanes = names.length ? names : [...byName.keys()];
  const deadlinePct = (DEADLINE_MS / SCALE_MS) * 100;

  return (
    <div className="space-y-3">
      {lanes.map((name) => {
        const bid = running ? undefined : byName.get(name);
        const rt = bid ? (bid.response_time_ms ?? DEADLINE_MS) : 0;
        const pct = bid ? Math.min(100, (rt / SCALE_MS) * 100) : 0;
        const won = bid?.status === "WON";
        const timedOut = bid?.status === "TIMEOUT";
        const barColor = won ? COLORS.accent : timedOut ? COLORS.rose : "rgba(161,161,170,0.45)";

        return (
          <div key={name} className="grid grid-cols-[88px_1fr_120px] items-center gap-4">
            <div className="flex items-center gap-2.5">
              <StatusMark
                status={running ? "running" : bid ? markFor(bid.status) : "pending"}
                size={14}
                color={COLORS.muted}
                doneColor={COLORS.accent}
                errorColor={COLORS.rose}
              />
              <span className={`font-mono text-[13px] ${won ? "text-zinc-100" : "text-zinc-400"}`}>{name}</span>
            </div>

            <div className="relative h-8 overflow-hidden rounded-lg bg-white/[0.03]">
              {running && (
                <div className="absolute inset-y-0 left-0 w-1/3 animate-[lane_1.1s_ease-in-out_infinite] bg-gradient-to-r from-transparent via-accent/25 to-transparent" />
              )}
              <div
                className="absolute inset-y-1 left-1 rounded-md transition-[width,background-color,box-shadow] ease-[cubic-bezier(.2,.8,.2,1)]"
                style={{
                  width: `calc(${pct}% - 8px)`,
                  minWidth: bid ? 6 : 0,
                  backgroundColor: barColor,
                  boxShadow: won ? "0 0 24px rgba(220,80,0,0.45)" : "none",
                  transitionDuration: "700ms",
                  transitionDelay: `${Math.round(rt * 6)}ms`,
                  backgroundImage: timedOut
                    ? "repeating-linear-gradient(135deg, transparent 0 6px, rgba(0,0,0,0.25) 6px 12px)"
                    : undefined,
                }}
              />
              <div
                className="absolute inset-y-0 border-l border-dashed border-rose/50"
                style={{ left: `${deadlinePct}%` }}
                title="100 ms deadline"
              />
              {bid && (
                <span className="absolute inset-y-0 right-2 flex items-center font-mono text-[11px] text-zinc-500">
                  {bid.response_time_ms != null ? `${bid.response_time_ms} ms` : "no reply"}
                </span>
              )}
            </div>

            <div className="text-right">
              {bid ? (
                <>
                  <div className={`num font-mono text-sm ${won ? "text-zinc-100" : "text-zinc-400"}`}>
                    {bid.amount > 0 ? `$${bid.amount.toFixed(2)}` : "–"}
                  </div>
                  <div className={`text-[11px] ${won ? "text-accent" : timedOut ? "text-rose/80" : "text-zinc-600"}`}>
                    {prettyStatus(bid.status)}
                  </div>
                </>
              ) : (
                <div className="text-[11px] text-zinc-600">{running ? "bidding…" : "waiting"}</div>
              )}
            </div>
          </div>
        );
      })}
      <div className="grid grid-cols-[88px_1fr_120px] gap-4 text-[10px] text-zinc-600">
        <span />
        <div className="relative h-3">
          <span className="absolute left-0">0 ms</span>
          <span className="absolute -translate-x-1/2 text-rose/70" style={{ left: `${deadlinePct}%` }}>
            100 ms deadline
          </span>
        </div>
        <span />
      </div>
    </div>
  );
}
