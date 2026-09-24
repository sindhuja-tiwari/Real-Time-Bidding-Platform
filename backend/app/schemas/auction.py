from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AuctionUser(BaseModel):
    id: str
    country: str
    device: str


class AuctionAdSlotRef(BaseModel):
    id: uuid.UUID
    width: int
    height: int


class AuctionRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    user: AuctionUser
    ad_slot: AuctionAdSlotRef


class BidResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dsp_id: uuid.UUID
    dsp_name: str | None = None
    campaign_id: uuid.UUID
    amount: float
    response_time_ms: int | None
    status: str


class AuctionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    request_id: str
    ad_slot_id: uuid.UUID
    status: str
    duration_ms: int | None
    winning_bid_id: uuid.UUID | None
    winning_dsp_name: str | None = None
    clearing_price: float | None = None
    creative_url: str | None = None
    landing_url: str | None = None
    started_at: datetime
    completed_at: datetime | None
