from tests.conftest import make_bid
from app.services.bidding.types import BidStatus
from app.services.bidding.validation import validate_bid


def test_bid_below_floor_is_rejected(campaign_snapshot):
    bid = make_bid(amount=0.5)
    result = validate_bid(bid, campaign_snapshot, floor_price=1.0, country="US", device="mobile")
    assert result.status == BidStatus.BELOW_FLOOR


def test_bid_exceeding_budget_is_rejected(campaign_snapshot):
    campaign_snapshot.remaining_budget = 2.0
    bid = make_bid(amount=5.0)
    result = validate_bid(bid, campaign_snapshot, floor_price=1.0, country="US", device="mobile")
    assert result.status == BidStatus.BUDGET_EXCEEDED


def test_bid_from_inactive_campaign_is_invalid(campaign_snapshot):
    campaign_snapshot.status = "PAUSED"
    bid = make_bid(amount=5.0)
    result = validate_bid(bid, campaign_snapshot, floor_price=1.0, country="US", device="mobile")
    assert result.status == BidStatus.INVALID


def test_bid_outside_target_country_is_invalid(campaign_snapshot):
    campaign_snapshot.target_countries = ["IN"]
    bid = make_bid(amount=5.0)
    result = validate_bid(bid, campaign_snapshot, floor_price=1.0, country="US", device="mobile")
    assert result.status == BidStatus.INVALID


def test_bid_outside_target_device_is_invalid(campaign_snapshot):
    campaign_snapshot.target_devices = ["desktop"]
    bid = make_bid(amount=5.0)
    result = validate_bid(bid, campaign_snapshot, floor_price=1.0, country="US", device="mobile")
    assert result.status == BidStatus.INVALID


def test_valid_bid_passes(campaign_snapshot):
    bid = make_bid(amount=5.0)
    result = validate_bid(bid, campaign_snapshot, floor_price=1.0, country="US", device="mobile")
    assert result.status == BidStatus.VALID


def test_bid_for_unknown_campaign_is_invalid():
    bid = make_bid(amount=5.0)
    result = validate_bid(bid, None, floor_price=1.0, country="US", device="mobile")
    assert result.status == BidStatus.INVALID


def test_already_timed_out_bid_is_left_alone(campaign_snapshot):
    bid = make_bid(amount=5.0, status=BidStatus.TIMEOUT)
    result = validate_bid(bid, campaign_snapshot, floor_price=1.0, country="US", device="mobile")
    assert result.status == BidStatus.TIMEOUT
