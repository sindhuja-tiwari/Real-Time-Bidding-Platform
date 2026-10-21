"use client";

import SplitFlapText from "@/components/reactbits/SplitFlapText";
import { useQuery } from "@/lib/data";
import type { Bid } from "@/lib/api";
import { COLORS, ErrorNote, PageHeader, Panel, Skeleton, Stat, Status } from "@/components/ui/primitives";

const SAMPLE = 25;

interface DspStats {
  asked: number;
  won: number;
  timeouts: number;
  avgResponse: number;
  avgBid: number;
}

function summarise(bids: Bid[]): Map<string, DspStats> {
  const out = new Map<string, DspStats>();
  const groups = new Map<string, Bid[]>();
  for (const b of bids) {
    const k = b.dsp_name ?? b.dsp_id;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(b);
  }
  for (const [k, bs] of groups) {
    const answered = bs.filter((b) => b.response_time_ms != null);
    const priced = bs.filter((b) => b.amount > 0);
    out.set(k, {
      asked: bs.length,
      won: bs.filter((b) => b.status === "WON").length,
      timeouts: bs.filter((b) => b.status === "TIMEOUT").length,
      avgResponse: answered.length ? answered.reduce((s, b) => s + (b.response_time_ms ?? 0), 0) / answered.length : 0,
      avgBid: priced.length ? priced.reduce((s, b) => s + b.amount, 0) / priced.length : 0,
    });
  }
  return out;
}

export default function DSPsPage() {
  const dsps = useQuery((s) => s.dsps());
  const stats = useQuery(async (s) => {
    const auctions = await s.auctions(SAMPLE);
    const bids = await Promise.all(auctions.map((a) => s.bidsForAuction(a.id)));
    return summarise(bids.flat());
  });

  return (
    <div>
      <PageHeader kicker="Field · Demand-side platforms" title="Who bids, how fast, and who wins.">
        Figures cover the last {SAMPLE} auctions. DSP-C bids the most but is configured at 150 ms, so it usually misses the
        100 ms deadline: low latency beats a high bid.
      </PageHeader>

      {dsps.error && <ErrorNote>{dsps.error}</ErrorNote>}

      <div className="grid gap-4 md:grid-cols-2">
        {dsps.data
          ? [...dsps.data]
              .sort((a, b) => a.name.localeCompare(b.name))
              .map((d) => {
                const st = stats.data?.get(d.name);
                const winRate = st && st.asked ? (st.won / st.asked) * 100 : 0;
                const timeoutRate = st && st.asked ? (st.timeouts / st.asked) * 100 : 0;
                return (
                  <Panel key={d.id} glow={timeoutRate > 20 ? "rgba(255,122,47,0.16)" : undefined}>
                    <div className="flex items-start justify-between gap-4">
                      <SplitFlapText
                        text={d.name}
                        loop={false}
                        padTo={5}
                        fontSize={26}
                        gap={3}
                        tileRadius={5}
                        tileColor="#1a0f08"
                        textColor="#ffedd7"
                        charset="ABCDEFGHIJKLMNOPQRSTUVWXYZ-"
                        flipsPerChar={5}
                      />
                      <Status status={d.status} />
                    </div>
                    <div className="mt-2 font-mono text-[11px] text-zinc-600">
                      {d.endpoint} · timeout {d.timeout_ms} ms
                    </div>
                    <div className="mt-6 grid grid-cols-2 gap-6 sm:grid-cols-4">
                      {st ? (
                        <>
                          <Stat label="Win rate" value={winRate} decimals={0} suffix="%" color={winRate > 0 ? "#ffedd7" : "#ffedd7"} />
                          <Stat label="Avg reply" value={Math.round(st.avgResponse)} suffix="ms" />
                          <Stat
                            label="Timeouts"
                            value={timeoutRate}
                            decimals={0}
                            suffix="%"
                            color={timeoutRate > 20 ? COLORS.rose : "#ffedd7"}
                          />
                          <Stat label="Avg bid" value={st.avgBid} decimals={2} prefix="$" />
                        </>
                      ) : (
                        <Skeleton className="col-span-4 h-[72px]" />
                      )}
                    </div>
                    <div className="mt-6 h-1 overflow-hidden rounded-full bg-white/[0.05]">
                      <div
                        className="h-full rounded-full bg-accent transition-[width] duration-1000 ease-out"
                        style={{ width: `${winRate}%` }}
                      />
                    </div>
                  </Panel>
                );
              })
          : [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[230px]" />)}
      </div>
    </div>
  );
}
