"use client";

import { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";

/**
 * First-visit intro: a counter runs to 100 while the engine "warms up",
 * then the curtain lifts off the page. Skipped on later visits in the session.
 */
export function Preloader({ onDone, colors }: { onDone: () => void; colors: { bg: string; fg: string; muted: string; accent: string } }) {
  const root = useRef<HTMLDivElement>(null);
  const num = useRef<HTMLSpanElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const [show, setShow] = useState(true);

  useEffect(() => {
    let seen = false;
    try {
      seen = sessionStorage.getItem("rtb.intro") === "1";
      sessionStorage.setItem("rtb.intro", "1");
    } catch {
      /* storage blocked: just play the intro */
    }
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (seen || reduce) {
      setShow(false);
      onDone();
      return;
    }
    const counter = { v: 0 };
    const tl = gsap.timeline({
      onComplete: () => {
        setShow(false);
      },
    });
    tl.to(counter, {
      v: 100,
      duration: 1.6,
      ease: "power2.inOut",
      onUpdate: () => {
        if (num.current) num.current.textContent = String(Math.round(counter.v)).padStart(3, "0");
      },
    })
      .to(bar.current, { scaleX: 1, duration: 1.6, ease: "power2.inOut" }, 0)
      .to(root.current?.querySelectorAll("[data-fade]") ?? [], { opacity: 0, y: -12, duration: 0.35, stagger: 0.04 }, "+=0.1")
      .add(onDone, "-=0.1")
      .to(root.current, { clipPath: "inset(0 0 100% 0)", duration: 0.95, ease: "expo.inOut" }, "<");
    return () => {
      tl.kill();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!show) return null;
  return (
    <div
      ref={root}
      className="fixed inset-0 z-[100] flex flex-col justify-between p-8"
      style={{ background: colors.bg, color: colors.fg, clipPath: "inset(0 0 0% 0)" }}
    >
      <div data-fade className="flex justify-between text-[12px] font-medium uppercase">
        <span>RTB — Engine 01</span>
        <span style={{ color: colors.muted }}>Warming up five buyers</span>
      </div>
      <div>
        <div data-fade className="mb-6 h-px w-full origin-left" style={{ background: "rgba(255,237,215,0.12)" }}>
          <div ref={bar} className="h-px w-full origin-left scale-x-0" style={{ background: colors.accent }} />
        </div>
        <div data-fade className="flex items-end justify-between">
          <span ref={num} className="text-[22vw] font-medium leading-[0.78] tabular-nums tracking-[-0.04em]">
            000
          </span>
          <span className="mb-4 text-[12px] font-medium uppercase" style={{ color: colors.muted }}>
            ms budget · 100
          </span>
        </div>
      </div>
    </div>
  );
}
