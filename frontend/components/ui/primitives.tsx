"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { gsap } from "gsap";
import { SwapText } from "@/components/motion/SwapText";
import { DashRule } from "@/components/motion/DashRule";
import { Reveal } from "@/components/motion/Reveal";
import { useReady } from "@/components/motion/ready";
import { T } from "@/lib/theme";
import SpotlightCard from "@/components/reactbits/SpotlightCard";
import Counter from "@/components/reactbits/Counter";
import StatusMark, { type StatusMarkStatus } from "@/components/reactbits/StatusMark";

export const COLORS = {
  accent: "#dc5000",
  mint: "#ffb829",
  amber: "#ffb829",
  rose: "#ff7a2f",
  muted: "#8a7b6b",
};

export function PageHeader({ kicker, title, children }: { kicker: string; title: string; children?: ReactNode }) {
  const ready = useReady();
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ready || !body.current) return;
    const t = gsap.fromTo(body.current, { y: 30, opacity: 0 }, { y: 0, opacity: 1, duration: 1.1, delay: 0.35, ease: "expo.out" });
    return () => {
      t.kill();
    };
  }, [ready]);
  return (
    <header className="mb-14">
      <div className="flex items-center gap-3 text-[12px] font-medium uppercase" style={{ color: T.drift }}>
        <span className="relative flex h-2 w-2">
          <span className="absolute inset-0 animate-ping rounded-full opacity-60" style={{ background: T.ember }} />
          <span className="relative h-2 w-2 rounded-full" style={{ background: T.ember }} />
        </span>
        {kicker}
      </div>
      <h1 className="mt-6 max-w-[16ch] text-[44px] font-medium uppercase leading-[0.92] md:text-[76px]">
        {ready ? <SwapText text={title} stagger={0.06} /> : <span className="opacity-0">{title}</span>}
      </h1>
      {children && (
        <div ref={body} className="mt-8 max-w-xl text-[15px] leading-relaxed opacity-0" style={{ color: "#b5a690" }}>
          {children}
        </div>
      )}
      <DashRule className="mt-12" />
    </header>
  );
}

export function Panel({
  children,
  className = "",
  glow = "rgba(220, 80, 0, 0.16)",
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  glow?: string;
  delay?: number;
}) {
  return (
    <Reveal delay={delay} className={className.includes("z-") ? "relative z-20" : ""}>
      <SpotlightCard
        spotlightColor={glow}
        intensity={0.9}
        spotlightSize={360}
        className={`group !rounded-[28px] !border-[#40372e]/70 !bg-[#1a0f08] !p-7 transition-[border-color,transform] duration-500 ease-[cubic-bezier(.2,.8,.2,1)] hover:!border-[#dc5000]/40 ${className}`}
      >
        {children}
      </SpotlightCard>
    </Reveal>
  );
}

export function Stat({
  label,
  value,
  decimals = 0,
  prefix,
  suffix,
  hint,
  color = "#ffedd7",
}: {
  label: string;
  value: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  hint?: ReactNode;
  color?: string;
}) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className="mt-3 flex items-baseline">
        <Counter
          value={value}
          decimals={decimals}
          prefix={prefix}
          suffix={suffix ? <span className="ml-1 text-base text-zinc-500 font-normal">{suffix}</span> : undefined}
          fontSize={34}
          fontWeight={600}
          textColor={color}
          tabular
        />
      </div>
      {hint && <div className="mt-2 text-xs text-zinc-500">{hint}</div>}
    </div>
  );
}

const AUCTION_STATUS: Record<string, StatusMarkStatus> = {
  COMPLETED: "done",
  WON: "done",
  NO_BID: "cancelled",
  LOST: "cancelled",
  FAILED: "failed",
  TIMEOUT: "failed",
  BELOW_FLOOR: "cancelled",
  BUDGET_EXCEEDED: "cancelled",
  ACTIVE: "done",
  PAUSED: "pending",
};

export const prettyStatus = (s: string) => s.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());

export function Status({ status, label = true, size = 16 }: { status: string; label?: boolean; size?: number }) {
  return (
    <StatusMark
      status={AUCTION_STATUS[status] ?? "running"}
      label={label ? <span className="text-zinc-300">{prettyStatus(status)}</span> : undefined}
      size={size}
      fontSize={13}
      color={COLORS.muted}
      doneColor={COLORS.mint}
      errorColor={COLORS.rose}
    />
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-rose/30 bg-rose/[0.06] px-4 py-3 text-sm text-zinc-100">{children}</div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-white/[0.04] ${className}`} />;
}

export const money = (n: number | null | undefined) => (n == null ? "–" : `$${n.toFixed(2)}`);
export const ms = (n: number | null | undefined) => (n == null ? "–" : `${n} ms`);
