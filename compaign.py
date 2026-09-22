import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CampaignCreate(BaseModel):
    advertiser_id: uuid.UUID
    name: str
    daily_budget: float = Field(gt=0)
    bid_floor: float = Field(ge=0, default=0)
    target_countries: list[str] = Field(default_factory=list)
    target_devices: list[str] = Field(default_factory=list)
    start_time: datetime
    end_time: datetime


class CampaignUpdate(BaseModel):
    name: str | None = None
    daily_budget: float | None = Field(default=None, gt=0)
    bid_floor: float | None = Field(default=None, ge=0)
    target_countries: list[str] | None = None
    target_devices: list[str] | None = None
    status: str | None = Field(default=None, pattern="^(ACTIVE|PAUSED|ENDED)$")
    end_time: datetime | None = None


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    advertiser_id: uuid.UUID
    name: str
    daily_budget: float
    remaining_budget: float
    bid_floor: float
    target_countries: list[str]
    target_devices: list[str]
    status: str
    start_time: datetime
    end_time: datetime
    created_at: datetime