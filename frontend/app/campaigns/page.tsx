"use client";

import SloshGauge from "@/components/reactbits/SloshGauge";
import { useQuery } from "@/lib/data";
import { COLORS, ErrorNote, PageHeader, Panel, Skeleton, Status, money } from "@/components/ui/primitives";

export default function CampaignsPage() {
  const campaigns = useQuery((s) => s.campaigns());

  return (
    <div>
      <PageHeader kicker="Budgets · Campaign spend" title="Budgets, drawn down one impression at a time.">
        Each win atomically reserves the clearing price from the winning campaign. A campaign that can&apos;t cover its bid
        is skipped with a budget-exceeded status.
      </PageHeader>

      {campaigns.error && <ErrorNote>{campaigns.error}</ErrorNote>}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {campaigns.data
          ? campaigns.data.map((c) => {
              const left = c.daily_budget ? Math.max(0, Math.min(100, (c.remaining_budget / c.daily_budget) * 100)) : 0;
              return (
                <Panel key={c.id} glow={left < 20 ? "rgba(255,122,47,0.16)" : "rgba(255,184,41,0.12)"}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="text-[15px] font-medium text-zinc-100">{c.name}</div>
                    <Status status={c.status} label={false} size={14} />
                  </div>
                  <div className="mt-6 flex items-center gap-6">
                    <SloshGauge
                      value={Math.round(left)}
                      liquidColor={left < 20 ? COLORS.rose : COLORS.mint}
                      glassColor="#1a0f08"
                      width={64}
                      height={132}
                      radius={16}
                      ariaLabel={`${c.name} budget remaining`}
                    />
                    <dl className="flex-1 space-y-3 text-sm">
                      <Row k="Remaining" v={money(c.remaining_budget)} strong />
                      <Row k="Daily budget" v={money(c.daily_budget)} />
                      <Row k="Bid floor" v={money(c.bid_floor)} />
                      <Row k="Ends" v={new Date(c.end_time).toLocaleDateString()} />
                    </dl>
                  </div>
                  <div className="mt-5 flex flex-wrap gap-1.5">
                    {(c.target_countries.length ? c.target_countries : ["All countries"]).map((t) => (
                      <span key={t} className="rounded-full border border-white/[0.07] px-2.5 py-0.5 text-[11px] text-zinc-400">
                        {t}
                      </span>
                    ))}
                    {(c.target_devices.length ? c.target_devices : ["All devices"]).map((t) => (
                      <span key={t} className="rounded-full border border-white/[0.07] px-2.5 py-0.5 text-[11px] text-zinc-400">
                        {t}
                      </span>
                    ))}
                  </div>
                </Panel>
              );
            })
          : [0, 1, 2].map((i) => <Skeleton key={i} className="h-[260px]" />)}
      </div>
    </div>
  );
}

function Row({ k, v, strong }: { k: string; v: string; strong?: boolean }) {
  return (
    <div className="flex justify-between border-b border-white/[0.05] pb-2">
      <dt className="text-zinc-500">{k}</dt>
      <dd className={`num font-mono ${strong ? "text-zinc-100" : "text-zinc-300"}`}>{v}</dd>
    </div>
  );
}
