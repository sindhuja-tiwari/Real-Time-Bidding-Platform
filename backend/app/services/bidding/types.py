"""Domain types for the bidding/auction engine.

Kept free of FastAPI, SQLAlchemy and Redis imports on purpose: the engine
in engine.py is pure logic over these dataclasses, which is what makes it
trivially unit-testable (see tests/test_auction_engine.py) without spinning
up Postgres, Redis or Kafka.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum


class BidStatus(str, Enum):
    VALID = "VALID"
    TIMEOUT = "TIMEOUT"
    INVALID = "INVALID"
    BELOW_FLOOR = "BELOW_FLOOR"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    WON = "WON"
    LOST = "LOST"


@dataclass
class CampaignSnapshot:
    """Just the fields the engine needs, decoupled from the ORM model so the
    engine can be fed either a live SQLAlchemy row or a Redis-cached dict."""

    id: uuid.UUID
    status: str
    remaining_budget: float
    bid_floor: float
    target_countries: list[str]
    target_devices: list[str]


@dataclass
class RawBid:
    """A bid as returned by a DSP, before validation against campaign rules."""

    dsp_id: uuid.UUID
    dsp_name: str
    campaign_id: uuid.UUID
    amount: float
    quality_score: float
    response_time_ms: int
    status: BidStatus = BidStatus.VALID


@dataclass
class AuctionResult:
    winner: RawBid | None
    clearing_price: float | None
    all_bids: list[RawBid]
