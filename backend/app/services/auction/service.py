"""AuctionService: orchestrates a single auction end to end.

This is deliberately the only place that knows the full sequence from
Section 4 of the spec. Each step delegates to a focused collaborator so the
sequence itself stays readable and testable:

  1. idempotency check                -> AuctionRepository.get_by_request_id
  2. eligible campaigns/DSPs          -> CampaignService / DSPService (cache-aside)
  3. concurrent bid collection        -> bidding.client.collect_bids (asyncio)
  4. validation                       -> bidding.validation.validate_bid
  5. ranking / winner selection       -> bidding.strategies.AuctionStrategy
  6. atomic budget reservation        -> CampaignRepository.reserve_budget (SELECT FOR UPDATE)
  7. persistence                      -> AuctionRepository
  8. fire-and-forget event publish    -> events.producer (never awaited by the response)
"""
from __future__ import annotations

import time
import uuid

import httpx
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import auction_id_var, get_logger
from app.core.metrics import (
    AUCTION_COMPLETED_TOTAL,
    AUCTION_FAILED_TOTAL,
    AUCTION_LATENCY_MS,
    AUCTION_NO_BID_TOTAL,
    AUCTION_REQUESTS_TOTAL,
    BID_TOTAL,
    WINNING_BID_VALUE,
)
from app.events.producer import publish_auction_completed
from app.models.bid import Bid
from app.repositories.auction_repository import AuctionRepository
from app.repositories.support_repositories import AdSlotRepository, CreativeRepository
from app.schemas.auction import AuctionRequest, AuctionResponse, BidResponse
from app.services.bidding.client import BidRequestContext, collect_bids
from app.services.bidding.strategies import get_strategy
from app.services.bidding.types import BidStatus, RawBid
from app.services.bidding.validation import validate_bid
from app.services.campaign.service import CampaignService
from app.services.dsp.service import DSPService

settings = get_settings()
logger = get_logger(__name__)

_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient()
    return _http_client


class AuctionService:
    def __init__(self, db: AsyncSession, redis_client: redis.Redis):
        self.db = db
        self.redis = redis_client
        self.auction_repo = AuctionRepository(db)
        self.ad_slot_repo = AdSlotRepository(db)
        self.creative_repo = CreativeRepository(db)
        self.campaign_service = CampaignService(db, redis_client)
        self.dsp_service = DSPService(db, redis_client)

    async def run_auction(self, request: AuctionRequest) -> AuctionResponse:
        AUCTION_REQUESTS_TOTAL.inc()

        # ---- 1. Idempotency: same request_id never runs twice ----
        existing = await self.auction_repo.get_by_request_id(request.request_id)
        if existing is not None:
            logger.info("auction_idempotent_replay", request_id=request.request_id)
            return await self._to_response(existing)

        ad_slot = await self.ad_slot_repo.get_or_create_default(
            request.ad_slot.id, request.ad_slot.width, request.ad_slot.height
        )

        auction = await self.auction_repo.create_pending(request.request_id, ad_slot.id)
        if auction is None:
            # Lost the INSERT race to a concurrent identical request.
            existing = await self.auction_repo.get_by_request_id(request.request_id)
            return await self._to_response(existing)

        auction_id_var.set(str(auction.id))
        start = time.perf_counter()

        try:
            response = await self._execute(auction, ad_slot, request)
            AUCTION_COMPLETED_TOTAL.inc() if response.winning_bid_id else AUCTION_NO_BID_TOTAL.inc()
            return response
        except Exception:
            AUCTION_FAILED_TOTAL.inc()
            duration_ms = int((time.perf_counter() - start) * 1000)
            await self.auction_repo.finalize(auction, "FAILED", duration_ms, None)
            logger.error("auction_failed", request_id=request.request_id, exc_info=True)
            raise
        finally:
            AUCTION_LATENCY_MS.observe(int((time.perf_counter() - start) * 1000))
            auction_id_var.set(None)

    async def _execute(self, auction, ad_slot, request: AuctionRequest) -> AuctionResponse:
        start = time.perf_counter()

        # ---- 2. Eligible campaigns + active DSPs (cache-aside) ----
        eligible_campaigns = await self.campaign_service.list_eligible(
            request.user.country, request.user.device
        )
        active_dsps = await self.dsp_service.list_active_cached()

        if not eligible_campaigns or not active_dsps:
            duration_ms = int((time.perf_counter() - start) * 1000)
            await self.auction_repo.finalize(auction, "NO_BID", duration_ms, None)
            return AuctionResponse(
                id=auction.id, request_id=auction.request_id, ad_slot_id=ad_slot.id,
                status="NO_BID", duration_ms=duration_ms, winning_bid_id=None,
                started_at=auction.started_at, completed_at=auction.completed_at,
            )

        # ---- 3. Concurrent bid collection ----
        ctx = BidRequestContext(
            request_id=request.request_id, ad_slot_id=ad_slot.id,
            country=request.user.country, device=request.user.device,
        )
        raw_bids = await collect_bids(
            active_dsps, ctx, settings.AUCTION_GLOBAL_TIMEOUT_MS, get_http_client()
        )

        # ---- 4. Validate each bid against the campaign it targets ----
        campaign_by_id = {c.id: c for c in eligible_campaigns}
        validated: list[RawBid] = []
        for bid in raw_bids:
            snapshot = await self.campaign_service.get_cached_snapshot(bid.campaign_id) \
                if bid.campaign_id in campaign_by_id else None
            validated.append(validate_bid(bid, snapshot, ad_slot.floor_price, request.user.country, request.user.device))
            BID_TOTAL.labels(status=validated[-1].status.value).inc()

        # ---- 5. Rank & select winner ----
        strategy = get_strategy(settings.AUCTION_DEFAULT_TYPE)
        result = strategy.select(validated, ad_slot.floor_price)

        winning_bid_row: Bid | None = None
        budget_ok = True
        if result.winner is not None:
            # ---- 6. Atomic budget reservation ----
            budget_ok = await self.campaign_service.reserve_budget(
                result.winner.campaign_id, result.clearing_price or result.winner.amount
            )
            if not budget_ok:
                result.winner.status = BidStatus.BUDGET_EXCEEDED

        # ---- 7. Persist all bids ----
        bid_rows = [
            Bid(
                auction_id=auction.id, dsp_id=b.dsp_id, campaign_id=b.campaign_id,
                amount=b.amount, response_time_ms=b.response_time_ms,
                status=(BidStatus.WON.value if (result.winner is b and budget_ok) else
                        (BidStatus.LOST.value if b.status == BidStatus.VALID else b.status.value)),
            )
            for b in validated
        ]
        await self.auction_repo.save_bids(bid_rows)

        winning_bid_id = None
        clearing_price = None
        if result.winner is not None and budget_ok:
            for row, b in zip(bid_rows, validated):
                if b is result.winner:
                    winning_bid_row = row
                    winning_bid_id = row.id
                    clearing_price = result.clearing_price
                    break

        duration_ms = int((time.perf_counter() - start) * 1000)
        status = "COMPLETED" if winning_bid_id else "NO_BID"
        await self.auction_repo.finalize(auction, status, duration_ms, winning_bid_id)

        if winning_bid_id:
            WINNING_BID_VALUE.observe(clearing_price or 0)

        # ---- 8. Fire-and-forget Kafka publish (never awaited) ----
        publish_auction_completed(
            auction_id=str(auction.id),
            winning_dsp=result.winner.dsp_name if (result.winner and budget_ok) else None,
            winning_bid=clearing_price,
            latency_ms=duration_ms,
            status=status,
        )

        creative = None
        if winning_bid_row:
            creative = await self.creative_repo.get_active_for_campaign(winning_bid_row.campaign_id)

        return AuctionResponse(
            id=auction.id, request_id=auction.request_id, ad_slot_id=ad_slot.id,
            status=status, duration_ms=duration_ms, winning_bid_id=winning_bid_id,
            winning_dsp_name=result.winner.dsp_name if (result.winner and budget_ok) else None,
            clearing_price=clearing_price,
            creative_url=creative.image_url if creative else None,
            landing_url=creative.landing_url if creative else None,
            started_at=auction.started_at, completed_at=auction.completed_at,
        )

    async def get_bids(self, auction_id: uuid.UUID) -> list[BidResponse]:
        bids = await self.auction_repo.get_bids(auction_id)
        dsp_names = {d.id: d.name for d in await self.dsp_service.list_all()}
        return [
            BidResponse(
                id=b.id, dsp_id=b.dsp_id, dsp_name=dsp_names.get(b.dsp_id),
                campaign_id=b.campaign_id, amount=float(b.amount),
                response_time_ms=b.response_time_ms, status=b.status,
            )
            for b in bids
        ]

    async def get_auction(self, auction_id: uuid.UUID) -> AuctionResponse | None:
        auction = await self.auction_repo.get_with_bids(auction_id)
        if auction is None:
            return None
        return await self._to_response(auction)

    async def list_recent_auctions(self, limit: int = 50) -> list[AuctionResponse]:
        auctions = await self.auction_repo.list_recent(limit)
        return [await self._to_response(a) for a in auctions]

    async def _to_response(self, auction) -> AuctionResponse:
        winner_name = None
        clearing_price = None
        if auction.winning_bid_id:
            bids = await self.auction_repo.get_bids(auction.id)
            winning = next((b for b in bids if b.id == auction.winning_bid_id), None)
            if winning:
                dsp_names = {d.id: d.name for d in await self.dsp_service.list_all()}
                winner_name = dsp_names.get(winning.dsp_id)
                clearing_price = float(winning.amount)
        return AuctionResponse(
            id=auction.id, request_id=auction.request_id, ad_slot_id=auction.ad_slot_id,
            status=auction.status, duration_ms=auction.duration_ms,
            winning_bid_id=auction.winning_bid_id, winning_dsp_name=winner_name,
            clearing_price=clearing_price, started_at=auction.started_at,
            completed_at=auction.completed_at,
        )
