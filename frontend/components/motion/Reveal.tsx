"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

/** Rises and un-blurs into place the first time it scrolls into view. */
export function Reveal({ children, className = "", delay = 0, y = 60 }: { children: ReactNode; className?: string; delay?: number; y?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = gsap.fromTo(
      ref.current,
      { y, opacity: 0, filter: "blur(8px)" },
      {
        y: 0,
        opacity: 1,
        filter: "blur(0px)",
        duration: 1.2,
        delay,
        ease: "expo.out",
        clearProps: "filter",
        scrollTrigger: { trigger: ref.current, start: "top 90%" },
      },
    );
    return () => {
      t.scrollTrigger?.kill();
      t.kill();
    };
  }, [delay, y]);
  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}
