"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import Magnet from "@/components/reactbits/Magnet";
import { useData, type Preference } from "@/lib/data";
import { T } from "@/lib/theme";

const LINKS = [
  { href: "/", label: "Live" },
  { href: "/auctions", label: "Arena" },
  { href: "/dsps", label: "Field" },
  { href: "/campaigns", label: "Budgets" },
  { href: "/incidents", label: "Incidents" },
  { href: "/system", label: "System" },
];

const NEXT: Record<Preference, Preference> = { auto: "live", live: "demo", demo: "auto" };

export function Nav({ ready }: { ready: boolean }) {
  const pathname = usePathname() ?? "/";
  const { preference, setPreference, isDemo, backendUp } = useData();
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!ready) return;
    gsap.fromTo(
      ref.current?.querySelectorAll("[data-nav]") ?? [],
      { y: -24, opacity: 0 },
      { y: 0, opacity: 1, duration: 1, ease: "expo.out", stagger: 0.06, delay: 0.15 },
    );
  }, [ready]);

  const active = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  // Slides away while scrolling down, comes back on the way up.
  const [hidden, setHidden] = useState(false);
  const [menu, setMenu] = useState(false);
  useEffect(() => setMenu(false), [pathname]);
  useEffect(() => {
    let last = window.scrollY;
    const onScroll = () => {
      const y = window.scrollY;
      if (Math.abs(y - last) < 6) return;
      setHidden(y > last && y > 160);
      last = y;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const status = preference === "auto" ? (isDemo ? "Auto · demo" : "Auto · live") : preference === "live" ? (backendUp ? "Live" : "Live · offline") : "Demo";

  return (
    <nav
      ref={ref}
      data-hidden={hidden && !menu}
      className="pointer-events-none fixed inset-x-0 top-0 z-50 flex [&>*]:pointer-events-auto transition-transform duration-700 ease-[cubic-bezier(.7,0,.2,1)] data-[hidden=true]:-translate-y-full items-center justify-between px-5 py-5 text-[12px] font-medium uppercase md:px-8 md:py-6"
      style={{ color: T.cream }}
    >
      <span
        aria-hidden
        className={`pointer-events-none absolute inset-0 -bottom-6 -z-10 transition-opacity duration-300 ${menu ? "opacity-0" : ""}`}
        style={{ background: `linear-gradient(${T.bg}, ${T.bg}e6 55%, transparent)` }}
      />
      <Link data-nav href="/" className="flex items-center gap-2.5 opacity-0">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60" style={{ background: T.ember }} />
          <span className="relative inline-flex h-2 w-2 rounded-full" style={{ background: T.ember }} />
        </span>
        RTB — Engine 01
      </Link>
      <div className="flex items-center gap-5 md:gap-8">
        <div className="hidden items-center gap-7 md:flex">
          {LINKS.map((l) => (
            <Link key={l.href} data-nav href={l.href} className="group relative py-1 opacity-0">
              <span style={{ color: active(l.href) ? T.cream : T.drift }} className="transition-colors duration-300 group-hover:!text-[#ffedd7]">
                {l.label}
              </span>
              <span
                className={`absolute -bottom-0.5 left-0 h-px w-full origin-left border-t border-dashed transition-transform duration-500 ease-[cubic-bezier(.2,.8,.2,1)] ${
                  active(l.href) ? "scale-x-100" : "scale-x-0 group-hover:scale-x-100"
                }`}
                style={{ borderColor: T.cream }}
              />
            </Link>
          ))}
        </div>
        <button
          data-nav
          onClick={() => setMenu((m) => !m)}
          aria-expanded={menu}
          className="relative z-10 opacity-0 md:hidden"
        >
          {menu ? "Close" : "Menu"}
        </button>
        <div data-nav className="opacity-0">
          <Magnet padding={40} magnetStrength={3}>
            <button
              onClick={() => setPreference(NEXT[preference])}
              title="Switch data source: auto, live backend, or in-browser demo"
              className="rounded-[22.5px] border px-4 py-[7px] uppercase transition-colors duration-300 hover:bg-[#ffedd7] hover:text-[#100904]"
              style={{ borderColor: T.cream }}
            >
              {status}
            </button>
          </Magnet>
        </div>
      </div>
      {/* Mobile menu: a panel that wipes down, links rise in one after another. */}
      <div
        className="fixed inset-0 -z-20 flex flex-col justify-end px-5 pb-16 transition-[clip-path] duration-700 ease-[cubic-bezier(.7,0,.2,1)] md:hidden"
        style={{ background: T.raised, clipPath: menu ? "inset(0 0 0 0)" : "inset(0 0 100% 0)" }}
        aria-hidden={!menu}
      >
        {LINKS.map((l, i) => (
          <Link
            key={l.href}
            href={l.href}
            tabIndex={menu ? 0 : -1}
            className="overflow-hidden border-b border-dashed py-3 text-[44px] leading-none"
            style={{ borderColor: T.cork, color: active(l.href) ? T.ember : T.cream }}
          >
            <span
              className="block transition-transform duration-700 ease-[cubic-bezier(.2,.8,.2,1)]"
              style={{ transform: menu ? "translateY(0)" : "translateY(110%)", transitionDelay: menu ? `${200 + i * 60}ms` : "0ms" }}
            >
              {l.label}
            </span>
          </Link>
        ))}
      </div>
    </nav>
  );
}
