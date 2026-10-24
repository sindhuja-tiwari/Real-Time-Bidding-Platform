"use client";

import { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";

const WORDS = ["Bid.", "Win.", "Serve.", "Sold."];

/**
 * Opening sequence, played on every full page load.
 * Giant words punch through a mask one after another while a millisecond
 * counter runs, then three stacked colour panels peel away in turn and
 * hand over to the page (which bursts its lava out as they go).
 */
export function Preloader({
  onDone,
  colors,
}: {
  onDone: () => void;
  colors: { bg: string; fg: string; muted: string; accent: string; second: string };
}) {
  const root = useRef<HTMLDivElement>(null);
  const num = useRef<HTMLSpanElement>(null);
  const [show, setShow] = useState(true);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setShow(false);
      onDone();
      return;
    }
    const q = (sel: string) => root.current?.querySelectorAll(sel) ?? [];
    const words = Array.from(q("[data-word]"));
    const reel = q("[data-reel]")[0];
    // One column of words rolls up a step at a time behind the mask, like a
    // departures board: the outgoing and incoming word move as one piece, so
    // there is never a torn half-word on screen.
    const step = 100 / words.length;
    gsap.set(reel, { yPercent: step, opacity: 1 });
    const counter = { v: 0 };
    const tl = gsap.timeline({ onComplete: () => setShow(false) });

    tl.fromTo(q("[data-chrome]"), { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.5, stagger: 0.06, ease: "power2.out" }, 0)
      .to(
        counter,
        {
          v: 100,
          duration: 2.4,
          ease: "power3.inOut",
          onUpdate: () => {
            if (num.current) num.current.textContent = String(Math.round(counter.v)).padStart(3, "0");
          },
        },
        0.1,
      );

    const STEP = 0.62;
    words.forEach((_, i) => {
      tl.to(reel, { yPercent: -i * step, duration: i === 0 ? 0.7 : 0.5, ease: "expo.inOut" }, 0.15 + i * STEP);
    });

    // The last word swells, then the panels peel off: page colour, ember, saffron.
    const end = 0.15 + (words.length - 1) * STEP + 0.75;
    tl.to(words[words.length - 1], { scale: 1.06, duration: 0.5, ease: "power2.out" }, end - 0.3)
      // Let clicks through as soon as the panels start to lift.
      .set(root.current, { pointerEvents: "none" }, end)
      .to(q("[data-chrome]"), { opacity: 0, duration: 0.25 }, end)
      .to(q("[data-panel='0']"), { clipPath: "inset(0 0 100% 0)", duration: 0.9, ease: "expo.inOut" }, end)
      .to(q("[data-panel='1']"), { clipPath: "inset(0 0 100% 0)", duration: 0.9, ease: "expo.inOut" }, end + 0.12)
      .to(q("[data-panel='2']"), { clipPath: "inset(0 0 100% 0)", duration: 0.9, ease: "expo.inOut" }, end + 0.24)
      .add(onDone, end + 0.45);

    // Any click or key fast-forwards the intro instead of being swallowed.
    const skip = () => tl.timeScale(5);
    window.addEventListener("pointerdown", skip);
    window.addEventListener("keydown", skip);

    return () => {
      tl.kill();
      window.removeEventListener("pointerdown", skip);
      window.removeEventListener("keydown", skip);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!show) return null;
  const panel = "absolute inset-0 [clip-path:inset(0_0_0%_0)]";
  return (
    <div ref={root} className="fixed inset-0 z-[100]" aria-hidden>
      <div data-panel="2" className={panel} style={{ background: colors.second }} />
      <div data-panel="1" className={panel} style={{ background: colors.accent }} />
      <div data-panel="0" className={`${panel} flex flex-col justify-between p-5 md:p-8`} style={{ background: colors.bg, color: colors.fg }}>
        <div className="flex justify-between text-[12px] font-medium uppercase">
          <span data-chrome>RTB — Engine 01</span>
          <span data-chrome style={{ color: colors.muted }}>
            Five buyers · 100 ms
          </span>
        </div>

        <div className="relative h-[34vw] overflow-hidden md:h-[24vw]">
          <div data-reel className="opacity-0 will-change-transform">
            {WORDS.map((w, i) => (
              <div key={w} className="flex h-[34vw] items-end md:h-[24vw]">
                <span
                  data-word
                  className="block origin-bottom-left text-[33vw] font-medium uppercase leading-[0.8] tracking-[-0.05em] md:text-[23vw]"
                  style={{ color: i === WORDS.length - 1 ? colors.accent : colors.fg }}
                >
                  {w}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-end justify-between text-[12px] font-medium uppercase">
          <span data-chrome style={{ color: colors.muted }}>
            Real-time bidding, second price
          </span>
          <span data-chrome className="tabular-nums">
            <span ref={num}>000</span> ms
          </span>
        </div>
      </div>
    </div>
  );
}
