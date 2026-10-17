# Real-Time Bidding Platform

A simplified real-time bidding (programmatic advertising) auction platform, built to demonstrate
low-latency request handling, concurrent I/O, event-driven architecture, and the operational
concerns that come with them: caching, idempotency, rate limiting, observability and failure
handling. It also serves as the test bed for [EvidenceOps](#evidenceops), an incident-investigation
harness.

**Stack:** Python, FastAPI, asyncio, PostgreSQL, Redis, Kafka, Docker Compose, OpenTelemetry,
Next.js, Prometheus, Grafana, Locust.

## What it does

A publisher sends an ad request (`POST /api/v1/auctions`). The platform concurrently asks every
eligible demand-side platform (DSP) to bid, enforces a strict per-DSP and global auction deadline,
ranks the valid bids (first- or second-price), atomically reserves the winning campaign's budget,
persists the result, and returns the winning creative, all within the auction's latency budget
(default 100 ms). Everything not required to answer the publisher (analytics, audit logging, budget
reconciliation) happens asynchronously via Kafka.

## Architecture

```
Next.js UI -> FastAPI (modular monolith: campaign / auction / dsp / analytics)
                 |- Postgres      system of record: campaigns, budgets, auctions, bids
                 |- Redis         cache-aside for campaigns/DSPs, rate limiting
                 |- DSP Simulator 5 configurable simulated DSPs
                 '- Kafka         -> analytics / audit / budget consumers (worker service)
Prometheus + Grafana scrape /metrics; OpenTelemetry traces when OTEL_EXPORTER_OTLP_ENDPOINT is set
```

Full write-up: `docs/architecture.md` (service boundaries, request flow, why each technology).
Schema and index rationale: `docs/database.md`. Auction algorithm: `docs/auction-engine.md`.
Behaviour when each dependency degrades: `docs/failure-handling.md`.

## Running it locally

Requires Docker with Compose v2.

```bash
git clone https://github.com/sindhuja-tiwari/Real-Time-Bidding-Platform.git
cd Real-Time-Bidding-Platform
cp .env.example .env

docker compose up --build -d
docker compose ps                                  # wait until services are healthy
docker compose exec backend python -m app.seed     # demo campaigns/DSPs; prints an ad_slot_id
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API docs (OpenAPI) | http://localhost:8000/api/v1/docs |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 (admin / admin) |
| DSP simulator admin | http://localhost:9000/admin/dsps |

Send a test auction (use the `ad_slot_id` printed by the seed script):

```bash
curl -X POST http://localhost:8000/api/v1/auctions \
  -H "Content-Type: application/json" \
  -d '{
        "request_id": "req_demo_1",
        "user": {"id": "user_1", "country": "US", "device": "mobile"},
        "ad_slot": {"id": "<ad_slot_id>", "width": 300, "height": 250}
      }'
```

Then open http://localhost:3000/auctions to see it in the dashboard. Stop everything with
`docker compose down` (add `-v` to also delete the database volume).

## Tests

```bash
cd backend && pip install -r requirements.txt && pytest -v      # platform tests
pytest evidenceops/tests                                         # harness tests, no Docker needed
```

The backend tests cover bid validation, all three ranking strategies (including the second-price
tie-break), and the concurrency behaviour of the DSP fan-out (parallel calls, per-DSP timeout,
global deadline, and a regression test for the stuck-connection failure described in the
EvidenceOps write-up). Most of them use a mocked transport and need no live Postgres / Redis / Kafka.

## Performance

On a 4-core Linux machine one backend process is CPU-bound at roughly 45 auctions/s; the
EvidenceOps scenarios drive 20-30 auctions/s to stay below that. Locust scenarios and the
methodology are in `load-tests/` and `docs/performance.md`.

## EvidenceOps

[`evidenceops/`](evidenceops/README.md) turns this platform into a test bed for incident
investigation: 22 reproducible injected incidents (slow bidders, bad config deploys, DB pool
exhaustion, a migration that drops an index, poison messages, duplicate delivery) with recorded
ground truth, a tool-using investigator agent graded against them alongside two baselines, and
approval-gated fixes tested in a disposable copy of the platform.

```bash
pip install -r evidenceops/requirements.txt
python -m evidenceops run --all
python -m evidenceops investigate --method agent   # needs ANTHROPIC_API_KEY
python -m evidenceops evaluate
```

Running it against the live platform found and fixed several real bugs (budget reservation type
errors, foreign-key violations on timed-out bids, a connection-pool leak after bursts of slow DSPs);
they are listed in the EvidenceOps README under "Platform fixes found while making it reproducible".

## Project structure

```
Real-Time-Bidding-Platform/
|- backend/           FastAPI app: api/, core/, models/, schemas/, repositories/,
|                     services/, events/, workers/, tests/, alembic migrations
|- dsp-simulator/     standalone FastAPI service simulating 5 DSPs
|- frontend/          Next.js + TypeScript + Tailwind dashboard
|- evidenceops/       incident harness, diagnostic tools, investigator, grader
|- load-tests/        Locust scenarios
|- infrastructure/    Prometheus + Grafana config
|- docs/              architecture, database, auction-engine, failure-handling, performance
|- docker-compose.yml
'- .env.example
```

## Documentation

- [`docs/architecture.md`](docs/architecture.md): service boundaries, request flow, technology rationale
- [`docs/database.md`](docs/database.md): schema, indexes, budget-concurrency query
- [`docs/auction-engine.md`](docs/auction-engine.md): concurrency, validation, ranking strategies, idempotency
- [`docs/failure-handling.md`](docs/failure-handling.md): degradation behaviour per dependency, retry policy
- [`docs/performance.md`](docs/performance.md): load-testing methodology
- [`evidenceops/README.md`](evidenceops/README.md): incident harness and results

## Known limitations

- **Two worker bugs are deliberate.** A message that fails to decode kills the worker (the JSON
  deserializer raises outside the retry/dead-letter path), and the analytics rollup is not
  idempotent, so redelivered events are double-counted. Both are kept so EvidenceOps scenarios
  s08, s17-s20 can exercise them. Do not deploy this build as-is.
- One backend process serves about 45 auctions/s (CPU bound); there is no multi-worker or
  multi-instance setup.
- Docker Compose only, intended for local development. There are no Kubernetes manifests.
- Postgres, Redis and Kafka ports are published to the host and use default dev credentials; do not
  expose this stack to a network as-is.
- The EvidenceOps model results (`--method agent`, `--method log_only`) have not been run yet; the
  published suite table covers the two rule-based methods only.

## License

MIT
