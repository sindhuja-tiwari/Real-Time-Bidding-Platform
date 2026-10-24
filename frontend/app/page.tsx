"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Counter from "@/components/reactbits/Counter";
import Magnet from "@/components/reactbits/Magnet";
import DecryptedText from "@/components/reactbits/DecryptedText";
import ScrollReveal from "@/components/reactbits/ScrollReveal";
import ScrollVelocity from "@/components/reactbits/ScrollVelocity";
import { useLiveAuctions } from "@/lib/live";
import { useData, useQuery } from "@/lib/data";
import type { Bid } from "@/lib/api";
import { T } from "@/lib/theme";
import { RadialRace, narrate } from "@/components/ui/RadialRace";
import { SwapText } from "@/components/motion/SwapText";
import { DashRule } from "@/components/motion/DashRule";
import { useInView } from "@/components/motion/hooks";
import { useReady } from "@/components/motion/ready";
import { LavaField } from "@/components/motion/LavaField";

gsap.registerPlugin(ScrollTrigger);

export default function LivePage() {
  const ready = useReady();
  const [auto, setAuto] = useState(true);
  const { last, history, overview, run, running, hold } = useLiveAuctions({ autoMs: auto ? 3400 : 0, historySize: 8 });
  const { isDemo } = useData();
  const a = last?.auction;
  const bids = last?.bids ?? [];

  const hero = useRef<HTMLElement>(null);
  const object = useRef<HTMLDivElement>(null);
  const left = useRef<HTMLDivElement>(null);
  const right = useRef<HTMLDivElement>(null);

  // Entrance once the intro curtain lifts.
  useEffect(() => {
    if (!ready) return;
    const tl = gsap.timeline({ defaults: { ease: "expo.out" } });
    tl.fromTo(object.current, { scale: 0.85, opacity: 0 }, { scale: 1, opacity: 1, duration: 1.8 }, 0.5)
      .fromTo(left.current?.querySelectorAll("[data-in]") ?? [], { y: 60, opacity: 0 }, { y: 0, opacity: 1, duration: 1.2, stagger: 0.08 }, 0.15)
      .fromTo(right.current?.querySelectorAll("[data-in]") ?? [], { y: 40, opacity: 0 }, { y: 0, opacity: 1, duration: 1.2, stagger: 0.08 }, 0.35);
    return () => {
      tl.kill();
    };
  }, [ready]);

  // Scroll: the chart turns away and the columns drift apart. Explicit start
  // values matter here: a plain .to() would capture the pre-entrance opacity (0)
  // and snap back to it whenever ScrollTrigger refreshes.
  useEffect(() => {
    const ctx = gsap.context(() => {
      const st = { trigger: hero.current, start: "top top", end: "bottom top", scrub: 0.8 };
      gsap.fromTo(object.current, { scale: 1, yPercent: 0 }, { scale: 0.8, yPercent: 12, ease: "none", immediateRender: false, scrollTrigger: st });
      gsap.fromTo(left.current, { yPercent: 0, opacity: 1 }, { yPercent: -30, opacity: 0, ease: "none", immediateRender: false, scrollTrigger: st });
      gsap.fromTo(right.current, { yPercent: 0, opacity: 1 }, { yPercent: -45, opacity: 0, ease: "none", immediateRender: false, scrollTrigger: st });
    });
    return () => ctx.revert();
  }, []);

  // The winner's own response time: the auction as a whole can run past 100 ms while it waits out slow DSPs.
  const winnerMs = bids.find((b) => b.status === "WON")?.response_time_ms;
  const headline = a?.winning_dsp_name
    ? `Sold to *${a.winning_dsp_name}*${winnerMs != null ? ` in ${winnerMs} ms` : ""}`
    : a
      ? "No valid bids this round"
      : "Waiting for the first bid";

  return (
    <main className="relative">
      <LavaField anchor={object} start={ready} pulse={a?.id} />
      {/* HERO */}
      <section
        ref={hero}
        data-lava="0"
        className="relative z-10 grid min-h-[100svh] grid-cols-1 items-center gap-6 px-5 pb-16 pt-28 md:px-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:gap-10"
      >
        <div className="order-2 flex flex-col gap-10 lg:order-1">
        <div ref={left}>
          <div data-in className="text-[12px] font-medium uppercase opacity-0" style={{ color: T.drift }}>
            Auction №{String(overview?.total_auctions ?? 0).padStart(4, "0")} · {isDemo ? "Simulated" : "Live"}
          </div>
          <h1 data-in className="mt-4 max-w-[13ch] text-[44px] font-medium uppercase leading-[0.9] tracking-[-0.02em] opacity-0 md:text-[68px]">
            <SwapText key={headline} text={headline} />
          </h1>
          <div data-in className="mt-10 opacity-0">
            <Counter
              value={a?.clearing_price ?? 0}
              decimals={2}
              prefix="$"
              fontSize={104}
              fontWeight={500}
              textColor={T.cream}
              tabular
            />
            <div className="mt-3 text-[12px] font-medium uppercase" style={{ color: T.drift }}>
              Clearing price · second price + $0.01
            </div>
          </div>
        </div>

        <div ref={right} className="max-w-[520px]">
          <p data-in className="text-[19px] font-light leading-[1.4] opacity-0 md:text-[21px]" style={{ color: "#d9c8b2" }}>
            <SwapText key={a?.id ?? "x"} text={bids.length ? narrate(bids, a?.clearing_price) : "Five demand-side platforms are about to bid."} stagger={0.012} />
          </p>
          <div
            data-in
            className="mt-10 flex flex-wrap items-center gap-4 opacity-0"
            onPointerEnter={() => hold(true)}
            onPointerLeave={() => hold(false)}
          >
            <Magnet padding={60} magnetStrength={2.5}>
              <button
                onClick={() => run()}
                aria-busy={running}
                className="group relative overflow-hidden rounded-[36px] px-7 py-[15px] text-[13px] font-medium uppercase"
                style={{ background: T.bark, color: T.cream }}
              >
                <span
                  className="absolute inset-0 origin-bottom scale-y-0 rounded-[36px] transition-transform duration-500 ease-[cubic-bezier(.2,.8,.2,1)] group-hover:scale-y-100"
                  style={{ background: T.ember }}
                />
                <span className="relative">{running ? "Auctioning…" : "Run an auction"}</span>
              </button>
            </Magnet>
            <button
              onClick={() => setAuto((v) => !v)}
              className="rounded-[22.5px] border px-4 py-[7.5px] text-[12px] font-medium uppercase transition-colors duration-300 hover:bg-[#ffedd7] hover:text-[#100904]"
              style={{ borderColor: T.cream }}
            >
              Autoplay {auto ? "on" : "off"}
            </button>
          </div>
        </div>

        </div>

        <div ref={object} className="relative order-1 mx-auto aspect-square w-full max-w-[720px] opacity-0 lg:order-2">
          <div className="absolute inset-[24%]">
            {bids.length > 0 && (
              <RadialRace
                bids={bids}
                uppercase
                theme={{
                  ring: "rgba(255,237,215,0.07)",
                  deadline: T.ember,
                  dot: T.cream,
                  winner: T.saffron,
                  timeout: T.ember,
                  label: T.cream,
                  muted: T.drift,
                }}
              />
            )}
          </div>
        </div>

        <div className="pointer-events-none absolute bottom-6 left-1/2 hidden -translate-x-1/2 flex-col items-center gap-2 text-[11px] font-medium uppercase md:flex" style={{ color: T.drift }}>
          Scroll
          <span className="block h-10 w-px origin-top animate-[scrollcue_1.8s_ease-in-out_infinite]" style={{ background: T.drift }} />
        </div>
      </section>

      {/* MARQUEE */}
      <section className="relative z-10 py-10">
        <ScrollVelocity
          texts={["Second price · 100 ms · Five buyers · One winner ·", "Bid fast or not at all · Kafka · Redis · Postgres ·"]}
          velocity={40}
          fontSize="clamp(48px, 9vw, 132px)"
          fontWeight={500}
          color={T.cream}
          numCopies={4}
          className="uppercase"
        />
      </section>

      {/* NUMBERS */}
      <Numbers overview={overview} />

      {/* FIELD */}
      <Field />

      {/* LEDGER */}
      <section data-lava="3" className="relative z-10 px-5 pb-28 md:px-8">
        <DashRule />
        <div className="grid gap-10 pt-16 lg:grid-cols-[1fr_2fr]">
          <h2 className="text-[41px] font-medium uppercase leading-[0.9]">
            The
            <br />
            ledger
          </h2>
          <div onPointerEnter={() => hold(true)} onPointerLeave={() => hold(false)}>
            {history.map((h, i) => (
              <Link
                key={h.id}
                href={`/auctions/${h.id}`}
                className="group relative grid w-full grid-cols-[1.4fr_1fr_0.8fr_0.7fr] items-baseline gap-4 border-b border-dashed py-5 text-left text-[13px] uppercase md:text-[14px]"
                style={{ borderColor: T.cork, animation: `rowIn 900ms cubic-bezier(.2,.8,.2,1) ${i * 60}ms both` }}
              >
                <span
                  className="absolute inset-0 origin-left scale-x-0 transition-transform duration-500 ease-[cubic-bezier(.2,.8,.2,1)] group-hover:scale-x-100"
                  style={{ background: "rgba(56,36,22,0.55)" }}
                />
                <DecryptedText text={h.request_id} animateOn="hover" sequential speed={28} className="relative font-medium" encryptedClassName="opacity-50" />
                <span className="relative transition-transform duration-500 group-hover:translate-x-2" style={{ color: h.winning_dsp_name ? T.cream : T.drift }}>
                  {h.winning_dsp_name ?? "No bid"}
                </span>
                <span className="relative tabular-nums">{h.clearing_price != null ? `$${h.clearing_price.toFixed(2)}` : "–"}</span>
                <span className="relative text-right tabular-nums" style={{ color: T.drift }}>
                  {h.duration_ms} ms <span className="inline-block transition-transform duration-500 group-hover:translate-x-1">→</span>
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* INCIDENTS TEASER */}
      <section data-lava="3" className="relative z-10 px-5 pb-28 md:px-8">
        <DashRule />
        <Link href="/incidents" className="group grid gap-10 pt-16 lg:grid-cols-[1fr_2fr] lg:items-end">
          <div>
            <div className="text-[12px] font-medium uppercase" style={{ color: T.saffron }}>
              When it breaks
            </div>
            <h2 className="mt-4 text-[41px] font-medium uppercase leading-[0.9]">
              Every outage
              <br />
              has a <span className="accent-serif">cause.</span>
            </h2>
          </div>
          <div className="flex flex-wrap items-end justify-between gap-8">
            <p className="max-w-md text-[17px] leading-relaxed" style={{ color: "#b5a690" }}>
              EvidenceOps breaks this engine on purpose: slow DSPs, bad configs, a starved database pool. Then it works out why,
              cites the logs and metrics it used, and proves a fix in a sandbox before anyone touches production.
            </p>
            <span className="flex items-baseline gap-3">
              <span className="font-serif text-[96px] italic leading-none transition-colors duration-500 group-hover:text-[#dc5000] md:text-[128px]">
                22/22
              </span>
              <span className="max-w-[10ch] text-[12px] font-medium uppercase" style={{ color: T.drift }}>
                incidents called right →
              </span>
            </span>
          </div>
        </Link>
      </section>

      {/* FOOTER CTA */}
      <section data-lava="3" className="relative z-10 px-5 pb-16 md:px-8">
        <DashRule />
        <Link href="/auctions" className="group mt-12 flex items-end justify-between gap-6">
          <span className="text-[13vw] font-medium uppercase leading-[0.8] tracking-[-0.03em] transition-colors duration-500 group-hover:text-[#dc5000]">
            Arena
          </span>
          <span className="mb-4 text-[12px] font-medium uppercase transition-transform duration-500 group-hover:-translate-x-3" style={{ color: T.drift }}>
            Run auctions by hand →
          </span>
        </Link>
      </section>
    </main>
  );
}

function Numbers({ overview }: { overview: ReturnType<typeof useLiveAuctions>["overview"] }) {
  const { ref, inView } = useInView<HTMLDivElement>(0.35);
  const stats = [
    { label: "Auctions, last hour", value: overview?.total_auctions ?? 0, decimals: 0 },
    { label: "Filled", value: (overview?.win_rate ?? 0) * 100, decimals: 0, suffix: "%" },
    { label: "P95 latency, ms", value: overview?.p95_latency_ms ?? 0, decimals: 0 },
    { label: "Avg clearing", value: overview?.avg_winning_bid ?? 0, decimals: 2, prefix: "$" },
  ];
  return (
    <section data-lava="1" className="relative z-10 px-5 py-24 md:px-8">
      <DashRule />
      <div ref={ref} className="grid grid-cols-2 gap-x-6 gap-y-14 pt-14 lg:grid-cols-4">
        {stats.map((s, i) => (
          <div key={s.label} style={{ transition: `opacity 1s ${i * 120}ms, transform 1.2s cubic-bezier(.2,.8,.2,1) ${i * 120}ms`, opacity: inView ? 1 : 0, transform: inView ? "none" : "translateY(40px)" }}>
            <div className="text-[12px] font-medium uppercase" style={{ color: T.saffron }}>
              {s.label}
            </div>
            <div className="mt-4">
              <Counter
                value={inView ? s.value : 0}
                decimals={s.decimals}
                prefix={s.prefix}
                suffix={s.suffix}
                fontSize={88}
                fontWeight={500}
                textColor={T.cream}
                tabular
                duration={1.6}
                style={{ letterSpacing: "-0.04em" }}
              />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Field() {
  const field = useQuery(async (s) => {
    const recent = await s.auctions(30);
    return (await Promise.all(recent.map((x) => s.bidsForAuction(x.id)))).flat();
  });
  const dsps = useMemo(() => summarise(field.data ?? []), [field.data]);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!dsps.length) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(
        "[data-row]",
        { y: 50, opacity: 0 },
        { y: 0, opacity: 1, duration: 1.1, ease: "expo.out", stagger: 0.09, scrollTrigger: { trigger: list.current, start: "top 80%" } },
      );
      gsap.utils.toArray<HTMLElement>("[data-bar]").forEach((el) =>
        gsap.fromTo(el, { scaleX: 0 }, { scaleX: 1, duration: 1.4, ease: "expo.inOut", scrollTrigger: { trigger: el, start: "top 90%" } }),
      );
    }, list);
    return () => ctx.revert();
  }, [dsps.length]);

  return (
    <section data-lava="2" className="relative z-10 px-5 pb-28 md:px-8">
      <DashRule />
      <div className="grid gap-12 pt-16 lg:grid-cols-[1fr_1.4fr]">
        <div>
          <div className="text-[12px] font-medium uppercase" style={{ color: T.saffron }}>
            The field
          </div>
          <ScrollReveal baseOpacity={0.12} enableBlur blurStrength={6} baseRotation={2} textClassName="!text-[32px] md:!text-[44px] !font-medium !leading-[1.05] uppercase">
            Speed wins. A high bid that arrives late is no bid at all.
          </ScrollReveal>
          <p className="mt-6 max-w-[420px] text-[17px] leading-[1.5]" style={{ color: T.drift }}>
            DSP-C bids the most, but it is configured to answer in 150 ms. Against a 100 ms deadline it almost never gets the chance.
          </p>
        </div>
        <div ref={list}>
          {dsps.map((d) => (
            <Link
              key={d.name}
              href="/dsps"
              data-row
              className="group block border-b border-dashed py-6"
              style={{ borderColor: T.cork }}
            >
              <div className="flex items-baseline justify-between gap-4">
                <span className="text-[32px] font-medium uppercase leading-none transition-transform duration-500 ease-[cubic-bezier(.2,.8,.2,1)] group-hover:translate-x-3 md:text-[41px]">
                  {d.name}
                </span>
                <span className="text-right text-[12px] font-medium uppercase" style={{ color: T.drift }}>
                  {d.winRate}% won · {d.avgMs ? `${d.avgMs} ms` : "never on time"} · {d.timeoutRate}% late
                </span>
              </div>
              <div className="relative mt-4 h-[3px] w-full overflow-hidden rounded-full" style={{ background: "rgba(255,237,215,0.06)" }}>
                <div
                  data-bar
                  className="absolute inset-y-0 left-0 origin-left rounded-full transition-[width] duration-1000"
                  style={{ width: `${Math.max(1.5, d.winRate)}%`, background: d.timeoutRate > 20 ? T.ember : T.saffron }}
                />
              </div>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

function summarise(bids: Bid[]) {
  const by = new Map<string, Bid[]>();
  for (const b of bids) {
    const k = b.dsp_name ?? b.dsp_id;
    by.set(k, [...(by.get(k) ?? []), b]);
  }
  return [...by.entries()]
    .sort(([x], [y]) => x.localeCompare(y))
    .map(([name, bs]) => {
      const answered = bs.filter((b) => b.response_time_ms != null);
      return {
        name,
        winRate: Math.round((bs.filter((b) => b.status === "WON").length / bs.length) * 100),
        timeoutRate: Math.round((bs.filter((b) => b.status === "TIMEOUT").length / bs.length) * 100),
        avgMs: answered.length ? Math.round(answered.reduce((s, b) => s + (b.response_time_ms ?? 0), 0) / answered.length) : 0,
      };
    });
}
