from __future__ import annotations

from pydantic import BaseModel


class AnalyticsOverview(BaseModel):
    total_auctions: int
    completed_auctions: int
    no_bid_auctions: int
    failed_auctions: int
    win_rate: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    avg_winning_bid: float


class LatencyBucket(BaseModel):
    bucket_start: str
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    count: int
