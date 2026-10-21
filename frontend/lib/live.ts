"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AnalyticsOverview, AuctionSummary, Bid } from "./api";
import { useData } from "./data";

const COUNTRIES = ["US", "GB", "DE", "IN", "BR", "JP"];
const DEVICES = ["mobile", "desktop", "tablet"];
const pick = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)];

/**
 * Keeps a live view of the platform: the latest auction with its bids, recent
 * history and the overview. With `autoMs` set, it runs an auction on that
 * interval so a demo keeps moving on its own.
 */
export function useLiveAuctions({ autoMs = 0, historySize = 24 } = {}) {
  const { source, runAuction, version, backendUp } = useData();
  const [last, setLast] = useState<{ auction: AuctionSummary; bids: Bid[] } | null>(null);
  const [history, setHistory] = useState<AuctionSummary[]>([]);
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const busy = useRef(false);

  useEffect(() => {
    if (backendUp === null) return;
    let cancelled = false;
    Promise.all([source.auctions(historySize), source.overview()])
      .then(async ([h, o]) => {
        if (cancelled) return;
        setHistory(h);
        setOverview(o);
        if (!last && h[0]) {
          const bids = await source.bidsForAuction(h[0].id);
          if (!cancelled) setLast({ auction: h[0], bids });
        }
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, version, backendUp, historySize]);

  const run = useCallback(
    async (country = pick(COUNTRIES), device = pick(DEVICES)) => {
      if (busy.current) return null;
      busy.current = true;
      setRunning(true);
      setError(null);
      try {
        const auction = await runAuction(country, device);
        const bids = await source.bidsForAuction(auction.id);
        setLast({ auction, bids });
        setTick((t) => t + 1);
        return auction;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return null;
      } finally {
        busy.current = false;
        setRunning(false);
      }
    },
    [runAuction, source],
  );

  useEffect(() => {
    if (!autoMs) return;
    const t = setInterval(() => void run(), autoMs);
    return () => clearInterval(t);
  }, [autoMs, run]);

  return { last, history, overview, running, error, run, tick };
}
