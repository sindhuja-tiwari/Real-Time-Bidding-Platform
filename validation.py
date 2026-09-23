"""Bid validation (Section 6, steps 1-5 of the spec).

Pure function, no I/O: takes a raw bid + the campaign snapshot it targets +
the auction context, returns a validated/rejected copy of the bid with its
status field set. Called once per bid returned by collect_bids(); budget is
re-checked atomically at reservation time in the repository, so this check
is a fast-path rejection, not the source of truth for "did we overspend".
"""
from __future__ import annotations

from app.services.bidding.types import BidStatus, CampaignSnapshot, RawBid


def validate_bid(
    bid: RawBid,
    campaign: CampaignSnapshot | None,
    floor_price: float,
    country: str,
    device: str,
) -> RawBid:
    if bid.status != BidStatus.VALID:
        return bid  # already TIMEOUT/INVALID from the transport layer

    if campaign is None:
        bid.status = BidStatus.INVALID
        return bid

    if campaign.status != "ACTIVE":
        bid.status = BidStatus.INVALID
        return bid

    if campaign.target_countries and country not in campaign.target_countries:
        bid.status = BidStatus.INVALID
        return bid

    if campaign.target_devices and device not in campaign.target_devices:
        bid.status = BidStatus.INVALID
        return bid

    effective_floor = max(floor_price, campaign.bid_floor)
    if bid.amount < effective_floor:
        bid.status = BidStatus.BELOW_FLOOR
        return bid

    if bid.amount <= 0 or bid.amount > campaign.remaining_budget:
        bid.status = BidStatus.BUDGET_EXCEEDED
        return bid

    bid.status = BidStatus.VALID
    return bid