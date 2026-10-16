"""HTTP transport for DSP calls that cannot be wedged by pool timeouts.

httpcore's connection pool (1.0.x) can leak a connection slot. When a queued
request is handed a brand-new connection at the same moment its pool timeout
fires, the request gives up before it ever starts connecting. The pool drops
the request but keeps the connection, which stays in the CONNECTING state
forever: it is not available, not idle and not closed, so nothing ever
removes it. DSP calls use pool timeouts of tens of milliseconds, so a burst
of auctions hits this race often, and once every slot has leaked the client
can never reach any DSP again (every call ends at its timeout) until the
process restarts.

DSPTransport removes those orphaned connections whenever a request fails, so
leaked slots go back to the pool straight away.
"""
from __future__ import annotations

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

# Explicit so the pool size is visible here; these are httpx's defaults.
DSP_POOL_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)


def _drop_orphaned_connections(pool) -> int:
    """Remove connections that never started connecting and that no request
    is waiting to use. Returns how many were removed.

    A connection that is still CONNECTING is always owned by the request it
    was created for until that request's connect attempt finishes (success or
    failure). If no request in the pool holds it, nothing ever will.
    """
    in_use = {id(r.connection) for r in pool._requests if r.connection is not None}
    orphaned = [c for c in pool._connections if c.info() == "CONNECTING" and id(c) not in in_use]
    for connection in orphaned:
        pool._connections.remove(connection)
    return len(orphaned)


class DSPTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            return await super().handle_async_request(request)
        except BaseException:
            pool = self._pool
            with pool._optional_thread_lock:
                dropped = _drop_orphaned_connections(pool)
                # Hand the freed slots to requests already queued for one.
                closing = pool._assign_requests_to_connections() if dropped else []
            if dropped:
                logger.info("dsp_pool_orphans_dropped", count=dropped)
                await pool._close_connections(closing)
            raise


def make_dsp_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=DSPTransport(limits=DSP_POOL_LIMITS))
