"""Sliding-window rate limiter backed by Redis sorted sets.

Why sliding window over a fixed token bucket for this project: a fixed
window (e.g. "1000/min, reset on the minute boundary") allows a burst of
2x the limit right at the boundary (999 requests at 0:59, 999 more at
1:00). A sliding window log, implemented with a Redis sorted set keyed by
timestamp, gives an accurate rolling count at the cost of O(log n) per
request instead of O(1) -- an acceptable trade-off at the throughput this
project targets (thousands/sec, not millions).

Algorithm per request:
  1. ZREMRANGEBYSCORE key 0 (now - window)   -- drop entries older than window
  2. ZCARD key                                -- count remaining entries
  3. if count >= limit: reject
  4. else: ZADD key now member=uuid; EXPIRE key window; allow

Steps 1-4 are pipelined for a single round trip. If Redis is unavailable,
the limiter fails OPEN (allows the request) rather than closed, so a Redis
outage degrades to "no rate limiting" instead of "API totally down" --
consistent with Redis being a latency/protection optimization, not the
system of record.
"""
from __future__ import annotations

import time
import uuid

import redis.asyncio as redis

from app.core.logging import get_logger
from app.core.metrics import RATE_LIMIT_REJECTIONS_TOTAL

logger = get_logger(__name__)

WINDOW_SECONDS = 60


async def is_allowed(client: redis.Redis, role: str, identity: str, limit_per_min: int) -> bool:
    key = f"ratelimit:{role}:{identity}"
    now = time.time()
    window_start = now - WINDOW_SECONDS
    member = f"{now}:{uuid.uuid4()}"

    try:
        pipe = client.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        pipe.zadd(key, {member: now})
        pipe.expire(key, WINDOW_SECONDS)
        _, count, *_ = await pipe.execute()
    except Exception as exc:  # noqa: BLE001 - fail open on Redis outage
        logger.warning("rate_limiter_redis_unavailable", error=str(exc))
        return True

    allowed = count < limit_per_min
    if not allowed:
        RATE_LIMIT_REJECTIONS_TOTAL.labels(role=role).inc()
    return allowed
