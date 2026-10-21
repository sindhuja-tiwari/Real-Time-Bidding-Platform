"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, API_BASE_URL, type AuctionRequest, type AuctionSummary } from "./api";
import { mockApi } from "./mock";

export type Preference = "auto" | "live" | "demo";
type Source = typeof mockApi;

interface DataContextValue {
  preference: Preference;
  setPreference: (p: Preference) => void;
  /** null while the first health check is in flight */
  backendUp: boolean | null;
  /** true when requests are served by the in-browser simulation */
  isDemo: boolean;
  source: Source;
  adSlotId: string;
  setAdSlotId: (id: string) => void;
  /** bumps whenever an auction is run, so views can refetch */
  version: number;
  runAuction: (country: string, device: string) => Promise<AuctionSummary>;
  apiBaseUrl: string;
}

const DataContext = createContext<DataContextValue | null>(null);

const liveApi: Source = {
  ...api,
  adSlotId: "",
  health: async () => {
    const root = API_BASE_URL.replace(/\/api\/v1\/?$/, "");
    const res = await fetch(`${root}/health`, { cache: "no-store", signal: AbortSignal.timeout(2000) });
    if (!res.ok) throw new Error(`health check failed: ${res.status}`);
    return res.json();
  },
};

function readStorage(key: string, fallback: string) {
  try {
    return window.localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function writeStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: setting just won't persist */
  }
}

export function DataProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPref] = useState<Preference>("auto");
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [adSlotId, setSlot] = useState("");
  const [version, setVersion] = useState(0);

  useEffect(() => {
    setPref(readStorage("rtb.preference", "auto") as Preference);
    setSlot(readStorage("rtb.adSlotId", ""));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const check = () =>
      liveApi
        .health()
        .then(() => !cancelled && setBackendUp(true))
        .catch(() => !cancelled && setBackendUp(false));
    check();
    const t = setInterval(check, 15_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const isDemo = preference === "demo" || (preference === "auto" && backendUp !== true);
  const source = isDemo ? mockApi : liveApi;

  const setPreference = useCallback((p: Preference) => {
    setPref(p);
    writeStorage("rtb.preference", p);
    setVersion((v) => v + 1);
  }, []);

  const setAdSlotId = useCallback((id: string) => {
    setSlot(id);
    writeStorage("rtb.adSlotId", id);
  }, []);

  const runAuction = useCallback(
    async (country: string, device: string) => {
      const slot = isDemo ? mockApi.adSlotId : adSlotId.trim();
      if (!slot) throw new Error("Set the ad slot ID printed by `python -m app.seed` on the System page first.");
      const body: AuctionRequest = {
        request_id: `req_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
        user: { id: `user_${Math.floor(Math.random() * 1000)}`, country, device },
        ad_slot: { id: slot, width: 300, height: 250 },
      };
      const result = await source.runAuction(body);
      setVersion((v) => v + 1);
      return result;
    },
    [isDemo, adSlotId, source],
  );

  const value = useMemo(
    () => ({
      preference,
      setPreference,
      backendUp,
      isDemo,
      source,
      adSlotId,
      setAdSlotId,
      version,
      runAuction,
      apiBaseUrl: API_BASE_URL,
    }),
    [preference, setPreference, backendUp, isDemo, source, adSlotId, setAdSlotId, version, runAuction],
  );

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

export function useData() {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useData must be used inside <DataProvider>");
  return ctx;
}

/** Fetches with the active source and refetches when the source or data changes. */
export function useQuery<T>(fn: (s: Source) => Promise<T>, deps: unknown[] = []) {
  const { source, version, backendUp } = useData();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (backendUp === null) return; // wait for the first health check
    let cancelled = false;
    setLoading(true);
    fn(source)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, version, backendUp, ...deps]);

  return { data, error, loading };
}
