from tests.conftest import make_bid
from app.services.bidding.strategies import (
    HighestBidStrategy,
    QualityAdjustedStrategy,
    SecondPriceStrategy,
    get_strategy,
)
from app.services.bidding.types import BidStatus


def test_highest_bid_strategy_picks_top_bid():
    bids = [make_bid(2.5), make_bid(4.1), make_bid(3.2)]
    result = HighestBidStrategy().select(bids, floor_price=0.5)
    assert result.winner.amount == 4.1
    assert result.clearing_price == 4.1  # first-price: pays what it bid


def test_second_price_strategy_clears_at_second_highest():
    # DSP A = 4.50, DSP B = 3.80, DSP C = 2.50 -- from Section 7 of the spec
    bids = [make_bid(4.50), make_bid(3.80), make_bid(2.50)]
    result = SecondPriceStrategy().select(bids, floor_price=0.5)
    assert result.winner.amount == 4.50
    assert result.clearing_price == 3.80


def test_second_price_clearing_price_respects_floor():
    bids = [make_bid(5.0)]  # only one valid bid -> "second highest" is the floor
    result = SecondPriceStrategy().select(bids, floor_price=2.0)
    assert result.winner.amount == 5.0
    assert result.clearing_price == 2.0


def test_second_price_ties_broken_by_response_time():
    fast = make_bid(3.0, response_time_ms=10)
    slow = make_bid(3.0, response_time_ms=90)
    result = SecondPriceStrategy().select([slow, fast], floor_price=0.5)
    assert result.winner is fast


def test_quality_adjusted_strategy_can_flip_the_raw_winner():
    high_bid_low_quality = make_bid(amount=4.0, quality=0.3)
    lower_bid_high_quality = make_bid(amount=3.0, quality=0.9)
    result = QualityAdjustedStrategy().select([high_bid_low_quality, lower_bid_high_quality], floor_price=0.5)
    # 4.0*0.3=1.2 vs 3.0*0.9=2.7 -> the lower raw bid wins on quality-adjusted score
    assert result.winner is lower_bid_high_quality
    assert result.clearing_price == 3.0  # still pays its raw bid (first-price on amount)


def test_no_valid_bids_produces_no_winner():
    bids = [make_bid(4.0, status=BidStatus.TIMEOUT), make_bid(3.0, status=BidStatus.BELOW_FLOOR)]
    result = SecondPriceStrategy().select(bids, floor_price=0.5)
    assert result.winner is None
    assert result.clearing_price is None


def test_get_strategy_factory():
    assert isinstance(get_strategy("FIRST_PRICE"), HighestBidStrategy)
    assert isinstance(get_strategy("SECOND_PRICE"), SecondPriceStrategy)
    assert isinstance(get_strategy("QUALITY_ADJUSTED"), QualityAdjustedStrategy)


def test_get_strategy_unknown_raises():
    import pytest

    with pytest.raises(ValueError):
        get_strategy("NOT_A_REAL_STRATEGY")
