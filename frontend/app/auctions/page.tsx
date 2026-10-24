"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import GlideSelect from "@/components/reactbits/GlideSelect";
import RubberSegment from "@/components/reactbits/RubberSegment";
import { PressButton } from "@/components/ui/PressButton";
import StarBorder from "@/components/reactbits/StarBorder";
import TearTicket from "@/components/reactbits/TearTicket";
import DecryptedText from "@/components/reactbits/DecryptedText";
import type { AuctionSummary, Bid } from "@/lib/api";
import { useData, useQuery } from "@/lib/data";
import { COUNTRIES, DEVICES } from "@/lib/mock";
import { DspRace } from "@/components/ui/DspRace";
import { COLORS, ErrorNote, PageHeader, Panel, Skeleton, Status, money, ms } from "@/components/ui/primitives";

// Rendered on the client only: its injected <style> differs between server and browser.
const SplitFlapText = dynamic(() => import("@/components/reactbits/SplitFlapText"), { ssr: false });

const COUNTRY_NAMES: Record<string, string> = {
  US: "United States",
  GB: "United Kingdom",
  DE: "Germany",
  IN: "India",
  BR: "Brazil",
  JP: "Japan",
};

export default function ArenaPage() {
  const router = useRouter();
  const { runAuction, source, isDemo } = useData();
  const dsps = useQuery((s) => s.dsps());
  const history = useQuery((s) => s.auctions(25));

  const [country, setCountry] = useState("US");
  const [device, setDevice] = useState("mobile");
  const [running, setRunning] = useState(false);
  const [burst, setBurst] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<{ auction: AuctionSummary; bids: Bid[] } | null>(null);

  const names = (dsps.data ?? []).map((d) => d.name).sort();

  async function runOnce() {
    const auction = await runAuction(country, device);
    const bids = await source.bidsForAuction(auction.id);
    setLast({ auction, bids });
    return auction;
  }

  // Clicks during a run are queued rather than ignored.
  const queued = useRef(0);
  const active = useRef(false);

  async function run(times = 1) {
    if (active.current) {
      queued.current += times;
      setRunning(true);
      return;
    }
    active.current = true;
    setRunning(true);
    setError(null);
    try {
      for (let i = 0; i < times; i++) {
        if (times > 1) setBurst(i + 1);
        await runOnce();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      active.current = false;
      setBurst(null);
      const more = queued.current;
      queued.current = 0;
      if (more) void run(more);
      else setRunning(false);
    }
  }

  const a = last?.auction;
  const board = a ? (a.winning_dsp_name ? `${a.winning_dsp_name} ${money(a.clearing_price)}` : "NO BID") : "READY";

  return (
    <div>
      <PageHeader kicker="Arena · Run it yourself" title="Run an auction. Watch the bids *land.*">
        Each run sends one ad request through {isDemo ? "the in-browser simulation" : "the live backend"}. Every DSP gets the
        same 100 ms; anything slower is dropped, and the winner pays the runner-up&apos;s price plus one cent.
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <Panel className="relative z-20 !overflow-visible">
          <div className="label">Ad request</div>
          <div className="mt-6 space-y-6">
            <div>
              <div className="mb-2 text-xs text-zinc-500">User country</div>
              <GlideSelect
                options={COUNTRIES.map((c) => ({ value: c, label: COUNTRY_NAMES[c] ?? c, tag: c }))}
                value={country}
                onChange={(v) => setCountry(v)}
                accentColor={COLORS.accent}
                surfaceColor="#1a0f08"
                highlightColor="rgba(220,80,0,0.14)"
                textColor="#ffedd7"
                size="md"
                menuWidth={260}
                ariaLabel="User country"
              />
            </div>
            <div>
              <div className="mb-2 text-xs text-zinc-500">Device</div>
              <RubberSegment
                items={DEVICES.map((d) => ({ value: d, label: d[0].toUpperCase() + d.slice(1) }))}
                value={device}
                onChange={(v) => setDevice(v)}
                equalSlots
                trackColor="rgba(255,255,255,0.04)"
                thumbColor="rgba(220,80,0,0.22)"
                textColor="#b5a690"
                activeTextColor="#ffedd7"
              />
            </div>
            <div className="flex items-center justify-between rounded-xl border border-white/[0.06] px-4 py-3 text-xs text-zinc-500">
              <span>Ad slot</span>
              <span className="font-mono text-zinc-300">300 × 250</span>
            </div>

            <div className="space-y-3 pt-2">
              <PressButton onClick={() => run(1)} busy={running && !burst} className="w-full">
                {running && !burst ? (queued.current ? "Queued, one more…" : "Auctioning…") : "Run auction"}
              </PressButton>
              <StarBorder
                as="button"
                onClick={() => run(10)}
                color="#ffb829"
                radius={14}
                hover="brighten"
                className="w-full text-sm disabled:opacity-50"
              >
                {burst ? `Running ${burst} / 10…` : "Fire a burst of 10"}
              </StarBorder>
            </div>
            {error && <ErrorNote>{error}</ErrorNote>}
          </div>
        </Panel>

        <Panel delay={0.1}>
          <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="label">DSP race</div>
              <p className="mt-2 text-sm text-zinc-400">
                {a ? `Cleared in ${ms(a.duration_ms)}.` : "Bars fill to each DSP's response time."}
              </p>
            </div>
            <SplitFlapText
              key={board}
              text={board}
              loop={false}
              padTo={12}
              fontSize={20}
              gap={3}
              tileRadius={5}
              tileColor="#1a0f08"
              textColor={a?.winning_dsp_name ? "#ffedd7" : "#b5a690"}
              charset="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-$."
              flipsPerChar={6}
              stagger={0.03}
            />
          </div>
          {dsps.data ? (
            <DspRace names={names} bids={last?.bids ?? null} running={running} />
          ) : (
            <Skeleton className="h-[240px]" />
          )}
        </Panel>
      </div>

      {a && a.winning_dsp_name && (
        <div className="mt-10 flex flex-col items-center gap-4">
          <div className="label">Winning receipt · tear the stub to open the auction</div>
          <TearTicket
            key={a.id}
            image={a.creative_url ?? undefined}
            imageAlt={`${a.winning_dsp_name} creative`}
            width={520}
            height={230}
            stubSize={150}
            background="#1a0f08"
            stubBackground="#382416"
            borderColor="rgba(255,255,255,0.08)"
            color="#ffedd7"
            rotate={0}
            onTear={() => setTimeout(() => router.push(`/auctions/${a.id}`), 500)}
            stub={
              <div className="flex h-full flex-col items-center justify-center gap-1 p-4 text-center">
                <span className="label !text-[10px]">Clearing</span>
                <span className="num font-mono text-2xl font-semibold text-zinc-100">{money(a.clearing_price)}</span>
                <span className="text-[11px] text-zinc-500">{ms(a.duration_ms)}</span>
              </div>
            }
          >
            <div className="flex h-full flex-col justify-end p-5">
              <span className="label !text-zinc-300">Winner</span>
              <span className="mt-1 text-2xl font-semibold text-zinc-100">{a.winning_dsp_name}</span>
              <span className="mt-1 font-mono text-[11px] text-zinc-300">{a.request_id}</span>
            </div>
          </TearTicket>
          <Link href={`/auctions/${a.id}`} className="text-[12px] uppercase underline decoration-dashed underline-offset-4" style={{ color: "#8a7b6b" }}>
            or just open it →
          </Link>
        </div>
      )}

      <div className="mt-10">
        <Panel>
          <div className="mb-4 label">History</div>
          {history.data ? (
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Request</th>
                    <th>Status</th>
                    <th>Winner</th>
                    <th className="!text-right">Clearing</th>
                    <th className="!text-right">Latency</th>
                    <th className="!text-right">Started</th>
                  </tr>
                </thead>
                <tbody>
                  {history.data.map((h) => (
                    <tr key={h.id} className="cursor-pointer" onClick={() => router.push(`/auctions/${h.id}`)}>
                      <td>
                        <Link href={`/auctions/${h.id}`} className="font-mono text-[13px] text-zinc-200">
                          <DecryptedText text={h.request_id} animateOn="hover" speed={40} sequential encryptedClassName="text-accent" />
                        </Link>
                      </td>
                      <td>
                        <Status status={h.status} size={14} />
                      </td>
                      <td className="text-zinc-300">{h.winning_dsp_name ?? "–"}</td>
                      <td className="num text-right font-mono text-zinc-300">{money(h.clearing_price)}</td>
                      <td className="num text-right font-mono text-zinc-400">{ms(h.duration_ms)}</td>
                      <td className="text-right text-zinc-500">{new Date(h.started_at).toLocaleTimeString()}</td>
                    </tr>
                  ))}
                  {history.data.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-10 text-center text-zinc-500">
                        No auctions yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          ) : (
            <Skeleton className="h-[300px]" />
          )}
        </Panel>
      </div>
    </div>
  );
}
