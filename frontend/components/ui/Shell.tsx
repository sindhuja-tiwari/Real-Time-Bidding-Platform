"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import Noise from "@/components/reactbits/Noise";
import TargetCursor from "@/components/reactbits/TargetCursor";
import { DataProvider } from "@/lib/data";
import { EvidenceProvider } from "@/lib/evidence";
import { SmoothScroll } from "@/components/motion/SmoothScroll";
import { Preloader } from "@/components/motion/Preloader";
import { ReadyContext } from "@/components/motion/ready";
import { T } from "@/lib/theme";
import { Nav } from "./Nav";

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const [ready, setReady] = useState(false);

  // Concept pages bring their own full-bleed layout.
  if (pathname.startsWith("/concepts")) return <DataProvider>{children}</DataProvider>;

  return (
    <DataProvider>
      <EvidenceProvider>
      <ReadyContext.Provider value={ready}>
        <div className="min-h-screen font-display" style={{ background: T.bg, color: T.cream }}>
          <SmoothScroll />
          <Preloader onDone={() => setReady(true)} colors={{ bg: T.bg, fg: T.cream, muted: T.drift, accent: T.ember, second: T.saffron }} />
          <Nav ready={ready} />
          {pathname === "/" ? (
            children
          ) : (
            <main className="mx-auto max-w-[1360px] px-5 pb-32 pt-36 md:px-8">{children}</main>
          )}
          <Noise fixed opacity={0.06} blendMode="overlay" fps={18} zIndex={60} />
          <TargetCursor targetSelector="a, button, [data-cursor]" cursorColor={T.cream} showLabel={false} size={30} thickness={2} />
        </div>
      </ReadyContext.Provider>
      </EvidenceProvider>
    </DataProvider>
  );
}
