from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auction import Auction
from app.models.bid import Bid
from app.schemas.analytics import AnalyticsOverview


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