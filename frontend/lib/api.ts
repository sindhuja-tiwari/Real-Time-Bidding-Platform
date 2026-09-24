const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

export interface AnalyticsOverview {
  total_auctions: number;
  completed_auctions: number;
  no_bid_auctions: number;
  failed_auctions: number;
  win_rate: number;
  avg_latency_ms: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  avg_winning_bid: number;
}

export interface Campaign {
  id: string;
  advertiser_id: string;
  name: string;
  daily_budget: number;
  remaining_budget: number;
  bid_floor: number;
  target_countries: string[];
  target_devices: string[];
  status: string;
  start_time: string;
  end_time: string;
  created_at: string;
}

export interface DSP {
  id: string;
  name: string;
  endpoint: string;
  timeout_ms: number;
  status: string;
}

export interface AuctionSummary {
  id: string;
  request_id: string;
  ad_slot_id: string;
  status: string;
  duration_ms: number | null;
  winning_bid_id: string | null;
  winning_dsp_name?: string | null;
  clearing_price?: number | null;
  started_at: string;
  completed_at: string | null;
}

export interface Bid {
  id: string;
  dsp_id: string;
  dsp_name?: string | null;
  campaign_id: string;
  amount: number;
  response_time_ms: number | null;
  status: string;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${path} failed: ${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  overview: () => apiFetch<AnalyticsOverview>("/analytics/overview"),
  campaigns: () => apiFetch<Campaign[]>("/campaigns"),
  campaign: (id: string) => apiFetch<Campaign>(`/campaigns/${id}`),
  dsps: () => apiFetch<DSP[]>("/dsps"),
  auctions: (limit = 50) => apiFetch<AuctionSummary[]>(`/auctions?limit=${limit}`),
  auction: (id: string) => apiFetch<AuctionSummary>(`/auctions/${id}`),
  bidsForAuction: (auctionId: string) => apiFetch<Bid[]>(`/bids/${auctionId}`),
  health: async () => {
    const root = API_BASE_URL.replace(/\/api\/v1\/?$/, "");
    const res = await fetch(`${root}/health`, { cache: "no-store" });
    if (!res.ok) throw new Error(`health check failed: ${res.status}`);
    return res.json() as Promise<{ status: string; service: string; env: string }>;
  },
};

export { API_BASE_URL };
