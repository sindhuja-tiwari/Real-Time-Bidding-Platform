import pytest

from app.core.rate_limit import is_allowed


@pytest.mark.asyncio
async def test_rate_limiter_allows_under_limit():
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis()
    for _ in range(5):
        allowed = await is_allowed(client, "PUBLISHER", "pub-1", limit_per_min=10)
        assert allowed is True


@pytest.mark.asyncio
async def test_rate_limiter_rejects_over_limit():
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis()
    results = [await is_allowed(client, "PUBLISHER", "pub-2", limit_per_min=5) for _ in range(7)]
    assert results.count(True) == 5
    assert results.count(False) == 2


@pytest.mark.asyncio
async def test_rate_limiter_is_per_identity():
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis()
    for _ in range(5):
        assert await is_allowed(client, "PUBLISHER", "pub-a", limit_per_min=5) is True
    # A different identity has its own independent budget.
    assert await is_allowed(client, "PUBLISHER", "pub-b", limit_per_min=5) is True


@pytest.mark.asyncio
async def test_rate_limiter_fails_open_when_redis_unavailable():
    class BrokenRedis:
        def pipeline(self):
            raise ConnectionError("redis is down")

    allowed = await is_allowed(BrokenRedis(), "PUBLISHER", "pub-3", limit_per_min=1)
    assert allowed is True  # fail open, not closed
