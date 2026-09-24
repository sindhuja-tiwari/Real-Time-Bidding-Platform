"""Redis client + graceful-degradation wrapper.

Section 8/14 of the spec: Redis is used for low-latency cache-aside reads,
budget-reservation fast path, and rate limiting. If Redis is unavailable,
the auction path must still work by falling back to Postgres and skipping
non-critical features (rate limiting fails open, not closed, so a Redis
outage does not take down the whole platform).
"""
from __future__ import annotations

import redis.asyncio as redis

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

_pool = redis.ConnectionPool.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    max_connections=50,
)


def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)


class RedisUnavailable(Exception):
    pass


async def safe_get(client: redis.Redis, key: str) -> str | None:
    """Read from Redis, treating any failure as a cache miss rather than a
    hard error, so the caller falls back to Postgres."""
    try:
        return await client.get(key)
    except Exception as exc:  # noqa: BLE001 - intentional broad catch: degrade, don't crash
        logger.warning("redis_unavailable", operation="get", key=key, error=str(exc))
        return None


async def safe_set(client: redis.Redis, key: str, value: str, ttl: int) -> None:
    try:
        await client.set(key, value, ex=ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_unavailable", operation="set", key=key, error=str(exc))


async def safe_delete(client: redis.Redis, *keys: str) -> None:
    try:
        if keys:
            await client.delete(*keys)
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_unavailable", operation="delete", keys=keys, error=str(exc))
