"""Per-minute analytics rollup, maintained asynchronously by
events/consumers/analytics_consumer.py off the auction-events topic
(Section 9: "Do NOT perform expensive analytics synchronously inside the
auction request").

One row per minute bucket. Latency is stored as per-bucket counts (see
services/analytics/percentiles.py) rather than raw values, so a single
UPSERT per event keeps this table's write cost O(1) regardless of traffic
volume, and reading N minutes of history means summing N small rows instead
of scanning the full auction table.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.services.analytics.percentiles import LATENCY_BUCKETS_MS


class AuctionMinuteRollup(Base):
    __tablename__ = "auction_minute_rollup"

    minute_bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    total_auctions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    completed_auctions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    no_bid_auctions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failed_auctions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    sum_winning_bid: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    count_winning_bid: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # One column per latency histogram bucket, matching LATENCY_BUCKETS_MS
    # in order, plus a trailing +Inf overflow bucket.
    bucket_5: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bucket_10: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bucket_20: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bucket_30: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bucket_50: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bucket_75: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bucket_100: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bucket_150: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bucket_200: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bucket_300: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bucket_500: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bucket_1000: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bucket_inf: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


BUCKET_COLUMN_NAMES = [f"bucket_{int(b)}" for b in LATENCY_BUCKETS_MS] + ["bucket_inf"]
assert len(BUCKET_COLUMN_NAMES) == len(LATENCY_BUCKETS_MS) + 1