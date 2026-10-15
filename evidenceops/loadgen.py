"""Open-loop auction traffic.

Requests are scheduled at a fixed rate regardless of how fast the platform
answers (open loop), so a slow platform builds a backlog the way real
publisher traffic would instead of quietly throttling the load. Every
request's outcome is recorded; success means HTTP 201 with an auction status
of COMPLETED, returned within the client timeout.
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import asdict, dataclass
from typing import Callable, Dict, Iterable, List, Optional

import httpx

from evidenceops.stack import BACKEND_URL

COUNTRIES = ["US", "US", "US", "GB", "DE", "IN"]
DEVICES = ["mobile", "mobile", "desktop", "tablet"]


@dataclass
class RequestOutcome:
    seq: int
    request_id: str
    publisher: str
    sent_at: float  # unix epoch seconds
    latency_ms: float
    http_status: Optional[int]
    auction_status: Optional[str]
    auction_id: Optional[str]
    server_duration_ms: Optional[int]
    error: Optional[str]

    @property
    def success(self) -> bool:
        return self.http_status == 201 and self.auction_status == "COMPLETED"


async def _one(
    client: httpx.AsyncClient, seq: int, run_id: str, ad_slot_id: str, rng: random.Random, publishers: int
) -> RequestOutcome:
    request_id = f"{run_id}-{seq:06d}"
    publisher = f"publisher-{seq % publishers:02d}"
    body = {
        "request_id": request_id,
        "user": {"id": f"user-{rng.randrange(10_000)}", "country": rng.choice(COUNTRIES), "device": rng.choice(DEVICES)},
        "ad_slot": {"id": ad_slot_id, "width": 300, "height": 250},
    }
    sent_at = time.time()
    start = time.perf_counter()
    status = auction_status = auction_id = error = None
    server_ms = None
    try:
        resp = await client.post(
            f"{BACKEND_URL}/api/v1/auctions",
            json=body,
            headers={"X-Client-Role": "PUBLISHER", "X-Client-Id": publisher, "X-Request-ID": request_id},
        )
        status = resp.status_code
        if status == 201:
            data = resp.json()
            auction_status = data.get("status")
            auction_id = data.get("id")
            server_ms = data.get("duration_ms")
        else:
            try:
                error = resp.json()["error"]["code"]
            except (ValueError, KeyError, TypeError):
                error = f"http_{status}"
    except httpx.TimeoutException:
        error = "client_timeout"
    except httpx.HTTPError as exc:
        error = type(exc).__name__
    latency_ms = (time.perf_counter() - start) * 1000
    return RequestOutcome(seq, request_id, publisher, sent_at, round(latency_ms, 2), status, auction_status, auction_id, server_ms, error)


async def run_load(
    run_id: str,
    ad_slot_id: str,
    rps: float,
    duration_s: float,
    publishers: int = 20,
    client_timeout_s: float = 2.0,
    seed: int = 7,
    on_outcome: Optional[Callable[[RequestOutcome], None]] = None,
) -> List[RequestOutcome]:
    rng = random.Random(seed)
    outcomes: List[RequestOutcome] = []
    limits = httpx.Limits(max_connections=1000, max_keepalive_connections=200)
    async with httpx.AsyncClient(timeout=client_timeout_s, limits=limits) as client:
        t0 = time.perf_counter()
        total = int(rps * duration_s)
        tasks = []
        for seq in range(total):
            delay = t0 + seq / rps - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            task = asyncio.create_task(_one(client, seq, run_id, ad_slot_id, rng, publishers))
            if on_outcome is not None:
                task.add_done_callback(lambda t: on_outcome(t.result()))
            tasks.append(task)
        outcomes = list(await asyncio.gather(*tasks))
    return outcomes


def success_rate(outcomes: Iterable[RequestOutcome]) -> Optional[float]:
    items = list(outcomes)
    if not items:
        return None
    return sum(o.success for o in items) / len(items)


def window(outcomes: Iterable[RequestOutcome], start: float, end: float) -> List[RequestOutcome]:
    return [o for o in outcomes if start <= o.sent_at < end]


def bucketed(outcomes: Iterable[RequestOutcome], start: float, bucket_s: float = 10.0) -> List[Dict]:
    """Success rate and latency per time bucket (what a dashboard would plot)."""
    buckets: Dict[int, List[RequestOutcome]] = {}
    for o in outcomes:
        buckets.setdefault(int((o.sent_at - start) // bucket_s), []).append(o)
    rows = []
    for idx in sorted(buckets):
        items = buckets[idx]
        lat = sorted(o.latency_ms for o in items)
        errors: Dict[str, int] = {}
        for o in items:
            if not o.success:
                key = o.error or (o.auction_status or "unknown").lower()
                errors[key] = errors.get(key, 0) + 1
        rows.append(
            {
                "offset_s": idx * bucket_s,
                "requests": len(items),
                "success_rate": round(sum(o.success for o in items) / len(items), 4),
                "p50_latency_ms": lat[len(lat) // 2],
                "p95_latency_ms": lat[min(len(lat) - 1, int(len(lat) * 0.95))],
                "failures": errors,
            }
        )
    return rows


def to_dict(outcome: RequestOutcome) -> Dict:
    return asdict(outcome)
