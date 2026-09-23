"""Analytics consumer.

Consumes AUCTION_COMPLETED / AUCTION_NO_BID events and writes lightweight
rollups. Kept intentionally simple: in this project the analytics API
(app/api/v1/analytics.py) reads directly from the auction/bid tables for
correctness and simplicity, so this consumer's job here is to demonstrate
the asynchronous pipeline (Section 9) and to be the place where a real
system would maintain pre-aggregated read models (e.g. per-minute rollups
in a separate table) to keep the analytics endpoints fast at scale.
"""
from __future__ import annotations

from app.core.logging import get_logger

logger = get_logger(__name__)


async def handle_analytics_event(payload: dict) -> None:
    logger.info(
        "analytics_event_processed",
        event_type=payload.get("event_type"),
        auction_id=payload.get("auction_id"),
        latency_ms=payload.get("latency_ms"),
    )
    # A production system would upsert into a rollup table here, e.g.:
    #   INSERT INTO auction_minute_rollup (...) ON CONFLICT (...) DO UPDATE ...
    # Left as a documented extension point -- see docs/architecture.md Section 6.