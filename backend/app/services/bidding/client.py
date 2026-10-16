"""Concurrent DSP fan-out (Section 5 of the spec).

Design:

- Every eligible DSP is called concurrently via asyncio, never sequentially.
- Each DSP call has its OWN timeout (dsp.timeout_ms), passed to httpx so the
  client times the request out itself.
- The whole fan-out additionally has a GLOBAL deadline (AUCTION_GLOBAL_TIMEOUT_MS),
  enforced with asyncio.wait: when it fires, the auction stops waiting -- a
  single slow DSP (or several) can never hold the auction open past the
  deadline.
- In-flight DSP calls are never cancelled from outside. Cancelling an httpx
  request mid-flight can leave its pooled connection stuck, and under load
  those stuck connections exhaust the shared pool until every DSP call times
  out, even to healthy DSPs. A call the auction stopped waiting for keeps
  running in the background and ends at its own httpx timeout.
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
from app.core.tracing import tracer
from app.models.dsp import DSP
from app.services.bidding.types import BidStatus, RawBid

logger = get_logger(__name__)


def _discard_result(task: asyncio.Future) -> None:
    """Retrieve a background task's outcome so asyncio doesn't warn about it."""
    if not task.cancelled():
        task.exception()


async def _post_without_cancelling(
    client: httpx.AsyncClient, url: str, payload: dict, timeout_s: float
) -> httpx.Response:
    """POST with a deadline that never cancels the request (see module doc).

    httpx enforces timeout_s itself; the asyncio.wait is a backstop for when
    it doesn't (e.g. timeouts that apply per phase, or mock transports). On
    the backstop path the request is left to finish in the background.
    """
    task = asyncio.ensure_future(client.post(url, json=payload, timeout=httpx.Timeout(timeout_s)))
    done, _ = await asyncio.wait({task}, timeout=timeout_s)
    if not done:
        task.add_done_callback(_discard_result)
        raise asyncio.TimeoutError
    return task.result()


class BidRequestContext:
    def __init__(self, request_id: str, ad_slot_id: uuid.UUID, country: str, device: str):
        self.request_id = request_id
        self.ad_slot_id = ad_slot_id
        self.country = country
        self.device = device


async def _call_one_dsp(
    client: httpx.AsyncClient, dsp: DSP, ctx: BidRequestContext
) -> RawBid:
    with tracer.start_as_current_span("dsp.bid") as span:
        span.set_attribute("dsp.name", dsp.name)
        span.set_attribute("dsp.timeout_ms", dsp.timeout_ms)
        bid = await _call_one_dsp_untraced(client, dsp, ctx)
        span.set_attribute("dsp.outcome", bid.status.value)
        span.set_attribute("dsp.response_time_ms", bid.response_time_ms)
        return bid


async def _call_one_dsp_untraced(
    client: httpx.AsyncClient, dsp: DSP, ctx: BidRequestContext
) -> RawBid:
    start = time.perf_counter()
    timeout_s = dsp.timeout_ms / 1000
    try:
        response = await _post_without_cancelling(
            client,
            f"{dsp.endpoint}/bid",
            {
                "request_id": ctx.request_id,
                "ad_slot_id": str(ctx.ad_slot_id),
                "country": ctx.country,
                "device": ctx.device,
            },
            timeout_s,
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

    except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        DSP_TIMEOUT_TOTAL.labels(dsp_name=dsp.name).inc()
        # Which phase timed out (PoolTimeout, ConnectTimeout, ReadTimeout, or
        # TimeoutError for our own backstop) separates a slow DSP from a
        # starved client.
        logger.info("dsp_timeout", dsp_name=dsp.name, elapsed_ms=elapsed_ms, budget_ms=dsp.timeout_ms,
                    reason=type(exc).__name__)
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
    with tracer.start_as_current_span("dsp.fanout") as span:
        span.set_attribute("auction.global_timeout_ms", global_timeout_ms)
        span.set_attribute("dsp.count", len(dsps))
        results, deadline_hit = await _collect_bids(dsps, ctx, global_timeout_ms, http_client)
        span.set_attribute("dsp.deadline_hit", deadline_hit)
        span.set_attribute("dsp.timeouts", sum(r.status == BidStatus.TIMEOUT for r in results))
        return results


async def _collect_bids(
    dsps: list[DSP],
    ctx: BidRequestContext,
    global_timeout_ms: int,
    http_client: httpx.AsyncClient,
) -> tuple[list[RawBid], bool]:
    tasks = [asyncio.create_task(_call_one_dsp(http_client, dsp, ctx)) for dsp in dsps]
    if not tasks:
        return [], False

    _, pending = await asyncio.wait(tasks, timeout=global_timeout_ms / 1000)
    if pending:
        # Global deadline hit: collect partial results instead of failing the
        # whole auction. Unfinished calls are not cancelled (see module doc).
        logger.warning("auction_global_timeout", request_id=ctx.request_id, deadline_ms=global_timeout_ms)
    results: list = []
    for dsp, task in zip(dsps, tasks):
        if task in pending:
            task.add_done_callback(_discard_result)
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
        else:
            results.append(task.exception() or task.result())

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
    return final, bool(pending)
