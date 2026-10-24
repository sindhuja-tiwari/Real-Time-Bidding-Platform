"use client";

import { useMemo, useState } from "react";
import type { Deployment, DriftPoint, Incident, SuccessPoint } from "@/lib/evidence";
import { isSuccess } from "@/lib/evidence";
import { T } from "@/lib/theme";

const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/**
 * The alert metric over the incident window, with each deploy drawn as a
 * dashed marker so you can see whether the drop lines up with it.
 */
export function AlertChart({ incident, deployments, height = 260 }: { incident: Incident; deployments: Deployment[]; height?: number }) {
  const W = 960;
  const H = height;
  const pad = { l: 52, r: 16, t: 28, b: 30 };
  const pts = incident.alert.timeline;
  const success = pts.length > 0 && isSuccess(pts[0]);
  const [hover, setHover] = useState<number | null>(null);

  const { xs, ys, max, t0, t1 } = useMemo(() => {
    const times = pts.map((p) => +new Date(isSuccess(p) ? p.window_start : p.sampled_at));
    const vals = pts.map((p) => (isSuccess(p) ? p.success_rate * 100 : (p as DriftPoint).not_yet_counted));
    const [w0, w1] = incident.telemetry_window.map((d) => +new Date(d));
    const lo = Math.min(w0, ...times);
    const hi = Math.max(w1, ...times);
    return { xs: times, ys: vals, max: success ? 100 : Math.max(10, ...vals.map(Math.abs)) * 1.15, t0: lo, t1: hi };
  }, [pts, incident.telemetry_window, success]);

  const x = (t: number) => pad.l + ((t - t0) / Math.max(1, t1 - t0)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - v / max) * (H - pad.t - pad.b);
  const path = xs.map((t, i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(ys[i]).toFixed(1)}`).join(" ");
  const area = xs.length ? `${path} L${x(xs[xs.length - 1])},${y(0)} L${x(xs[0])},${y(0)} Z` : "";
  const ticks = success ? [0, 50, 100] : [0, Math.round(max / 2), Math.round(max)];

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    let best = 0;
    xs.forEach((t, i) => {
      if (Math.abs(x(t) - px) < Math.abs(x(xs[best]) - px)) best = i;
    });
    setHover(best);
  };

  const h = hover != null ? pts[hover] : null;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full overflow-visible"
        style={{ height }}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
        role="img"
        aria-label={success ? "Auction success rate over the incident" : "Analytics drift over the incident"}
      >
        <defs>
          <linearGradient id="alertFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={T.ember} stopOpacity="0.32" />
            <stop offset="100%" stopColor={T.ember} stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} stroke="rgba(255,237,215,0.07)" />
            <text x={pad.l - 10} y={y(v) + 4} textAnchor="end" fontSize="11" fill={T.drift} className="font-mono">
              {success ? `${v}%` : v}
            </text>
          </g>
        ))}
        {deployments.map((d) => {
          const dx = x(+new Date(d.started_at));
          return (
            <g key={d.started_at}>
              <line x1={dx} x2={dx} y1={pad.t - 14} y2={H - pad.b} stroke={T.saffron} strokeDasharray="3 5" />
              <text x={dx + 6} y={pad.t - 4} fontSize="11" fill={T.saffron} className="font-mono uppercase">
                deploy {d.to_version}
              </text>
            </g>
          );
        })}
        <path d={area} fill="url(#alertFill)" />
        <path d={path} fill="none" stroke={T.ember} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
        {xs.map((t, i) => (
          <circle key={t} cx={x(t)} cy={y(ys[i])} r={hover === i ? 5 : 2.5} fill={hover === i ? T.cream : T.ember} />
        ))}
        {hover != null && <line x1={x(xs[hover])} x2={x(xs[hover])} y1={pad.t} y2={H - pad.b} stroke="rgba(255,237,215,0.25)" />}
        <text x={pad.l} y={H - 6} fontSize="11" fill={T.drift} className="font-mono">
          {time(new Date(t0).toISOString())}
        </text>
        <text x={W - pad.r} y={H - 6} textAnchor="end" fontSize="11" fill={T.drift} className="font-mono">
          {time(new Date(t1).toISOString())}
        </text>
      </svg>
      <div
        className="pointer-events-none absolute right-0 top-0 min-w-[220px] rounded-2xl border px-4 py-3 text-[12px] transition-opacity duration-200"
        style={{ borderColor: T.cork, background: T.raised, opacity: h ? 1 : 0 }}
      >
        {h && isSuccess(h) && <SuccessTip p={h} />}
        {h && !isSuccess(h) && <DriftTip p={h} />}
      </div>
    </div>
  );
}

function SuccessTip({ p }: { p: SuccessPoint }) {
  return (
    <>
      <div className="font-mono" style={{ color: T.drift }}>{time(p.window_start)}</div>
      <div className="mt-1 font-serif text-[28px] italic leading-none">{(p.success_rate * 100).toFixed(1)}%</div>
      <div className="mt-2 font-mono" style={{ color: T.drift }}>
        {p.requests} req · p95 {p.p95_latency_ms} ms
      </div>
      {p.errors && Object.keys(p.errors).length > 0 && (
        <div className="mt-1 font-mono" style={{ color: T.flame }}>
          {Object.entries(p.errors).map(([k, v]) => `${v} ${k}`).join(" · ")}
        </div>
      )}
    </>
  );
}

function DriftTip({ p }: { p: DriftPoint }) {
  return (
    <>
      <div className="font-mono" style={{ color: T.drift }}>{time(p.sampled_at)}</div>
      <div className="mt-1 font-serif text-[28px] italic leading-none">{p.not_yet_counted}</div>
      <div className="mt-2 font-mono" style={{ color: T.drift }}>
        {p.finished_auctions} finished · {p.rolled_up} counted
      </div>
    </>
  );
}

/** A tiny version for lists. */
export function Spark({ incident, width = 160, height = 36 }: { incident: Incident; width?: number; height?: number }) {
  const pts = incident.alert.timeline;
  if (pts.length < 2) return null;
  const success = isSuccess(pts[0]);
  const vals = pts.map((p) => (isSuccess(p) ? p.success_rate : (p as DriftPoint).not_yet_counted));
  const max = success ? 1 : Math.max(1, ...vals);
  const d = vals.map((v, i) => `${i ? "L" : "M"}${((i / (vals.length - 1)) * width).toFixed(1)},${(2 + (1 - v / max) * (height - 4)).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <path d={d} fill="none" stroke={T.ember} strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}
