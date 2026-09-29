# Real-Time Bidding Platform

A simplified real-time bidding (programmatic advertising) auction platform.
A publisher sends an ad request, the platform asks several demand-side
platforms (DSPs) to bid in parallel, picks a winner within a fixed latency
budget, reserves the winning campaign's budget atomically, and returns the
winning creative.

## What it does

A publisher calls `POST /api/v1/auctions`. The platform:

1. Asks every eligible DSP to bid concurrently, enforcing both a per-DSP
   timeout and a global auction deadline (100 ms by default).
2. Validates the bids and ranks them with a configurable strategy (first-price,
   second-price, and others).
3. Atomically reserves the winning campaign's budget, persists the auction and
   its bids, and returns the winning creative.

Anything the publisher doesn't need in the response (analytics, audit logging,
budget reconciliation) is published to Kafka and handled asynchronously.

## Design highlights

- **Deadline-bounded fan-out.** DSP calls run concurrently with `asyncio`. A DSP
  that misses its timeout is recorded as `TIMEOUT` and dropped from the
  auction, so one slow DSP cannot delay the response.
- **Budgets never go negative.** Reservation is a single conditional
  `UPDATE ... WHERE remaining_budget >= amount`, which is atomic under
  concurrent auctions. See [`docs/database.md`](docs/database.md), Section 4.
- **Idempotent auctions.** `request_id` is unique in the database, so a retried
  request cannot run a second auction.
- **Off the hot path.** Analytics, audit and reconciliation consume Kafka
  events instead of adding latency to the auction request.
- **Defined degradation.** [`docs/failure-handling.md`](docs/failure-handling.md)
  describes what happens when Postgres, Redis, Kafka or a DSP degrades.

## Architecture

```
Next.js UI → FastAPI (modular monolith: campaign / auction / dsp / analytics)
                 ├─ Postgres  (system of record: campaigns, budgets, auctions, bids)
                 ├─ Redis     (cache-aside for campaigns/DSPs, rate limiting)
                 ├─ DSP Simulator (5 configurable simulated DSPs)
                 └─ Kafka → analytics / audit / budget consumers
Prometheus + Grafana scrape /metrics for dashboards
```

Details: [`docs/architecture.md`](docs/architecture.md) (service boundaries and
technology choices), [`docs/database.md`](docs/database.md) (schema, indexes,
budget concurrency), [`docs/auction-engine.md`](docs/auction-engine.md)
(concurrency, validation, ranking, idempotency).

## Running it locally

```bash
git clone https://github.com/sindhuja-tiwari/Real-Time-Bidding-Platform.git
cd Real-Time-Bidding-Platform
cp .env.example .env

docker compose up --build -d
docker compose exec backend python -m app.seed   # creates demo campaigns/DSPs, prints an ad_slot_id
```

- Frontend: http://localhost:3000
- API docs (OpenAPI): http://localhost:8000/api/v1/docs
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001 (admin/admin)
- DSP simulator admin: http://localhost:9000/admin/dsps

Send a test auction, using the `ad_slot_id` printed by the seed script:

```bash
curl -X POST http://localhost:8000/api/v1/auctions \
  -H "Content-Type: application/json" \
  -d '{
        "request_id": "req_demo_1",
        "user": {"id": "user_1", "country": "US", "device": "mobile"},
        "ad_slot": {"id": "<ad_slot_id>", "width": 300, "height": 250}
      }'
```

Then open http://localhost:3000/auctions to see it in the dashboard.

## Tests

```bash
cd backend
pip install -r requirements.txt
pytest -v
```

24 tests cover bid validation, all ranking strategies (including the
second-price tie-break), and the concurrency behavior of the DSP fan-out
(parallel calls, per-DSP timeout, global deadline) using a mocked transport,
so no live Postgres, Redis or Kafka is needed for this subset.

## Performance

Measured with the Locust scenarios in `load-tests/` against the full
Docker Compose stack on [machine: CPU, cores, RAM], with [N] concurrent users.

| Scenario | Throughput | p50 | p99 | DSP timeout rate | Fill rate |
|---|---|---|---|---|---|
| 5 healthy DSPs | [ ] req/s | [ ] ms | [ ] ms | [ ]% | [ ]% |
| 1 DSP stalled past its timeout | [ ] req/s | [ ] ms | [ ] ms | [ ]% | [ ]% |

Methodology and how to reproduce: [`docs/performance.md`](docs/performance.md).

## Known limitations

- Analytics endpoints query the auction and bid tables directly. The Kafka
  analytics consumer exists (`events/consumers/analytics_consumer.py`), but a
  consumer-maintained rollup table is not yet in use.
- Budget reservation serializes on each campaign's row, which would become a
  bottleneck at very high per-campaign win rates. Options are discussed in
  `docs/database.md`, Section 4.
- The stack targets Docker Compose for local development. There are no
  Kubernetes manifests.

## Project structure

```
Real-Time-Bidding-Platform/
├── backend/          FastAPI app: api/, core/, models/, schemas/,
│                     repositories/, services/, events/, workers/, tests/
├── dsp-simulator/    Standalone FastAPI service simulating 5 DSPs
├── frontend/         Next.js + TypeScript + Tailwind dashboard
├── load-tests/       Locust scenarios
├── infrastructure/   Prometheus + Grafana config
├── docs/             architecture, database, auction-engine,
│                     failure-handling, performance
├── docker-compose.yml
└── .env.example
```

## License

MIT
