"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { gsap } from "gsap";

/** Page transition: a panel wipes off the new page as it mounts. */
export default function Template({ children }: { children: React.ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  const page = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      gsap.set(panel.current, { display: "none" });
      return;
    }
    const tl = gsap.timeline();
    tl.fromTo(panel.current, { yPercent: 0 }, { yPercent: -100, duration: 0.9, ease: "expo.inOut" }).fromTo(
      page.current,
      { y: 40, opacity: 0.4 },
      { y: 0, opacity: 1, duration: 0.9, ease: "expo.out", clearProps: "transform,opacity" },
      0.25,
    );
    return () => {
      tl.kill();
    };
  }, [pathname]);

  return (
    <>
      <div ref={panel} aria-hidden className="pointer-events-none fixed inset-0 z-[90]" style={{ background: "#1a0f08" }} />
      <div ref={page}>{children}</div>
    </>
  );
}
