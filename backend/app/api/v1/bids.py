import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.auction import BidResponse
from app.services.auction.service import AuctionService

router = APIRouter(prefix="/bids", tags=["bids"])


@router.get("/{auction_id}", response_model=list[BidResponse])
async def get_bids_for_auction(
    auction_id: uuid.UUID, db: AsyncSession = Depends(get_db), redis_client=None
):
    from app.core.redis_client import get_redis

    client = redis_client or get_redis()
    service = AuctionService(db, client)
    return await service.get_bids(auction_id)
