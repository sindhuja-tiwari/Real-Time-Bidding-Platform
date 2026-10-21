"use client";

import { SwapText } from "@/components/motion/SwapText";
import { DashRule } from "@/components/motion/DashRule";

import Link from "next/link";
import DecryptedText from "@/components/reactbits/DecryptedText";
import BorderGlow from "@/components/reactbits/BorderGlow";
import { useQuery } from "@/lib/data";
import { DspRace } from "@/components/ui/DspRace";
import { ErrorNote, Panel, Skeleton, Stat, Status, money } from "@/components/ui/primitives";

export default function AuctionDetailPage({ params }: { params: { id: string } }) {
  const auction = useQuery((s) => s.auction(params.id), [params.id]);
  const bids = useQuery((s) => s.bidsForAuction(params.id), [params.id]);
  const a = auction.data;

  if (auction.error) {
    return (
      <div className="space-y-4">
        <ErrorNote>{auction.error}</ErrorNote>
        <Link href="/auctions" className="text-sm text-accent">
          ← Back to the arena
        </Link>
      </div>
    );
  }
  if (!a) return <Skeleton className="h-[480px]" />;

  const valid = (bids.data ?? []).filter((b) => b.status === "WON" || b.status === "LOST").length;

  return (
    <div>
      <Link href="/auctions" className="text-sm text-zinc-500 transition-colors hover:text-zinc-100">
        ← Arena
      </Link>
      <header className="mb-14 mt-8">
        <div className="label">
          <DecryptedText text={a.request_id} animateOn="view" sequential speed={35} encryptedClassName="text-accent" />
        </div>
        <h1 className="mt-6 max-w-[18ch] text-[44px] font-medium uppercase leading-[0.92] md:text-[76px]">
          <SwapText
            stagger={0.06}
            text={a.winning_dsp_name ? `Sold to ${a.winning_dsp_name} for ${money(a.clearing_price)}` : "No valid bids. Nothing sold."}
          />
        </h1>
        <div className="mt-8 flex flex-wrap items-center gap-5 text-sm text-zinc-500">
          <Status status={a.status} />
          <span className="font-mono text-xs">{a.id}</span>
          <span>{new Date(a.started_at).toLocaleString()}</span>
        </div>
        <DashRule className="mt-12" />
      </header>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Panel delay={0.00}>
          <Stat label="Latency" value={a.duration_ms ?? 0} suffix="ms" />
        </Panel>
        <Panel delay={0.06}>
          <Stat label="Clearing price" value={a.clearing_price ?? 0} decimals={2} prefix="$" />
        </Panel>
        <Panel delay={0.12}>
          <Stat label="Valid bids" value={valid} hint={`of ${bids.data?.length ?? 0} DSPs asked`} />
        </Panel>
        <Panel delay={0.18}>
          <div className="label">Winner</div>
          <div className="mt-3 text-[34px] font-semibold leading-none text-zinc-100">{a.winning_dsp_name ?? "None"}</div>
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_340px]">
        <Panel delay={0.24}>
          <div className="mb-6 label">DSP responses</div>
          {bids.data ? <DspRace names={[]} bids={bids.data} running={false} /> : <Skeleton className="h-[240px]" />}
        </Panel>
        <BorderGlow
          backgroundColor="#1a0f08"
          borderRadius={28}
          glowColor="22 100 55"
          colors={["#dc5000", "#ffb829", "#ffb829"]}
          className="h-full"
        >
          <div className="p-6">
            <div className="label">Creative served</div>
            {a.creative_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={a.creative_url}
                alt="Winning creative"
                className="mt-5 aspect-[6/5] w-full rounded-xl bg-white/[0.04] object-cover"
              />
            ) : (
              <p className="mt-5 text-sm text-zinc-500">No creative: nobody won this auction.</p>
            )}
            <p className="mt-4 text-xs text-zinc-500">
              Paid {money(a.clearing_price)} under second-price rules.
            </p>
          </div>
        </BorderGlow>
      </div>
    </div>
  );
}
