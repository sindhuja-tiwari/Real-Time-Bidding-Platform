# RTB Platform

A simplified real-time bidding (programmatic advertising) auction platform,
built as a portfolio project to demonstrate low-latency request handling,
concurrent I/O, event-driven architecture, and the operational concerns
(caching, idempotency, rate limiting, observability, failure handling) that
come with them.

## What it does

A publisher sends an ad request (`POST /api/v1/auctions`). The platform
concurrently asks every eligible demand-side platform (DSP) to bid, enforces
a strict per-DSP and global auction deadline, ranks the valid bids (first- or
second-price), atomically reserves the winning campaign's budget, persists
the result, and returns the winning creative — all within the auction's
latency budget (default 100ms). Everything not required to answer the
publisher (analytics, audit logging, budget reconciliation) happens
asynchronously via Kafka.

## Why this project exists

It's designed to be discussable in a systems-design interview: every major
technology choice (Postgres, Redis, Kafka, asyncio) is used because of a
specific problem it solves here, not for résumé decoration. See
`docs/architecture.md` Section 7 and `docs/database.md` Section 5 for the
"why X and not Y" reasoning, and `docs/failure-handling.md` for what happens
when each dependency degrades.

## Architecture

```
Next.js UI → FastAPI (modular monolith: campaign / auction / dsp / analytics)
                 ├─ Postgres  (system of record: campaigns, budgets, auctions, bids)
                 ├─ Redis     (cache-aside for campaigns/DSPs, rate limiting)
                 ├─ DSP Simulator (5 configurable simulated DSPs)
                 └─ Kafka → analytics / audit / budget consumers
Prometheus + Grafana scrape /metrics for dashboards
```

Full write-up: `docs/architecture.md`. Schema and index rationale:
`docs/database.md`. Auction algorithm details: `docs/auction-engine.md`.

## Running it locally

```bash
git clone <this repo>
cd rtb-platform
cp .env.example .env

docker compose up --build -d
docker compose exec backend python -m app.seed   # creates demo campaigns/DSPs, prints an ad_slot_id
```

- Frontend: http://localhost:3000
- API docs (OpenAPI): http://localhost:8000/api/v1/docs
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001 (admin/admin)
- DSP simulator admin: http://localhost:9000/admin/dsps

Send a test auction request (use the `ad_slot_id` printed by the seed script):

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

## Running the backend tests

```bash
cd backend
pip install -r requirements.txt
pytest -v
```

24 tests cover bid validation, all three ranking strategies (including the
second-price tie-break), and the concurrency behavior of the DSP fan-out
(parallel calls, per-DSP timeout, global deadline) using a mocked transport
— no live Postgres/Redis/Kafka required for this subset.

## Load testing

See `docs/performance.md` for the methodology and how to run it against your
own running stack. **That document's numbers are placeholders** — run the
load test yourself and fill in your actual measurements; this project
deliberately does not ship fabricated performance numbers.

## Project structure

```
rtb-platform/
├── backend/            FastAPI app: api/, core/, models/, schemas/,
│                        repositories/, services/, events/, workers/, tests/
├── dsp-simulator/      Standalone FastAPI service simulating 5 DSPs
├── frontend/            Next.js + TypeScript + Tailwind dashboard
├── load-tests/          Locust scenarios
├── infrastructure/      Prometheus + Grafana config
├── docs/                 architecture, database, auction-engine,
│                        failure-handling, performance
├── docker-compose.yml
└── .env.example
```

## Documentation index

- [`docs/architecture.md`](docs/architecture.md) — service boundaries, request flow, tech rationale
- [`docs/database.md`](docs/database.md) — schema, indexes, budget-concurrency query
- [`docs/auction-engine.md`](docs/auction-engine.md) — concurrency, validation, ranking strategies, idempotency
- [`docs/failure-handling.md`](docs/failure-handling.md) — degradation behavior per dependency, retry policy
- [`docs/performance.md`](docs/performance.md) — load-testing methodology (numbers to be filled in by you)

## Known limitations / honest gaps

- Load-test numbers in `docs/performance.md` are placeholders (see above) —
  this was built without a live Docker environment available to the author
  at build time.
- Analytics endpoints query the auction/bid tables directly rather than
  reading from Kafka-consumer-maintained rollup tables; the async pipeline
  exists (see `events/consumers/analytics_consumer.py`) but the rollup
  table itself is a documented extension point, not yet implemented.
- No Kubernetes manifests by design (Section 1 of the original spec) — the
  whole stack targets Docker Compose for local development only.
