# Performance / Load Testing

## Honesty note

**The numbers in this document are placeholders.** I built and unit-tested
this project in a sandboxed environment with no Docker daemon available, so
I could not bring up the full Postgres + Redis + Kafka + backend stack and
run a real load test against it end to end. What I *did* verify:

- The auction engine's pure logic (validation, ranking strategies) — 24
  passing unit tests, see `backend/tests/`.
- The concurrency behavior of the DSP fan-out under simulated
  network delay (`tests/test_concurrency.py`), using `httpx.MockTransport` to
  prove DSPs are called in parallel and that per-DSP/global timeouts hold,
  without needing a live network.
- That the full FastAPI app and every route import and wire up correctly.
- That the DSP simulator responds correctly over real HTTP (ASGI transport),
  including runtime failure injection via its admin API.
- That the Next.js frontend type-checks and builds cleanly against the API
  client.

None of that is a substitute for a real load test against the live stack.
**Run the steps below yourself and replace this document's numbers with
your actual results before using this project's numbers in an interview** --
per the project's own quality bar: "Do NOT fabricate performance numbers."

## How to run the load test

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec backend alembic upgrade head   # if not already run by the backend entrypoint
docker compose exec backend python -m app.seed     # prints the ad_slot_id to use below

pip install -r load-tests/requirements.txt

# headless run, e.g. targeting 500 concurrent virtual users
LOAD_TEST_AD_SLOT_ID=<ad_slot_id from seed output> \
locust -f load-tests/locustfile.py --host=http://localhost:8000 \
  --users 500 --spawn-rate 100 --run-time 60s --headless \
  --csv=load-tests/results/500rps
```

Repeat for each target load in Section 22 of the spec (100/500/1000/5000
req/s -- note Locust controls *concurrent users*, not req/s directly; tune
`--users`/`--spawn-rate` and the `wait_time` in `locustfile.py` to hit your
target throughput, and confirm the achieved rate from Locust's own
`Requests/s` column rather than assuming spawn count == req/s).

## What to fill in

| Target load | Users | P50 | P95 | P99 | Error rate | Achieved req/s |
|---|---|---|---|---|---|---|
| 100 req/s  | ? | ? | ? | ? | ? | ? |
| 500 req/s  | ? | ? | ? | ? | ? | ? |
| 1000 req/s | ? | ? | ? | ? | ? | ? |
| 5000 req/s | ? | ? | ? | ? | ? | ? |

Also run with:

- 5 DSPs (default seed) vs. 20 DSPs (register 15 more via `POST /api/v1/dsps`
  and add matching simulator configs) -- expect P95/P99 to be *insensitive*
  to DSP count as long as the global timeout holds, since they're all
  called concurrently, not sequentially. If P95/P99 instead scale linearly
  with DSP count, that's a sign the fan-out regressed to sequential
  somewhere -- worth checking `asyncio.gather` is actually being used with
  independently-created tasks.
- DSP-C's default config (`timeout_probability=0.35`, `latency_ms=150`) left
  in place vs. all DSPs healthy -- expect a visibly higher `NO_BID`/`FAILED`-
  adjacent timeout count in the bid table for DSP-C specifically, and no
  material change to overall auction P95/P99 (that's the point of the
  per-DSP timeout).

## Where the bottleneck is likely to be (to reason about, then confirm)

1. **The `campaign.remaining_budget` row lock** (`SELECT ... FOR UPDATE` in
   `CampaignRepository.reserve_budget`) serializes all winning bids for the
   *same* campaign. With 5 seed campaigns spread evenly, this shouldn't
   bottleneck a load test with random traffic; it would dominate a load test
   that concentrates all traffic on one campaign/ad slot.
2. **Postgres connection pool size** (`pool_size=20, max_overflow=10` in
   `core/db.py`) -- at high concurrency, requests may queue for a connection
   before they queue for anything else. Watch for latency that scales with
   concurrent users independent of DSP behavior; that points here.
3. **A single `httpx.AsyncClient`/event loop per backend process** -- scaling
   past one process means running multiple `uvicorn` workers (`--workers N`)
   or multiple `backend` container replicas behind a load balancer, since a
   single Python process is bound by one event loop's throughput ceiling
   regardless of how well the async code is written.

## Scaling from 1,000 to 100,000 req/s (discussion, not a benchmark result)

- Horizontal-scale the `backend` service (stateless FastAPI process) behind
  a load balancer; nothing in `AuctionService` holds process-local state.
- Move the budget-reservation fast path to Redis (`DECRBY` with a periodic
  reconciliation job against Postgres) to remove the per-campaign row lock
  as a ceiling -- documented as the Phase 5 follow-up in
  `docs/database.md`.
- Partition Kafka topics by campaign/DSP id so consumer throughput scales
  with partition count.
- Consider read replicas for the analytics endpoints, which are pure reads
  and don't need to hit the same Postgres instance the auction path writes
  to.
- Re-measure after each change -- this list is a set of hypotheses, not a
  guarantee, precisely because it hasn't been load tested yet.
