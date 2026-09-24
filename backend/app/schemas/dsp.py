from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class DSPCreate(BaseModel):
    name: str
    endpoint: str
    timeout_ms: int = Field(default=100, gt=0)


class DSPUpdate(BaseModel):
    endpoint: str | None = None
    timeout_ms: int | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, pattern="^(ACTIVE|DISABLED)$")


class DSPResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    endpoint: str
    timeout_ms: int
    status: str


class DSPSimConfig(BaseModel):
    """Config pushed to the DSP simulator's admin endpoint (Section 13)."""

    name: str
    campaign_id: str
    base_bid: float
    latency_ms: int
    latency_jitter_ms: int = 10
    failure_probability: float = Field(ge=0, le=1, default=0.0)
    timeout_probability: float = Field(ge=0, le=1, default=0.0)
    quality_score: float = Field(ge=0, le=1, default=0.8)
    accepted_countries: list[str] = Field(default_factory=lambda: ["*"])
    accepted_devices: list[str] = Field(default_factory=lambda: ["*"])
