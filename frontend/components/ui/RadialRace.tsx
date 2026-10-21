"use client";

import type { Bid } from "@/lib/api";

export interface RadialTheme {
  ring: string;
  deadline: string;
  dot: string;
  winner: string;
  timeout: string;
  label: string;
  muted: string;
  font?: string;
}

const SCALE_MS = 125;

/**
 * Each DSP sits on its own spoke. Its distance from the centre is how long it
 * took to answer, so anything past the dashed ring missed the 100 ms deadline.
 */
export function RadialRace({
  bids,
  size = 520,
  theme,
  uppercase = false,
}: {
  bids: Bid[];
  size?: number;
  theme: RadialTheme;
  uppercase?: boolean;
}) {
  const c = size / 2;
  const R = size / 2 - 56;
  const r = (ms: number) => (Math.min(ms, SCALE_MS) / SCALE_MS) * R;
  const sorted = [...bids].sort((a, b) => (a.dsp_name ?? "").localeCompare(b.dsp_name ?? ""));
  const t = (s: string) => (uppercase ? s.toUpperCase() : s);

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="h-full w-full overflow-visible" role="img" aria-label="DSP response times">
      {[25, 50, 75].map((ms) => (
        <circle key={ms} cx={c} cy={c} r={r(ms)} fill="none" stroke={theme.ring} strokeWidth={1} />
      ))}
      <circle cx={c} cy={c} r={r(100)} fill="none" stroke={theme.deadline} strokeWidth={1.25} strokeDasharray="4 6" />
      <text x={c} y={c - r(100) - 8} textAnchor="middle" fill={theme.deadline} fontSize={10} letterSpacing="0.12em" fontFamily={theme.font}>
        {t("100 ms deadline")}
      </text>

      {sorted.map((b, i) => {
        const angle = (-90 + (360 / sorted.length) * i + 36) * (Math.PI / 180);
        const timedOut = b.response_time_ms == null;
        const dist = timedOut ? R + 6 : r(b.response_time_ms ?? 0);
        const x = c + Math.cos(angle) * dist;
        const y = c + Math.sin(angle) * dist;
        const lx = c + Math.cos(angle) * (R + 34);
        const ly = c + Math.sin(angle) * (R + 34);
        const won = b.status === "WON";
        const color = won ? theme.winner : timedOut ? theme.timeout : theme.dot;
        return (
          <g key={b.dsp_name ?? b.dsp_id}>
            <line x1={c} y1={c} x2={c + Math.cos(angle) * R} y2={c + Math.sin(angle) * R} stroke={theme.ring} strokeWidth={1} />
            <line
              x1={c}
              y1={c}
              x2={x}
              y2={y}
              stroke={color}
              strokeWidth={won ? 2 : 1.25}
              strokeOpacity={won ? 1 : 0.7}
              style={{ transition: "all 700ms cubic-bezier(.2,.8,.2,1)" }}
            />
            {timedOut ? (
              <g transform={`translate(${x} ${y})`} stroke={theme.timeout} strokeWidth={1.5}>
                <line x1={-5} y1={-5} x2={5} y2={5} />
                <line x1={-5} y1={5} x2={5} y2={-5} />
              </g>
            ) : (
              <>
                {won && <circle cx={x} cy={y} r={16} fill={theme.winner} opacity={0.18} className="animate-ping origin-center [transform-box:fill-box]" />}
                <circle cx={x} cy={y} r={won ? 7 : 4.5} fill={color} style={{ transition: "all 700ms cubic-bezier(.2,.8,.2,1)" }} />
              </>
            )}
            <text
              x={lx}
              y={ly - 6}
              textAnchor="middle"
              fill={won ? theme.winner : theme.label}
              fontSize={12}
              fontWeight={500}
              letterSpacing="0.06em"
              fontFamily={theme.font}
            >
              {t(b.dsp_name ?? "DSP")}
            </text>
            <text x={lx} y={ly + 10} textAnchor="middle" fill={theme.muted} fontSize={11} fontFamily={theme.font}>
              {timedOut ? t("timed out") : `${b.response_time_ms} ms · ${b.amount > 0 ? `$${b.amount.toFixed(2)}` : "–"}`}
            </text>
          </g>
        );
      })}
      <circle cx={c} cy={c} r={3} fill={theme.label} />
    </svg>
  );
}

/** One sentence describing what just happened, for editorial captions. */
export function narrate(bids: Bid[], clearing: number | null | undefined): string {
  const winner = bids.find((b) => b.status === "WON");
  const late = bids.filter((b) => b.status === "TIMEOUT").map((b) => b.dsp_name);
  const lateText = late.length ? `${late.join(" and ")} ran out of time. ` : "Every buyer answered in time. ";
  if (!winner) return `${bids.length} buyers were asked. ${lateText}No valid bid cleared the floor.`;
  return `${bids.length} buyers were asked. ${lateText}${winner.dsp_name} bid $${winner.amount.toFixed(2)} and paid $${(clearing ?? 0).toFixed(2)}, one cent over the runner-up.`;
}
