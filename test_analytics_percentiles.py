from app.services.analytics.percentiles import (
    LATENCY_BUCKETS_MS,
    bucket_index_for,
    estimate_percentile,
)


def test_bucket_index_for_exact_boundaries():
    assert bucket_index_for(5) == 0
    assert bucket_index_for(10) == 1
    assert bucket_index_for(1000) == len(LATENCY_BUCKETS_MS) - 1


def test_bucket_index_for_overflow():
    assert bucket_index_for(5000) == len(LATENCY_BUCKETS_MS)  # +Inf bucket


def test_bucket_index_for_between_boundaries():
    # Between 30 and 50 -> falls into the 50 bucket (smallest boundary >= value)
    assert bucket_index_for(40) == LATENCY_BUCKETS_MS.index(50)


def test_estimate_percentile_all_in_one_bucket():
    # All 100 observations landed in the "<=20ms" bucket.
    counts = [0] * (len(LATENCY_BUCKETS_MS) + 1)
    counts[LATENCY_BUCKETS_MS.index(20)] = 100
    p50 = estimate_percentile(counts, 0.50)
    assert 0 < p50 <= 20


def test_estimate_percentile_empty_returns_zero():
    counts = [0] * (len(LATENCY_BUCKETS_MS) + 1)
    assert estimate_percentile(counts, 0.95) == 0.0


def test_estimate_percentile_p99_exceeds_p50():
    counts = [0] * (len(LATENCY_BUCKETS_MS) + 1)
    counts[LATENCY_BUCKETS_MS.index(20)] = 80  # most requests fast
    counts[LATENCY_BUCKETS_MS.index(200)] = 15  # some slower
    counts[-1] = 5  # a few very slow (overflow bucket)
    p50 = estimate_percentile(counts, 0.50)
    p99 = estimate_percentile(counts, 0.99)
    assert p99 > p50


def test_estimate_percentile_matches_intuition_for_uniform_bucket():
    # 100 observations, all in the 50-75ms bucket. The median (50th
    # percentile of a bucket assumed uniform between its bounds) should sit
    # roughly in the middle of that range.
    counts = [0] * (len(LATENCY_BUCKETS_MS) + 1)
    counts[LATENCY_BUCKETS_MS.index(75)] = 100
    p50 = estimate_percentile(counts, 0.50)
    assert 50 <= p50 <= 75