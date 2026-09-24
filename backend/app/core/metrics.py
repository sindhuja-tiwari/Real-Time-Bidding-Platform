"""Central Prometheus metric definitions.

Kept in one module so `/metrics` output and Grafana panel queries are easy
to cross-reference against docs/performance.md.
"""
from prometheus_client import Counter, Gauge, Histogram

# --- Auction ---
AUCTION_REQUESTS_TOTAL = Counter(
    "rtb_auction_requests_total", "Total auction requests received"
)
AUCTION_COMPLETED_TOTAL = Counter(
    "rtb_auction_completed_total", "Auctions that produced a winning bid"
)
AUCTION_NO_BID_TOTAL = Counter(
    "rtb_auction_no_bid_total", "Auctions that completed with no valid bid"
)
AUCTION_FAILED_TOTAL = Counter(
    "rtb_auction_failed_total", "Auctions that failed due to an internal error"
)
AUCTION_LATENCY_MS = Histogram(
    "rtb_auction_latency_ms",
    "End-to-end auction latency in milliseconds",
    buckets=(5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500, 1000),
)
WINNING_BID_VALUE = Histogram(
    "rtb_winning_bid_value",
    "Winning bid clearing price",
    buckets=(0.5, 1, 2, 3, 4, 5, 7.5, 10, 15, 20),
)

# --- DSP ---
DSP_RESPONSE_LATENCY_MS = Histogram(
    "rtb_dsp_response_latency_ms",
    "DSP response latency in milliseconds",
    ["dsp_name"],
    buckets=(5, 10, 20, 30, 50, 75, 100, 150, 200),
)
DSP_TIMEOUT_TOTAL = Counter(
    "rtb_dsp_timeout_total", "DSP requests that hit the per-DSP timeout", ["dsp_name"]
)
DSP_ERROR_TOTAL = Counter(
    "rtb_dsp_error_total", "DSP requests that returned an error", ["dsp_name"]
)
BID_TOTAL = Counter(
    "rtb_bid_total", "Bids received, labeled by final status", ["status"]
)

# --- Cache ---
CACHE_HIT_TOTAL = Counter("rtb_cache_hit_total", "Redis cache hits", ["resource"])
CACHE_MISS_TOTAL = Counter("rtb_cache_miss_total", "Redis cache misses", ["resource"])

# --- Kafka ---
KAFKA_PUBLISH_TOTAL = Counter(
    "rtb_kafka_publish_total", "Successful Kafka event publishes", ["topic"]
)
KAFKA_PUBLISH_FAILURES = Counter(
    "rtb_kafka_publish_failures_total", "Failed Kafka event publishes", ["topic"]
)
KAFKA_CONSUMER_LAG = Gauge(
    "rtb_kafka_consumer_lag", "Approximate consumer lag", ["group", "topic"]
)

# --- Rate limiting ---
RATE_LIMIT_REJECTIONS_TOTAL = Counter(
    "rtb_rate_limit_rejections_total", "Requests rejected by the rate limiter", ["role"]
)

# --- API ---
API_ERRORS_TOTAL = Counter(
    "rtb_api_errors_total", "Unhandled API errors", ["route", "status_code"]
)
