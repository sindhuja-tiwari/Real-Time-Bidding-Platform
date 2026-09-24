# Failure Handling

## Design principle

The auction's critical path (`POST /api/v1/auctions`) must return within its
latency budget even when any single dependency is degraded. Concretely:

| Dependency down | Behavior | Where enforced |
|---|---|---|
| One or more DSPs slow/erroring | Auction completes using whichever bids arrived in time; the failing DSP's bids are marked `TIMEOUT`/`INVALID` | `bidding/client.py` (per-DSP timeout, broad `except` around each call) |
| All DSPs slow | Auction still completes at the global deadline, with `NO_BID` if nothing valid came back in time | `bidding/client.py` (`asyncio.wait_for` around `gather`) |
| Redis unavailable | Reads fall back to Postgres (cache miss behavior); writes to Redis are skipped with a warning, not an exception | `core/redis_client.py` (`safe_get`/`safe_set`/`safe_delete` swallow exceptions) |
| Kafka unavailable | Auction result is already committed to Postgres before publish is attempted; the publish is fire-and-forget and its failure is logged + counted in `rtb_kafka_publish_failures_total`, never raised | `core/kafka_client.py` / `events/producer.py` |
| Postgres unavailable | The auction fails loudly (`FAILED` status, 500) -- Postgres is the one dependency this project treats as non-optional, since it's the system of record for money (budgets) and auction results | `services/auction/service.py`'s `except Exception` block |

The asymmetry is intentional: Redis and Kafka are *optimizations* (latency,
decoupling) layered on top of a system that is still correct without them,
just slower/less observable. Postgres is the source of truth; there is no
"correct" way to run an auction if you can't durably record who won and
whose budget to deduct.

## Rate limiting fails open, not closed

`core/rate_limit.py::is_allowed` catches any Redis exception and returns
`True` (allow the request) rather than `False`. A Redis outage should
degrade the platform to "no rate limiting" -- an acceptable, recoverable
state -- rather than "every request rejected," which would be worse than
having no rate limiter at all. Verified in
`tests/test_rate_limiter.py::test_rate_limiter_fails_open_when_redis_unavailable`.

## Retries differ by path (Section 15)

- **Auction path: no retries.** A retried DSP call or a retried Postgres
  write would risk blowing the ~100ms auction deadline for a single request,
  and a retried write risks double-counting a budget deduction. If a step
  fails, the bid/auction is marked accordingly and the auction moves on.
- **Consumer path: retry with exponential backoff, then dead-letter.**
  `events/consumer_runner.py` retries a failing handler up to
  `EVENT_MAX_RETRIES` times (1s, 2s, 4s, 8s by default) before publishing the
  original payload to the `dead-letter-events` topic and committing the
  offset anyway, so one poison message can't wedge the consumer group
  forever.

## Simulating failures locally (Section 14)

The DSP simulator's `/admin/dsps/{name}` endpoint lets you change any DSP's
`failure_probability`, `timeout_probability`, and `latency_ms` at runtime
without restarting anything:

```bash
curl -X POST http://localhost:9000/admin/dsps/dsp-c \
  -H "Content-Type: application/json" \
  -d '{"campaign_id": "<uuid>", "base_bid": 4.1, "latency_ms": 150, "timeout_probability": 0.9}'
```

DSP-C ships pre-configured with `latency_ms=150` and `timeout_probability=0.35`
specifically so it frequently misses the default 100ms auction deadline --
the frontend's `/system` page and `docs/performance.md` reference this as
the demonstration of "why low latency and per-DSP timeouts matter."

To simulate Redis or Kafka being unavailable, stop the container directly:

```bash
docker compose stop redis   # auctions keep working, slower, cache misses
docker compose stop kafka   # auctions keep working, events are dropped + logged
docker compose stop postgres  # auctions start failing -- this is the one true SPOF
```
