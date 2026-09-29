from __future__ import annotations

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics_rollup import BUCKET_COLUMN_NAMES, AuctionMinuteRollup
from app.models.auction import Auction
from app.models.bid import Bid
from app.schemas.analytics import AnalyticsOverview, AuctionCountBucket, LatencyBucket
from app.services.analytics.percentiles import estimate_percentile


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def overview(self) -> AnalyticsOverview:
        total_stmt = select(func.count(Auction.id))
        total = (await self.db.execute(total_stmt)).scalar_one()

        def count_status(status: str):
            return select(func.count(Auction.id)).where(Auction.status == status)

        completed = (await self.db.execute(count_status("COMPLETED"))).scalar_one()
        no_bid = (await self.db.execute(count_status("NO_BID"))).scalar_one()
        failed = (await self.db.execute(count_status("FAILED"))).scalar_one()

        latency_rows = (
            await self.db.execute(
                select(Auction.duration_ms).where(Auction.duration_ms.is_not(None))
            )
        ).scalars().all()
        latencies = sorted(latency_rows)

        def percentile(p: float) -> float:
            if not latencies:
                return 0.0
            idx = min(int(len(latencies) * p), len(latencies) - 1)
            return float(latencies[idx])

        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        avg_bid_row = (
            await self.db.execute(select(func.avg(Bid.amount)).where(Bid.status == "WON"))
        ).scalar_one()

        return AnalyticsOverview(
            total_auctions=total,
            completed_auctions=completed,
            no_bid_auctions=no_bid,
            failed_auctions=failed,
            win_rate=(completed / total) if total else 0.0,
            avg_latency_ms=round(avg_latency, 2),
            p50_latency_ms=percentile(0.50),
            p95_latency_ms=percentile(0.95),
            p99_latency_ms=percentile(0.99),
            avg_winning_bid=round(float(avg_bid_row), 4) if avg_bid_row else 0.0,
        )

    async def _rollup_rows(self, minutes: int) -> list[AuctionMinuteRollup]:
        """Reads from auction_minute_rollup, the table maintained
        asynchronously by events/consumers/analytics_consumer.py -- NOT the
        raw auction table. This is what keeps these two endpoints fast
        regardless of how many auctions have ever run, at the cost of the
        numbers reflecting whatever the consumer has processed so far
        (eventually consistent, not read-your-writes)."""
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        stmt = (
            select(AuctionMinuteRollup)
            .where(AuctionMinuteRollup.minute_bucket >= since)
            .order_by(AuctionMinuteRollup.minute_bucket.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def latency_timeseries(self, minutes: int = 60) -> list[LatencyBucket]:
        rows = await self._rollup_rows(minutes)
        buckets: list[LatencyBucket] = []
        for row in rows:
            counts = [getattr(row, col) for col in BUCKET_COLUMN_NAMES]
            total = sum(counts)
            buckets.append(
                LatencyBucket(
                    bucket_start=row.minute_bucket.isoformat(),
                    p50_latency_ms=estimate_percentile(counts, 0.50),
                    p95_latency_ms=estimate_percentile(counts, 0.95),
                    p99_latency_ms=estimate_percentile(counts, 0.99),
                    count=total,
                )
            )
        return buckets

    async def auctions_timeseries(self, minutes: int = 60) -> list[AuctionCountBucket]:
        rows = await self._rollup_rows(minutes)
        return [
            AuctionCountBucket(
                bucket_start=row.minute_bucket.isoformat(),
                total_auctions=row.total_auctions,
                completed_auctions=row.completed_auctions,
                no_bid_auctions=row.no_bid_auctions,
                failed_auctions=row.failed_auctions,
                avg_winning_bid=round(float(row.sum_winning_bid) / row.count_winning_bid, 4)
                if row.count_winning_bid
                else 0.0,
            )
            for row in rows
        ]
