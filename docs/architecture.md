# RTB Platform — Architecture (Phase 1)

## 1. Scope of this document

This document is produced **before any code** per the project's development
strategy (Phase 1). It defines:

- Service boundaries within a single modular FastAPI app (not yet split into
  microservices)
- The request/response path for the critical auction flow
- Where each infrastructure component (Postgres, Redis, Kafka) sits and *why*
- What is deferred to later phases (caching, eventing, rate limiting,
  observability) so Phase 1 stays scoped to: schema + core CRUD + auction
  skeleton with no external dependencies beyond Postgres.

## 2. Why "modular monolith" first, not microservices

Splitting into services before the domain model and the auction algorithm are
stable would mean paying network/serialization cost on the *one path that
must be fast* (the auction path) for no benefit. A modular monolith gives:

- Clean internal boundaries (`services/auction`, `services/bidding`,
  `services/campaign`, `services/dsp`, `services/analytics`) that map 1:1 to
  future service extraction points
- Function calls instead of network calls on the hot path, during the phase
  where we're still tuning the auction algorithm and don't want two sources
  of latency (network + algorithm) to fight each other
- A single deployable for local Docker Compose development

Extraction candidate later: **Analytics Service**, since it's already
decoupled via Kafka and has no synchronous callers.

## 3. Logical architecture (target state, built incrementally)

```
                              ┌────────────────────┐
                              │     Next.js UI      │
                              └──────────┬───────────┘
                                         │ HTTPS/JSON
                                         ▼
                              ┌────────────────────┐
                              │   FastAPI Gateway   │  (single process, Phase 1)
                              │  (authn, routing,   │
                              │   rate limiting*)   │
                              └──────────┬───────────┘
              ┌───────────────────────────┼───────────────────────────┐
              ▼                           ▼                           ▼
     ┌──────────────────┐       ┌───────────────────┐        ┌──────────────────┐
     │ Campaign Domain   │       │  Auction Domain    │        │ Analytics Domain │
     │ - CRUD campaigns  │       │ - AuctionEngine     │        │ - read models     │
     │ - budget mgmt      │       │ - BiddingClient     │        │ - Kafka consumers │
     │ - creative mgmt    │◄──────┤ - AuctionStrategy   │        │                    │
     └─────────┬──────────┘  read └──────────┬──────────┘        └────────┬──────────┘
               │                              │                             ▲
               │ writes                       │ cache-aside*                │ consumes
               ▼                              ▼                             │
     ┌──────────────────┐            ┌───────────────┐            ┌────────┴────────┐
     │   PostgreSQL      │◄───────────┤     Redis*     │            │      Kafka*      │
     │ (system of record)│  fallback  │ (hot-path cache│            │ (event backbone) │
     └────────────────────┘  on miss  │  + budget locks│            └──────────────────┘
                                        │  + rate limit) │                     ▲
                                        └───────────────┘                     │
                                                                    ┌─────────┴─────────┐
                                                                    │  DSP Simulator(s)  │
                                                                    │  DSP-A..DSP-E      │
                                                                    └────────────────────┘
```
`*` = introduced in later phases (3, 4, 6), not part of Phase 1. Phase 1 wires
Postgres + FastAPI + campaign/DSP/auction CRUD with a synchronous, in-memory
auction stub so the schema and domain boundaries can be validated first.

## 4. Service boundaries (Phase 1 modules)

| Module | Owns | Does NOT own |
|---|---|---|
| `services/campaign` | Advertiser, Campaign, Creative CRUD; budget reads/writes | Auction logic, DSP calls |
| `services/dsp` | DSP registry, DSP client abstraction, simulator config | Auction ranking |
| `services/auction` | Orchestrates a single auction: gather bids, apply engine, persist result | Campaign CRUD, DSP registry management |
| `services/bidding` | `AuctionEngine`, `AuctionStrategy` implementations, bid validation | HTTP concerns, persistence details |
| `services/analytics` | Read-only aggregation queries / (later) Kafka consumers | Writing auction results |
| `repositories/*` | All SQL — no other module talks to the DB directly | Business rules |
| `events/*` | Kafka producers/consumers (Phase 4+) | — |
| `workers/*` | Background consumers, retry/backoff jobs (Phase 4+/5+) | — |

Rule enforced throughout: **API layer → service layer → repository layer**.
No service imports another service's repository directly; cross-domain reads
go through the owning service's public interface. This is what lets
`services/analytics` be extracted later without touching `services/auction`.

## 5. Critical path: `POST /api/v1/auctions`

```
Publisher
   │ POST /api/v1/auctions  (Idempotency-Key: req_123)
   ▼
API layer
   │ 1. validate payload (Pydantic)
   │ 2. idempotency check (Phase 5: Redis/Postgres; Phase 1: Postgres unique constraint on request_id)
   ▼
AuctionService.run_auction()
   │ 3. load ad_slot -> eligible campaigns (Phase 1: Postgres query; Phase 3: Redis cache-aside)
   │ 4. build BidRequest per eligible DSP
   ▼
BiddingClient.collect_bids()   ── asyncio.gather with per-DSP timeout + global timeout
   │        ├── DSP-A  (task, timeout=Nms)
   │        ├── DSP-B  (task, timeout=Nms)
   │        └── DSP-C  (task, timeout=Nms) -> cancelled if global deadline hit
   ▼
AuctionEngine.select_winner(valid_bids)
   │ 5. filter: floor price, campaign status, budget, targeting
   │ 6. score + rank (FirstPrice / SecondPrice strategy)
   ▼
AuctionService
   │ 7. persist Auction + Bids (Postgres transaction)
   │ 8. reserve/deduct budget atomically
   │ 9. (Phase 4) publish AUCTION_COMPLETED to Kafka — fire-and-forget, off critical path
   ▼
Response: winning creative + clearing price
```

Everything after step 7 that isn't required to answer the publisher (Kafka
publish, downstream analytics) is explicitly **not awaited synchronously**
once Phase 4 lands — it will be handed to a background task /
`asyncio.create_task` so it cannot add latency to the response.

## 6. Deferred concerns (explicitly out of scope for Phase 1)

| Concern | Introduced in | Phase 1 stand-in |
|---|---|---|
| Redis cache-aside for campaigns/DSPs/slots | Phase 3 | Direct Postgres reads |
| Kafka event publishing | Phase 4 | None (log line only) |
| Idempotency-Key de-dup at scale | Phase 5 | Unique constraint on `auction.request_id` |
| Atomic budget reservation under concurrency | Phase 5 | `SELECT ... FOR UPDATE` in a single transaction |
| Rate limiting | Phase 6 | None |
| DSP timeout/failure injection | Phase 2 (simulator) | N/A |
| Metrics/dashboards | Phase 8 | None |

This keeps Phase 1 reviewable and testable on its own before concurrency,
caching, and eventing are layered on top of a schema that already works.

## 7. Why each core technology (full rationale, referenced from Section 28 of the brief)

- **PostgreSQL** — campaigns, budgets, and auction results need transactional
  guarantees (no lost updates on `remaining_budget`, no partial auction
  records). A relational model also matches the domain naturally: campaigns
  belong to advertisers, bids belong to auctions, indexes support the
  query patterns we already know (by status, by time range, by auction).
- **Redis** (Phase 3+) — campaign/DSP/slot lookups happen on every single
  auction, and the auction has a ~100ms budget. A network round trip to
  Postgres per lookup, for read-mostly, small, hot data, is the wrong
  trade-off. Redis also gives us atomic primitives (`INCRBY`, `WATCH`/`MULTI`)
  useful for budget locks and rate limiting.
- **Kafka** (Phase 4+) — decouples the latency-sensitive auction path from
  analytics, audit, and budget-reconciliation consumers. The auction should
  not slow down because an analytics aggregation is slow or an audit sink is
  temporarily unavailable.
- **asyncio** — DSP calls are I/O-bound and must happen concurrently, each
  under an individual timeout, without one slow DSP blocking the others or
  the auction as a whole.
- **Docker Compose** — reproducible local environment for Postgres, Redis,
  Kafka, Prometheus, and Grafana without requiring Kubernetes for a
  single-node portfolio project.

## 8. Next step

Section 9 (`database.md`) defines the Phase 1 PostgreSQL schema: tables,
relationships, and the indexes required by the query patterns above, with a
rationale for each index. Once you confirm the schema, Phase 1 implementation
begins: FastAPI app skeleton, models, migrations, and CRUD for Advertiser,
Campaign, Creative, DSP, and a stub Auction endpoint (no real bidding yet —
that's Phase 2).
