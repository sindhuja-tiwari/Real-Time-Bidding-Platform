"""Analytics consumer.

Consumes AUCTION_COMPLETED / AUCTION_NO_BID events (Section 9: this runs
asynchronously, off the auction's critical path) and maintains the
per-minute rollup table (`auction_minute_rollup`) that
`GET /api/v1/analytics/latency` and `GET /api/v1/analytics/auctions` read
from. A single UPSERT per event keeps this O(1) per event regardless of
total auction volume -- the alternative (querying the raw auction/bid
tables for every analytics request) is what `GET /api/v1/analytics/overview`
still does, deliberately kept as the simple/always-correct baseline; this
consumer is what lets the time-series endpoints stay fast as that table
grows into the millions of rows.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.analytics_rollup import BUCKET_COLUMN_NAMES
from app.services.analytics.percentiles import bucket_index_for

logger = get_logger(__name__)


def _minute_bucket(iso_timestamp: str) -> datetime:
    ts = datetime.fromisoformat(iso_timestamp)
    return ts.replace(second=0, microsecond=0)


async def handle_analytics_event(payload: dict) -> None:
    event_type = payload.get("event_type")
    if event_type not in ("AUCTION_COMPLETED", "AUCTION_NO_BID"):
        return

    minute = _minute_bucket(payload["timestamp"])
    status = payload.get("status", "NO_BID")
    latency_ms = payload.get("latency_ms") or 0
    winning_bid = payload.get("winning_bid")

    bucket_col = BUCKET_COLUMN_NAMES[bucket_index_for(latency_ms)]

    completed = 1 if status == "COMPLETED" else 0
    no_bid = 1 if status == "NO_BID" else 0
    failed = 1 if status == "FAILED" else 0
    bid_sum = float(winning_bid) if winning_bid else 0.0
    bid_count = 1 if winning_bid else 0

    # Single-statement UPSERT: the only column that needs a dynamic name is
    # the latency bucket, so it's the one piece of the query built with an
    # f-string -- safe here because bucket_col is drawn from a fixed,
    # code-defined whitelist (BUCKET_COLUMN_NAMES), never from user input.
    sql = text(
        f"""
        INSERT INTO auction_minute_rollup (
            minute_bucket, total_auctions, completed_auctions, no_bid_auctions,
            failed_auctions, sum_winning_bid, count_winning_bid, {bucket_col}
        ) VALUES (
            :minute, 1, :completed, :no_bid, :failed, :bid_sum, :bid_count, 1
        )
        ON CONFLICT (minute_bucket) DO UPDATE SET
            total_auctions = auction_minute_rollup.total_auctions + 1,
            completed_auctions = auction_minute_rollup.completed_auctions + :completed,
            no_bid_auctions = auction_minute_rollup.no_bid_auctions + :no_bid,
            failed_auctions = auction_minute_rollup.failed_auctions + :failed,
            sum_winning_bid = auction_minute_rollup.sum_winning_bid + :bid_sum,
            count_winning_bid = auction_minute_rollup.count_winning_bid + :bid_count,
            {bucket_col} = auction_minute_rollup.{bucket_col} + 1
        """
    )

    async with AsyncSessionLocal() as db:
        await db.execute(
            sql,
            {
                "minute": minute,
                "completed": completed,
                "no_bid": no_bid,
                "failed": failed,
                "bid_sum": bid_sum,
                "bid_count": bid_count,
            },
        )
        await db.commit()

    logger.info(
        "analytics_rollup_updated",
        minute=minute.isoformat(),
        event_type=event_type,
        auction_id=payload.get("auction_id"),
        latency_ms=latency_ms,
    )
