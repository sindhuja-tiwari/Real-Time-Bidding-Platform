import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auction import Auction
from app.models.bid import Bid


class AuctionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_request_id(self, request_id: str) -> Auction | None:
        """Idempotency lookup (docs/database.md: request_id is UNIQUE).

        Called *before* running the auction, so a duplicate submission of the
        same request_id (client retry, publisher double-send) returns the
        original result instead of running a second, independent auction.
        """
        stmt = select(Auction).where(Auction.request_id == request_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_bids(self, auction_id: uuid.UUID) -> Auction | None:
        stmt = (
            select(Auction)
            .where(Auction.id == auction_id)
            .options(selectinload(Auction.bids))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_bids(self, auction_id: uuid.UUID) -> list[Bid]:
        stmt = select(Bid).where(Bid.auction_id == auction_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_pending(self, request_id: str, ad_slot_id: uuid.UUID) -> Auction | None:
        """Insert the PENDING auction row up front. Relies on the unique
        constraint on request_id as the concurrency-safe idempotency guard:
        if two requests with the same request_id race each other, only one
        INSERT succeeds; the other gets an IntegrityError and is told by the
        caller to re-read the existing row instead of creating a duplicate.
        """
        auction = Auction(request_id=request_id, ad_slot_id=ad_slot_id, status="PENDING")
        self.db.add(auction)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            return None
        await self.db.refresh(auction)
        return auction

    async def finalize(
        self,
        auction: Auction,
        status: str,
        duration_ms: int,
        winning_bid_id: uuid.UUID | None,
    ) -> Auction:
        from sqlalchemy import func

        auction.status = status
        auction.duration_ms = duration_ms
        auction.winning_bid_id = winning_bid_id
        auction.completed_at = func.now()
        await self.db.commit()
        await self.db.refresh(auction)
        return auction

    async def save_bids(self, bids: list[Bid]) -> None:
        self.db.add_all(bids)
        await self.db.commit()