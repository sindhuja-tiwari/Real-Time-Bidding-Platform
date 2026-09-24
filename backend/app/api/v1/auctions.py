import uuid

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import enforce_rate_limit, get_redis_dep
from app.core.db import get_db
from app.core.exceptions import NotFoundError
from app.core.logging import request_id_var
from app.schemas.auction import AuctionRequest, AuctionResponse, BidResponse
from app.services.auction.service import AuctionService

router = APIRouter(prefix="/auctions", tags=["auctions"])


@router.post("", response_model=AuctionResponse, status_code=201, dependencies=[Depends(enforce_rate_limit)])
async def create_auction(
    body: AuctionRequest,
    db: AsyncSession = Depends(get_db),
    redis_client=Depends(get_redis_dep),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """The core RTB endpoint (Section 4 of the spec).

    Idempotency-Key header, if present, overrides body.request_id as the
    dedup key -- either is honored since the unique constraint lives on
    Auction.request_id either way; the header is the conventional HTTP way
    to express "retry me safely" without changing the payload contract.
    """
    request_id_var.set(idempotency_key or body.request_id)
    if idempotency_key:
        body.request_id = idempotency_key

    service = AuctionService(db, redis_client)
    return await service.run_auction(body)


@router.get("", response_model=list[AuctionResponse])
async def list_auctions(
    limit: int = 50, db: AsyncSession = Depends(get_db), redis_client=Depends(get_redis_dep)
):
    service = AuctionService(db, redis_client)
    return await service.list_recent_auctions(limit)


@router.get("/{auction_id}", response_model=AuctionResponse)
async def get_auction(
    auction_id: uuid.UUID, db: AsyncSession = Depends(get_db), redis_client=Depends(get_redis_dep)
):
    service = AuctionService(db, redis_client)
    result = await service.get_auction(auction_id)
    if result is None:
        raise NotFoundError(f"Auction {auction_id} not found")
    return result
