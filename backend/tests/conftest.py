import uuid

import pytest

from app.services.bidding.types import BidStatus, CampaignSnapshot, RawBid


@pytest.fixture
def campaign_snapshot() -> CampaignSnapshot:
    return CampaignSnapshot(
        id=uuid.uuid4(),
        status="ACTIVE",
        remaining_budget=100.0,
        bid_floor=1.0,
        target_countries=[],
        target_devices=[],
    )


def make_bid(amount: float, quality: float = 0.8, response_time_ms: int = 20, status=BidStatus.VALID) -> RawBid:
    return RawBid(
        dsp_id=uuid.uuid4(),
        dsp_name="dsp-test",
        campaign_id=uuid.uuid4(),
        amount=amount,
        quality_score=quality,
        response_time_ms=response_time_ms,
        status=status,
    )
