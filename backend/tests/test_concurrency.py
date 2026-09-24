import asyncio
import time
import uuid

import httpx
import pytest

from app.models.dsp import DSP
from app.services.bidding.client import BidRequestContext, collect_bids
from app.services.bidding.types import BidStatus


def make_dsp(name: str, timeout_ms: int) -> DSP:
    return DSP(id=uuid.uuid4(), name=name, endpoint=f"http://{name}", timeout_ms=timeout_ms, status="ACTIVE")


def transport_with_delays(delays_ms: dict[str, int], campaign_id: str):
    """A fake httpx transport where each DSP (identified by host) responds
    after its configured delay -- lets us test real concurrency (all DSPs
    called in parallel, not sequentially) without any network I/O."""

    async def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        delay_ms = delays_ms.get(host, 0)
        await asyncio.sleep(delay_ms / 1000)
        return httpx.Response(200, json={"campaign_id": campaign_id, "amount": 3.0, "quality_score": 0.8})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_dsps_are_called_concurrently_not_sequentially():
    """If DSPs were called sequentially, three DSPs at 40ms each would take
    ~120ms. Concurrently, they should all finish in ~40ms (plus overhead)."""
    campaign_id = str(uuid.uuid4())
    dsps = [make_dsp("dsp-a", 200), make_dsp("dsp-b", 200), make_dsp("dsp-c", 200)]
    delays = {"dsp-a": 40, "dsp-b": 40, "dsp-c": 40}
    transport = transport_with_delays(delays, campaign_id)

    async with httpx.AsyncClient(transport=transport) as client:
        ctx = BidRequestContext("req1", uuid.uuid4(), "US", "mobile")
        start = time.perf_counter()
        results = await collect_bids(dsps, ctx, global_timeout_ms=500, http_client=client)
        elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(results) == 3
    assert all(r.status == BidStatus.VALID for r in results)
    # Generous upper bound: sequential would be ~120ms; concurrent should be well under 100ms.
    assert elapsed_ms < 100


@pytest.mark.asyncio
async def test_slow_dsp_times_out_without_blocking_others():
    campaign_id = str(uuid.uuid4())
    dsps = [make_dsp("dsp-fast", 100), make_dsp("dsp-slow", 30)]
    delays = {"dsp-fast": 10, "dsp-slow": 500}  # dsp-slow exceeds its own 30ms timeout
    transport = transport_with_delays(delays, campaign_id)

    async with httpx.AsyncClient(transport=transport) as client:
        ctx = BidRequestContext("req2", uuid.uuid4(), "US", "mobile")
        results = await collect_bids(dsps, ctx, global_timeout_ms=200, http_client=client)

    by_name = {r.dsp_name: r for r in results}
    assert by_name["dsp-fast"].status == BidStatus.VALID
    assert by_name["dsp-slow"].status == BidStatus.TIMEOUT


@pytest.mark.asyncio
async def test_global_timeout_caps_total_auction_time_even_with_many_slow_dsps():
    campaign_id = str(uuid.uuid4())
    dsps = [make_dsp(f"dsp-{i}", 500) for i in range(5)]  # generous per-DSP timeout
    delays = {f"dsp-{i}": 500 for i in range(5)}  # all DSPs are slow
    transport = transport_with_delays(delays, campaign_id)

    async with httpx.AsyncClient(transport=transport) as client:
        ctx = BidRequestContext("req3", uuid.uuid4(), "US", "mobile")
        start = time.perf_counter()
        results = await collect_bids(dsps, ctx, global_timeout_ms=100, http_client=client)
        elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(results) == 5
    assert all(r.status == BidStatus.TIMEOUT for r in results)
    # The auction must still complete near the global deadline, not wait for the DSPs.
    assert elapsed_ms < 200


@pytest.mark.asyncio
async def test_dsp_error_produces_invalid_bid_not_an_exception():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    dsps = [make_dsp("dsp-broken", 100)]
    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=transport) as client:
        ctx = BidRequestContext("req4", uuid.uuid4(), "US", "mobile")
        results = await collect_bids(dsps, ctx, global_timeout_ms=200, http_client=client)

    assert results[0].status == BidStatus.INVALID
