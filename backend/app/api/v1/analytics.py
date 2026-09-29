from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.analytics import AnalyticsOverview, AuctionCountBucket, LatencyBucket
from app.services.analytics.service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
async def analytics_overview(db: AsyncSession = Depends(get_db)):
    """Live query over the raw auction/bid tables -- simple and always
    correct, at the cost of scanning those tables on every request. See
    /auctions and /latency below for the rollup-backed alternative."""
    service = AnalyticsService(db)
    return await service.overview()


@router.get("/auctions", response_model=list[AuctionCountBucket])
async def analytics_auctions_timeseries(minutes: int = 60, db: AsyncSession = Depends(get_db)):
    """Per-minute auction counts from auction_minute_rollup, maintained
    asynchronously by the Kafka analytics consumer (Section 9: kept off the
    auction's critical path). Eventually consistent with the raw tables."""
    service = AnalyticsService(db)
    return await service.auctions_timeseries(minutes)


@router.get("/latency", response_model=list[LatencyBucket])
async def analytics_latency_timeseries(minutes: int = 60, db: AsyncSession = Depends(get_db)):
    """Per-minute P50/P95/P99 latency, estimated from histogram bucket
    counts in auction_minute_rollup (same technique as Prometheus's
    histogram_quantile -- see services/analytics/percentiles.py)."""
    service = AnalyticsService(db)
    return await service.latency_timeseries(minutes)
