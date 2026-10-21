"use client";

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

/** A dashed hairline that draws itself across the page as it scrolls into view. */
export function DashRule({ color = "#40372e", className = "" }: { color?: string; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const t = gsap.fromTo(
      ref.current,
      { scaleX: 0 },
      { scaleX: 1, duration: 1.4, ease: "expo.inOut", scrollTrigger: { trigger: ref.current, start: "top 92%" } },
    );
    return () => {
      t.scrollTrigger?.kill();
      t.kill();
    };
  }, []);
  return <div ref={ref} className={`h-px origin-left border-t border-dashed ${className}`} style={{ borderColor: color }} />;
}
