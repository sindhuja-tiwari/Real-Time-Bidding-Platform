// In-browser simulation of the auction engine, used when the backend isn't
// running. It mirrors the seeded demo data (backend/app/seed.py) and the
// engine rules in docs/auction-engine.md: concurrent DSP fan-out, a 100 ms
// per-DSP deadline, a floor price, and second-price clearing.

import type { AnalyticsOverview, AuctionRequest, AuctionSummary, Bid, Campaign, DSP, LatencyBucket } from "./api";

interface DspSpec {
  name: string;
  base_bid: number;
  latency_ms: number;
  failure_probability: number;
  timeout_probability: number;
}

const DSP_SEED: DspSpec[] = [
  { name: "DSP-A", base_bid: 2.5, latency_ms: 20, failure_probability: 0.01, timeout_probability: 0.0 },
  { name: "DSP-B", base_bid: 3.2, latency_ms: 50, failure_probability: 0.02, timeout_probability: 0.02 },
  { name: "DSP-C", base_bid: 4.1, latency_ms: 150, failure_probability: 0.02, timeout_probability: 0.35 },
  { name: "DSP-D", base_bid: 2.9, latency_ms: 35, failure_probability: 0.01, timeout_probability: 0.01 },
  { name: "DSP-E", base_bid: 1.8, latency_ms: 60, failure_probability: 0.05, timeout_probability: 0.05 },
];

const DSP_TIMEOUT_MS = 100;
const FLOOR_PRICE = 0.5;
const CAMPAIGN_BUDGET = 400;
const AD_SLOT_ID = "5f0c1d2e-0000-4000-8000-000000000001";

export const COUNTRIES = ["US", "GB", "DE", "IN", "BR", "JP"];
export const DEVICES = ["mobile", "desktop", "tablet"];

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx".replace(/x/g, () => Math.floor(Math.random() * 16).toString(16));
}

const uniform = (spread: number) => (Math.random() * 2 - 1) * spread;

const round2 = (n: number) => Math.round(n * 100) / 100;

interface Store {
  dsps: (DSP & { spec: DspSpec; campaign_id: string })[];
  campaigns: Campaign[];
  auctions: AuctionSummary[];
  bids: Record<string, Bid[]>;
}

let store: Store | null = null;

function createStore(): Store {
  const now = Date.now();
  const campaigns: Campaign[] = DSP_SEED.map((spec) => ({
    id: uuid(),
    advertiser_id: "demo-advertiser",
    name: `Campaign for ${spec.name}`,
    daily_budget: CAMPAIGN_BUDGET,
    remaining_budget: CAMPAIGN_BUDGET,
    bid_floor: 0.1,
    target_countries: [],
    target_devices: [],
    status: "ACTIVE",
    start_time: new Date(now - 86_400_000).toISOString(),
    end_time: new Date(now + 30 * 86_400_000).toISOString(),
    created_at: new Date(now - 86_400_000).toISOString(),
  }));
  const dsps = DSP_SEED.map((spec, i) => ({
    id: uuid(),
    name: spec.name,
    endpoint: `http://dsp-simulator:9000/${spec.name.toLowerCase()}`,
    timeout_ms: DSP_TIMEOUT_MS,
    status: "ACTIVE",
    spec,
    campaign_id: campaigns[i].id,
  }));
  const s: Store = { dsps, campaigns, auctions: [], bids: {} };

  // Back-fill an hour of history so the dashboard has something to show.
  const countries = COUNTRIES;
  const devices = DEVICES;
  for (let i = 90; i > 0; i--) {
    const at = now - i * 40_000 - Math.random() * 30_000;
    simulate(s, {
      request_id: `req_${Math.floor(at).toString(36)}`,
      user: { id: "user_seed", country: countries[i % countries.length], device: devices[i % devices.length] },
      ad_slot: { id: AD_SLOT_ID, width: 300, height: 250 },
    }, at);
  }
  return s;
}

function getStore(): Store {
  if (!store) store = createStore();
  return store;
}

// A self-contained 300×250 banner so demo mode needs no network.
const CREATIVE_COLORS = ["#dc5000", "#ffb829", "#8052ff", "#15846e", "#db3c8a"];
function creativeFor(name: string) {
  const bg = CREATIVE_COLORS[name.charCodeAt(name.length - 1) % CREATIVE_COLORS.length];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="300" height="250" viewBox="0 0 300 250"><rect width="300" height="250" fill="${bg}"/><circle cx="240" cy="60" r="90" fill="#100904" fill-opacity=".12"/><text x="24" y="196" font-family="Inter,Arial,sans-serif" font-size="44" font-weight="600" fill="#100904">${name}</text><text x="24" y="222" font-family="Inter,Arial,sans-serif" font-size="13" fill="#100904" fill-opacity=".7">300 × 250 · demo creative</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

function simulate(s: Store, req: AuctionRequest, at = Date.now()) {
  const auctionId = uuid();

  const bids: Bid[] = s.dsps.map((d) => {
    // Same model as dsp-simulator/app.py: ±10 ms jitter, a timeout draw that
    // hangs the DSP, and a small chance of an error response.
    const latency = Math.max(1, Math.round(d.spec.latency_ms + uniform(10)));
    const timedOut = Math.random() < d.spec.timeout_probability || latency > DSP_TIMEOUT_MS;
    const failed = !timedOut && Math.random() < d.spec.failure_probability;
    const amount = round2(Math.max(0, (d.spec.base_bid + uniform(0.3))));
    const campaign = s.campaigns.find((c) => c.id === d.campaign_id)!;
    let status = "VALID";
    if (timedOut) status = "TIMEOUT";
    else if (failed) status = "INVALID";
    else if (amount < FLOOR_PRICE) status = "BELOW_FLOOR";
    else if (campaign.remaining_budget < amount) status = "BUDGET_EXCEEDED";
    return {
      id: uuid(),
      dsp_id: d.id,
      dsp_name: d.name,
      campaign_id: d.campaign_id,
      amount: timedOut || failed ? 0 : amount,
      response_time_ms: timedOut ? null : latency,
      status,
    };
  });

  const valid = bids.filter((b) => b.status === "VALID").sort((a, b) => b.amount - a.amount);
  const winner = valid[0];
  let clearing: number | null = null;
  if (winner) {
    const second = valid[1]?.amount ?? FLOOR_PRICE;
    clearing = round2(Math.min(winner.amount, Math.max(second + 0.01, FLOOR_PRICE)));
    const campaign = s.campaigns.find((c) => c.id === winner.campaign_id)!;
    campaign.remaining_budget = round2(campaign.remaining_budget - clearing);
  }
  for (const b of bids) {
    if (b.status !== "VALID") continue;
    b.status = b === winner ? "WON" : "LOST";
  }

  const slowest = Math.max(0, ...bids.map((b) => (b.response_time_ms == null ? DSP_TIMEOUT_MS : b.response_time_ms)));
  const duration = Math.min(DSP_TIMEOUT_MS, slowest) + 2 + Math.round(Math.random() * 5);
  const winDsp = winner ? s.dsps.find((d) => d.id === winner.dsp_id)! : null;

  const auction: AuctionSummary = {
    id: auctionId,
    request_id: req.request_id,
    ad_slot_id: req.ad_slot.id,
    status: winner ? "COMPLETED" : "NO_BID",
    duration_ms: duration,
    winning_bid_id: winner?.id ?? null,
    winning_dsp_name: winDsp?.name ?? null,
    clearing_price: clearing,
    creative_url: winDsp ? creativeFor(winDsp.name) : null,
    landing_url: winDsp ? "https://example.com" : null,
    started_at: new Date(at).toISOString(),
    completed_at: new Date(at + duration).toISOString(),
  };
  s.auctions.unshift(auction);
  s.bids[auctionId] = bids;
  return { auction, bids };
}

function percentile(sorted: number[], p: number) {
  if (!sorted.length) return 0;
  const idx = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[Math.max(0, idx)];
}

const delay = <T,>(v: T, ms = 120) => new Promise<T>((r) => setTimeout(() => r(v), ms));
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));

export const mockApi = {
  adSlotId: AD_SLOT_ID,
  overview: async (): Promise<AnalyticsOverview> => {
    const { auctions } = getStore();
    const completed = auctions.filter((a) => a.status === "COMPLETED");
    const lat = auctions.map((a) => a.duration_ms ?? 0).sort((a, b) => a - b);
    const avg = (xs: number[]) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : 0);
    return delay({
      total_auctions: auctions.length,
      completed_auctions: completed.length,
      no_bid_auctions: auctions.filter((a) => a.status === "NO_BID").length,
      failed_auctions: auctions.filter((a) => a.status === "FAILED").length,
      win_rate: auctions.length ? completed.length / auctions.length : 0,
      avg_latency_ms: round2(avg(lat)),
      p50_latency_ms: percentile(lat, 50),
      p95_latency_ms: percentile(lat, 95),
      p99_latency_ms: percentile(lat, 99),
      avg_winning_bid: round2(avg(completed.map((a) => a.clearing_price ?? 0))),
    });
  },
  auctions: async (limit = 50) => delay(clone(getStore().auctions.slice(0, limit))),
  auction: async (id: string) => {
    const a = getStore().auctions.find((x) => x.id === id);
    if (!a) throw new Error("Auction not found in demo data");
    return delay(clone(a));
  },
  bidsForAuction: async (id: string) => delay(clone(getStore().bids[id] ?? [])),
  dsps: async (): Promise<DSP[]> =>
    delay(getStore().dsps.map(({ spec: _spec, campaign_id: _c, ...d }) => ({ ...d }))),
  campaigns: async () => delay(clone(getStore().campaigns)),
  runAuction: async (req: AuctionRequest) => {
    const res = simulate(getStore(), req);
    // Let the UI see roughly the time the auction "took".
    return delay(clone(res.auction), res.auction.duration_ms ?? 60);
  },
  latency: async (minutes = 60): Promise<LatencyBucket[]> => {
    const { auctions } = getStore();
    const cutoff = Date.now() - minutes * 60_000;
    const buckets = new Map<number, number[]>();
    for (const a of auctions) {
      const t = new Date(a.started_at).getTime();
      if (t < cutoff) continue;
      const key = Math.floor(t / 300_000) * 300_000; // 5-minute buckets
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key)!.push(a.duration_ms ?? 0);
    }
    return delay(
      [...buckets.entries()]
        .sort(([a], [b]) => a - b)
        .map(([k, xs]) => {
          const s = xs.sort((a, b) => a - b);
          return {
            bucket_start: new Date(k).toISOString(),
            p50_latency_ms: percentile(s, 50),
            p95_latency_ms: percentile(s, 95),
            p99_latency_ms: percentile(s, 99),
            count: s.length,
          };
        }),
    );
  },
  health: async () => delay({ status: "ok", service: "in-browser simulation", env: "demo" }),
};
