"""Concurrent DSP fan-out (Section 5 of the spec).

Design:

- Every eligible DSP is called concurrently via asyncio, never sequentially.
- Each DSP call has its OWN timeout (dsp.timeout_ms), enforced with
  asyncio.wait_for around the individual httpx call.
- The whole fan-out additionally has a GLOBAL deadline (AUCTION_GLOBAL_TIMEOUT_MS).
  asyncio.wait_for around asyncio.gather(..., return_exceptions=True) enforces
  this: if the global deadline fires, gather is cancelled, which cancels any
  DSP tasks still in flight -- a single slow DSP (or several) can never hold
  the auction open past the deadline.
- A DSP task that times out, errors, or is cancelled produces a RawBid with
  status=TIMEOUT (not an exception bubbling up) so the caller always gets a
  full list of per-DSP outcomes to log/persist, including the losers.
"""
from __future__ import annotations

import asyncio
import time
import uuid

import httpx

from app.core.logging import get_logger
from app.core.metrics import DSP_ERROR_TOTAL, DSP_RESPONSE_LATENCY_MS, DSP_TIMEOUT_TOTAL
from app.models.dsp import DSP
from app.services.bidding.types import BidStatus, RawBid

logger = get_logger(__name__)


class BidRequestContext:
    def __init__(self, request_id: str, ad_slot_id: uuid.UUID, country: str, device: str):
        self.request_id = request_id
        self.ad_slot_id = ad_slot_id
        self.country = country
        self.device = device


async def _call_one_dsp(
    client: httpx.AsyncClient, dsp: DSP, ctx: BidRequestContext
) -> RawBid:
    start = time.perf_counter()
    timeout_s = dsp.timeout_ms / 1000
    try:
        response = await asyncio.wait_for(
            client.post(
                f"{dsp.endpoint}/bid",
                json={
                    "request_id": ctx.request_id,
                    "ad_slot_id": str(ctx.ad_slot_id),
                    "country": ctx.country,
                    "device": ctx.device,
                },
            ),
            timeout=timeout_s,
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        DSP_RESPONSE_LATENCY_MS.labels(dsp_name=dsp.name).observe(elapsed_ms)

        if response.status_code == 204:
            # DSP explicitly declined to bid (e.g. no matching campaign)
            return RawBid(
                dsp_id=dsp.id,
                dsp_name=dsp.name,
                campaign_id=uuid.UUID(int=0),
                amount=0,
                quality_score=0,
                response_time_ms=elapsed_ms,
                status=BidStatus.INVALID,
            )
        if response.status_code != 200:
            DSP_ERROR_TOTAL.labels(dsp_name=dsp.name).inc()
            return RawBid(
                dsp_id=dsp.id,
                dsp_name=dsp.name,
                campaign_id=uuid.UUID(int=0),
                amount=0,
                quality_score=0,
                response_time_ms=elapsed_ms,
                status=BidStatus.INVALID,
            )

        data = response.json()
        return RawBid(
            dsp_id=dsp.id,
            dsp_name=dsp.name,
            campaign_id=uuid.UUID(data["campaign_id"]),
            amount=float(data["amount"]),
            quality_score=float(data.get("quality_score", 0.8)),
            response_time_ms=elapsed_ms,
            status=BidStatus.VALID,
        )

    except (asyncio.TimeoutError, httpx.TimeoutException):
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        DSP_TIMEOUT_TOTAL.labels(dsp_name=dsp.name).inc()
        logger.info("dsp_timeout", dsp_name=dsp.name, elapsed_ms=elapsed_ms, budget_ms=dsp.timeout_ms)
        return RawBid(
            dsp_id=dsp.id,
            dsp_name=dsp.name,
            campaign_id=uuid.UUID(int=0),
            amount=0,
            quality_score=0,
            response_time_ms=elapsed_ms,
            status=BidStatus.TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 - a single DSP's failure must not sink the auction
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        DSP_ERROR_TOTAL.labels(dsp_name=dsp.name).inc()
        logger.warning("dsp_error", dsp_name=dsp.name, error=str(exc))
        return RawBid(
            dsp_id=dsp.id,
            dsp_name=dsp.name,
            campaign_id=uuid.UUID(int=0),
            amount=0,
            quality_score=0,
            response_time_ms=elapsed_ms,
            status=BidStatus.INVALID,
        )


async def collect_bids(
    dsps: list[DSP],
    ctx: BidRequestContext,
    global_timeout_ms: int,
    http_client: httpx.AsyncClient,
) -> list[RawBid]:
    """Fan out to every DSP concurrently, respect per-DSP timeouts, and
    enforce a hard global deadline. Always returns len(dsps) results -- a
    DSP that never responds in time shows up as a TIMEOUT bid, not a missing
    entry, so downstream logging/analytics has a complete picture."""
    tasks = [asyncio.create_task(_call_one_dsp(http_client, dsp, ctx)) for dsp in dsps]

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=global_timeout_ms / 1000,
        )
    except asyncio.TimeoutError:
        # Global deadline hit: cancel whatever is still running and collect
        # partial results instead of failing the whole auction.
        logger.warning("auction_global_timeout", request_id=ctx.request_id, deadline_ms=global_timeout_ms)
        results = []
        for dsp, task in zip(dsps, tasks):
            if task.done() and not task.cancelled():
                results.append(task.result())
            else:
                task.cancel()
                results.append(
                    RawBid(
                        dsp_id=dsp.id,
                        dsp_name=dsp.name,
                        campaign_id=uuid.UUID(int=0),
                        amount=0,
                        quality_score=0,
                        response_time_ms=global_timeout_ms,
                        status=BidStatus.TIMEOUT,
                    )
                )
        # let cancellations settle without propagating CancelledError
        await asyncio.gather(*tasks, return_exceptions=True)

    # Any raw exception objects (shouldn't normally happen -- _call_one_dsp
    # catches broadly -- but this is a defensive backstop) become TIMEOUT bids.
    final: list[RawBid] = []
    for dsp, r in zip(dsps, results):
        if isinstance(r, RawBid):
            final.append(r)
        else:
            final.append(
                RawBid(
                    dsp_id=dsp.id,
                    dsp_name=dsp.name,
                    campaign_id=uuid.UUID(int=0),
                    amount=0,
                    quality_score=0,
                    response_time_ms=global_timeout_ms,
                    status=BidStatus.INVALID,
                )
            )
    return final