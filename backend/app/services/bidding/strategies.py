"""Pluggable ranking strategies (Section 6/7 of the spec).

AuctionStrategy
    |
    +-- HighestBidStrategy      (first-price: winner pays what they bid)
    +-- SecondPriceStrategy     (winner pays max(second_highest, floor))
    +-- QualityAdjustedStrategy (ranks by bid * quality_score, still first-price)

Adding a new strategy means implementing `select`; nothing in the API layer
or repository layer needs to change (Open/Closed).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.bidding.types import AuctionResult, BidStatus, RawBid


def _valid(bids: list[RawBid]) -> list[RawBid]:
    return [b for b in bids if b.status == BidStatus.VALID]


class AuctionStrategy(ABC):
    @abstractmethod
    def select(self, bids: list[RawBid], floor_price: float) -> AuctionResult:
        ...


class HighestBidStrategy(AuctionStrategy):
    """First-price: highest raw bid wins, pays exactly what it bid."""

    def select(self, bids: list[RawBid], floor_price: float) -> AuctionResult:
        candidates = _valid(bids)
        if not candidates:
            return AuctionResult(winner=None, clearing_price=None, all_bids=bids)
        winner = max(candidates, key=lambda b: b.amount)
        return AuctionResult(winner=winner, clearing_price=winner.amount, all_bids=bids)


class SecondPriceStrategy(AuctionStrategy):
    """Vickrey (second-price) auction: highest bid wins, clearing price is
    max(second_highest_bid, floor_price). Ties on the top bid are broken by
    response time (the faster DSP wins) -- see docs/auction-engine.md."""

    def select(self, bids: list[RawBid], floor_price: float) -> AuctionResult:
        candidates = _valid(bids)
        if not candidates:
            return AuctionResult(winner=None, clearing_price=None, all_bids=bids)

        ranked = sorted(candidates, key=lambda b: (-b.amount, b.response_time_ms))
        winner = ranked[0]
        second_highest = ranked[1].amount if len(ranked) > 1 else floor_price
        clearing_price = max(second_highest, floor_price)
        return AuctionResult(winner=winner, clearing_price=clearing_price, all_bids=bids)


class QualityAdjustedStrategy(AuctionStrategy):
    """score = bid_amount * quality_score; highest score wins, pays its raw
    bid amount (first-price on the raw amount, ranked by adjusted score)."""

    def select(self, bids: list[RawBid], floor_price: float) -> AuctionResult:
        candidates = _valid(bids)
        if not candidates:
            return AuctionResult(winner=None, clearing_price=None, all_bids=bids)
        winner = max(candidates, key=lambda b: b.amount * b.quality_score)
        return AuctionResult(winner=winner, clearing_price=winner.amount, all_bids=bids)


def get_strategy(name: str) -> AuctionStrategy:
    strategies: dict[str, AuctionStrategy] = {
        "FIRST_PRICE": HighestBidStrategy(),
        "SECOND_PRICE": SecondPriceStrategy(),
        "QUALITY_ADJUSTED": QualityAdjustedStrategy(),
    }
    try:
        return strategies[name]
    except KeyError as exc:
        raise ValueError(f"Unknown auction strategy: {name}") from exc
