"""Approximate percentile estimation from histogram bucket counts.

This is the same technique Prometheus's `histogram_quantile()` uses: rather
than storing every raw latency value (unbounded storage, expensive to query),
we store a count per bucket boundary and linearly interpolate within the
bucket that contains the target percentile. It trades exactness for O(1)
storage per time window -- the right trade-off for a rollup table that's
written on every single auction completion.

The bucket boundaries here intentionally match `core/metrics.py`'s
`AUCTION_LATENCY_MS` Prometheus histogram, so the numbers on the Grafana
dashboard and the numbers from `GET /api/v1/analytics/latency` are computed
the same way and should agree.
"""
from __future__ import annotations

LATENCY_BUCKETS_MS: list[float] = [5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500, 1000]


def bucket_index_for(latency_ms: float) -> int:
    """Index into LATENCY_BUCKETS_MS (+1 for the implicit +Inf overflow
    bucket) that this latency falls into -- the smallest boundary >= it."""
    for i, boundary in enumerate(LATENCY_BUCKETS_MS):
        if latency_ms <= boundary:
            return i
    return len(LATENCY_BUCKETS_MS)  # overflow / +Inf bucket


def estimate_percentile(bucket_counts: list[int], percentile: float) -> float:
    """bucket_counts must have len(LATENCY_BUCKETS_MS) + 1 entries (one per
    boundary plus the +Inf overflow bucket), holding the count of
    observations whose latency fell in that bucket (not cumulative).

    Returns an estimated latency in ms for the given percentile (0 < p < 1),
    linearly interpolating within the bucket that contains it -- identical
    in spirit to Prometheus's histogram_quantile.
    """
    total = sum(bucket_counts)
    if total == 0:
        return 0.0

    target_rank = percentile * total
    cumulative = 0
    lower_boundary = 0.0

    for i, count in enumerate(bucket_counts):
        upper_boundary = LATENCY_BUCKETS_MS[i] if i < len(LATENCY_BUCKETS_MS) else LATENCY_BUCKETS_MS[-1] * 2
        next_cumulative = cumulative + count
        if next_cumulative >= target_rank and count > 0:
            # Linear interpolation within this bucket's range.
            fraction = (target_rank - cumulative) / count
            return round(lower_boundary + fraction * (upper_boundary - lower_boundary), 2)
        cumulative = next_cumulative
        lower_boundary = upper_boundary

    return float(LATENCY_BUCKETS_MS[-1])