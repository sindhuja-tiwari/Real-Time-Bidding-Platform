# RTB Platform — Database Design (Phase 1)

## 1. Entity relationship overview

```
User ──< (owns, optional) Advertiser
Advertiser 1───< Campaign
Campaign 1───< Creative
Campaign 1───< Bid
Campaign 1───< Impression
Publisher 1───< AdSlot
AdSlot 1───< Auction
DSP 1───< Bid
Auction 1───< Bid
Auction 1───1 Bid (winning_bid_id, nullable FK)
Auction 1───< Impression
Impression 1───< Click
```

Design notes:

- `Auction.winning_bid_id` is a nullable FK to `bid.id`, set after the
  winner is chosen (a bid always exists before it can "win" — chicken/egg
  is avoided by inserting bids first, then updating the auction row in the
  same transaction).
- `Campaign.remaining_budget` is a denormalized running total, deliberately
  redundant with `SUM(bid.amount) WHERE status='WON'`, because recomputing
  a sum on every auction request would be too slow. It is kept correct via
  the atomic reservation transaction described in Section 4.
- `request_id` on `Auction` is unique — this is the idempotency key
  (Phase 1 stand-in for the fuller Redis-backed idempotency layer in Phase 5).

## 2. Schema (DDL)

```sql
-- =========================================================
-- Users & Advertisers
-- =========================================================

CREATE TABLE "user" (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('ADMIN', 'ADVERTISER', 'PUBLISHER')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE advertiser (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id   UUID REFERENCES "user"(id),
    name            TEXT NOT NULL,
    budget          NUMERIC(12, 4) NOT NULL CHECK (budget >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- =========================================================
-- Campaigns & Creatives
-- =========================================================

CREATE TABLE campaign (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    advertiser_id       UUID NOT NULL REFERENCES advertiser(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    daily_budget        NUMERIC(12, 4) NOT NULL CHECK (daily_budget >= 0),
    remaining_budget    NUMERIC(12, 4) NOT NULL CHECK (remaining_budget >= 0),
    bid_floor           NUMERIC(10, 4) NOT NULL DEFAULT 0,
    target_countries    TEXT[] NOT NULL DEFAULT '{}',
    target_devices      TEXT[] NOT NULL DEFAULT '{}',
    status              TEXT NOT NULL CHECK (status IN ('ACTIVE', 'PAUSED', 'ENDED')) DEFAULT 'ACTIVE',
    start_time          TIMESTAMPTZ NOT NULL,
    end_time            TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_time > start_time)
);

CREATE TABLE creative (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     UUID NOT NULL REFERENCES campaign(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    image_url       TEXT NOT NULL,
    landing_url     TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('ACTIVE', 'PAUSED')) DEFAULT 'ACTIVE'
);

-- =========================================================
-- Publishers & Ad Slots
-- =========================================================

CREATE TABLE publisher (
    id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name    TEXT NOT NULL
);

CREATE TABLE ad_slot (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publisher_id    UUID NOT NULL REFERENCES publisher(id) ON DELETE CASCADE,
    placement       TEXT NOT NULL,
    width           INTEGER NOT NULL,
    height          INTEGER NOT NULL,
    floor_price     NUMERIC(10, 4) NOT NULL DEFAULT 0
);

-- =========================================================
-- DSPs
-- =========================================================

CREATE TABLE dsp (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL UNIQUE,
    endpoint        TEXT NOT NULL,
    timeout_ms      INTEGER NOT NULL DEFAULT 100,
    status          TEXT NOT NULL CHECK (status IN ('ACTIVE', 'DISABLED')) DEFAULT 'ACTIVE'
);

-- =========================================================
-- Auctions & Bids
-- =========================================================

CREATE TABLE auction (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      TEXT NOT NULL UNIQUE,           -- idempotency key
    ad_slot_id      UUID NOT NULL REFERENCES ad_slot(id),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    duration_ms     INTEGER,
    status          TEXT NOT NULL CHECK (status IN ('PENDING', 'COMPLETED', 'NO_BID', 'FAILED')) DEFAULT 'PENDING',
    winning_bid_id  UUID REFERENCES bid(id)
);

CREATE TABLE bid (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auction_id          UUID NOT NULL REFERENCES auction(id) ON DELETE CASCADE,
    dsp_id              UUID NOT NULL REFERENCES dsp(id),
    campaign_id         UUID NOT NULL REFERENCES campaign(id),
    amount              NUMERIC(10, 4) NOT NULL CHECK (amount >= 0),
    response_time_ms    INTEGER,
    status              TEXT NOT NULL CHECK (
                            status IN ('VALID', 'TIMEOUT', 'INVALID', 'BELOW_FLOOR', 'BUDGET_EXCEEDED', 'WON', 'LOST')
                        ),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- deferred FK, since auction.winning_bid_id references bid.id and bid.auction_id
-- references auction.id (created after bid, once both tables exist)
ALTER TABLE auction
    ADD CONSTRAINT fk_auction_winning_bid
    FOREIGN KEY (winning_bid_id) REFERENCES bid(id);

-- =========================================================
-- Impressions & Clicks
-- =========================================================

CREATE TABLE impression (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auction_id      UUID NOT NULL REFERENCES auction(id),
    campaign_id     UUID NOT NULL REFERENCES campaign(id),
    "timestamp"     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE click (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    impression_id   UUID NOT NULL REFERENCES impression(id) ON DELETE CASCADE,
    "timestamp"     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 3. Indexes and rationale

```sql
CREATE INDEX idx_campaign_status              ON campaign(status);
CREATE INDEX idx_campaign_advertiser_id        ON campaign(advertiser_id);
CREATE INDEX idx_campaign_start_end            ON campaign(start_time, end_time);

CREATE INDEX idx_bid_auction_id                ON bid(auction_id);
CREATE INDEX idx_bid_dsp_id                    ON bid(dsp_id);

CREATE INDEX idx_auction_created_at            ON auction(started_at);
CREATE INDEX idx_auction_status                ON auction(status);

CREATE INDEX idx_impression_campaign_id        ON impression(campaign_id);
CREATE INDEX idx_impression_timestamp          ON impression("timestamp");
```

| Index | Why |
|---|---|
| `campaign(status)` | Every auction's eligibility query filters `WHERE status = 'ACTIVE'` — this is on the hot path in Phase 1 before Redis caching lands in Phase 3. |
| `campaign(advertiser_id)` | Advertiser dashboard / campaign list views (`GET /campaigns?advertiser_id=`) and FK join performance. |
| `campaign(start_time, end_time)` | Eligibility also filters on flight dates (`now() BETWEEN start_time AND end_time`); a composite index supports range scans instead of a full table scan as campaign volume grows. |
| `bid(auction_id)` | `GET /api/v1/bids/{auction_id}` and the auction-detail page fetch all bids for one auction — this is the single most frequent read after an auction completes. |
| `bid(dsp_id)` | DSP-level analytics (win rate, timeout rate per DSP) and the admin DSP page. |
| `auction(created_at)` (on `started_at`) | Analytics queries and dashboards are time-windowed ("auctions in the last hour"); without this index they'd force a sequential scan as the auction table grows into millions of rows. |
| `auction(status)` | Distinguishing `COMPLETED` vs `FAILED` vs `NO_BID` for monitoring/alerting queries and the analytics overview endpoint. |
| `impression(campaign_id)` | Budget reconciliation and campaign performance rollups group by campaign. |
| `impression(timestamp)` | Time-windowed impression/CTR reporting, same reasoning as `auction(started_at)`. |

`request_id` and `dsp.name` already get an implicit unique index from their
`UNIQUE` constraints, which is what makes the idempotency check
(`SELECT ... WHERE request_id = $1`) O(log n) instead of a scan.

## 4. Concurrency-critical query: atomic budget reservation

Deferred to Phase 5 for the full design (with a Redis-based fast path), but
the Phase 1 fallback — correct, if not yet optimized for throughput — is a
single transaction using row locking:

```sql
BEGIN;

SELECT remaining_budget
FROM campaign
WHERE id = $1
FOR UPDATE;                          -- locks the row; concurrent auctions
                                      -- targeting the same campaign serialize here

UPDATE campaign
SET remaining_budget = remaining_budget - $2
WHERE id = $1
  AND remaining_budget >= $2;        -- re-check under the lock; 0 rows updated
                                      -- means "insufficient budget", handled
                                      -- as a rejected bid, not an error

COMMIT;
```

This is intentionally simple and correct first; Phase 5's documentation will
cover why (and when) this becomes a bottleneck at high campaign-level QPS,
and how a Redis `DECRBY`-based reservation with periodic reconciliation
against Postgres addresses it.

## 5. Why PostgreSQL over MongoDB (interview-ready answer)

The domain is inherently relational and write patterns need strong
consistency:

- Budgets must never go negative under concurrent writes → needs
  transactions + row locking, which document stores support far less
  naturally than Postgres.
- Campaigns, creatives, bids, and auctions have real foreign-key
  relationships that are queried in both directions (campaign → bids,
  bid → campaign) — a relational schema with indexes fits this better than
  embedding or manual joins in application code.
- Reporting/analytics queries are naturally aggregate-and-filter
  (`GROUP BY`, time-range `WHERE`) — exactly what SQL and Postgres's query
  planner are built for.
- We don't have a schema-flexibility requirement (wildly varying document
  shapes) that would justify a document store's trade-offs.

## 6. Next step

With this schema agreed, Phase 1 implementation is:

1. FastAPI app skeleton (`app/main.py`, `app/core/config.py`, `app/core/db.py`)
2. SQLAlchemy models mirroring this DDL + Alembic migration
3. Pydantic schemas for request/response validation
4. CRUD endpoints: Advertiser, Campaign, Creative, DSP
5. A stub `POST /api/v1/auctions` that persists an `Auction` row and returns
   a hardcoded "no real bidding yet" response — real concurrent bidding is
   Phase 2.

Say the word and I'll start writing the Phase 1 code (models, migrations,
and the FastAPI app) against this schema.
