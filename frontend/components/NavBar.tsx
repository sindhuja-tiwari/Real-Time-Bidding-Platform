"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/auctions", label: "Auctions" },
  { href: "/dsps", label: "DSPs" },
  { href: "/campaigns", label: "Campaigns" },
  { href: "/analytics", label: "Analytics" },
  { href: "/system", label: "System" },
];

export function NavBar() {
  const pathname = usePathname();
  return (
    <header className="border-b border-slate-800 bg-surface/60 sticky top-0 z-10 backdrop-blur">
      <div className="max-w-6xl mx-auto px-6 py-3 flex items-center gap-8">
        <span className="font-semibold text-accent tracking-tight">RTB Platform</span>
        <nav className="flex gap-1 text-sm">
          {LINKS.map((link) => {
            const active = pathname?.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`px-3 py-1.5 rounded-md transition-colors ${
                  active ? "bg-slate-800 text-white" : "text-slate-400 hover:text-white hover:bg-slate-800/60"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
