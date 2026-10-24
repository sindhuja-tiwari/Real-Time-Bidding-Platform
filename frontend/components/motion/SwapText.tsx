"use client";

import { Fragment, useEffect, useRef } from "react";
import { gsap } from "gsap";

/**
 * Text that re-reveals itself word by word, from behind a mask, whenever its
 * content changes. Used for live headlines. Wrap words in asterisks
 * (`*cause*`, `*DSP Alpha*`) to set them in the italic serif accent.
 */
export function SwapText({ text, className = "", stagger = 0.045 }: { text: string; className?: string; stagger?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const words = ref.current?.querySelectorAll("[data-w]");
    if (!words?.length) return;
    const tween = gsap.fromTo(
      words,
      { yPercent: 110, rotate: 4, opacity: 0 },
      { yPercent: 0, rotate: 0, opacity: 1, duration: 0.9, ease: "expo.out", stagger },
    );
    return () => {
      tween.kill();
    };
  }, [text, stagger]);
  return (
    <span ref={ref} className={className} aria-label={text.replace(/\*/g, "")}>
      {parse(text).map(({ w, accent }, i) => (
        <Fragment key={`${w}-${i}`}>
          {i > 0 && " "}
          <span aria-hidden className="inline-block overflow-hidden pb-[0.08em] align-bottom">
            <span data-w className={`inline-block will-change-transform ${accent ? "accent-serif" : ""}`}>
              {w}
            </span>
          </span>
        </Fragment>
      ))}
    </span>
  );
}

/** Splits into words, marking those inside `*...*` (which may span words). */
function parse(text: string) {
  let on = false;
  return text.split(" ").map((raw) => {
    if (raw.startsWith("*")) on = true;
    const accent = on;
    const core = raw.replace(/[.,!?:;]+$/, "");
    if (core.endsWith("*") && core.length > 1) on = false;
    return { w: raw.replace(/\*/g, ""), accent };
  });
}
