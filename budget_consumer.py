"""Campaign budget consumer.

The authoritative budget deduction happens synchronously and atomically in
CampaignRepository.reserve_budget (SELECT ... FOR UPDATE) at auction time --
this consumer does NOT re-deduct anything, which would double-spend. Its job
is asynchronous reconciliation/alerting: watch AUCTION_COMPLETED events and,
when a campaign's remaining budget is exhausted, flip it to PAUSED so future
auctions stop considering it without needing a synchronous check against a
live budget on every single request.
"""
from __future__ import annotations

from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.campaign import Campaign
from app.repositories.campaign_repository import CampaignRepository
from sqlalchemy import select

logger = get_logger(__name__)


async def handle_budget_event(payload: dict) -> None:
    if payload.get("event_type") != "AUCTION_COMPLETED":
        return

    auction_id = payload.get("auction_id")
    async with AsyncSessionLocal() as db:
        # Look up which campaign the winning bid belonged to via the bid table.
        from app.models.bid import Bid

        result = await db.execute(
            select(Bid).where(Bid.auction_id == auction_id, Bid.status == "WON")
        )
        won_bid = result.scalars().first()
        if not won_bid:
            return

        repo = CampaignRepository(db)
        campaign = await repo.get(won_bid.campaign_id)
        if campaign and campaign.status == "ACTIVE" and float(campaign.remaining_budget) <= 0:
            await repo.update(campaign, status="PAUSED")
            logger.info("campaign_auto_paused_budget_exhausted", campaign_id=str(campaign.id))