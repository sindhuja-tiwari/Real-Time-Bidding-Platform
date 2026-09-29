# Database Design

PostgreSQL is the system of record for campaigns, budgets, auctions and bids.
Redis sits in front of it as a cache for campaign and DSP lookups and for rate
limiting, but the two correctness guarantees in this document (a budget never
goes negative, and a request ID never produces two auctions) are enforced by
Postgres itself.

## 1. Entity relationships

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

- `auction.winning_bid_id` is a nullable foreign key to `bid.id`. Bids are
  inserted first, then the auction row is updated with the winner in the same
  transaction, so a winner always refers to an existing bid. Because `auction`
  and `bid` reference each other, the `auction → bid` constraint is added after
  both tables exist (see the DDL below).
- `campaign.remaining_budget` is a denormalized running total. It duplicates
  `SUM(bid.amount) WHERE status = 'WON'`, but recomputing that sum on every
  auction would be too slow on the hot path. It is kept correct by the
  conditional update in Section 4.
- `auction.request_id` is `UNIQUE` and serves as the idempotency key. A retried
  request with the same `request_id` cannot create a second auction row. See
  `auction-engine.md` for how the API responds to a duplicate.

## 2. Schema (DDL)

Tables are listed in dependency order. `gen_random_uuid()` is built into
PostgreSQL 13 and later; on older versions, enable the `pgcrypto` extension.

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

-- winning_bid_id gets its foreign key after the bid table exists (below).
CREATE TABLE auction (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      TEXT NOT NULL UNIQUE,           -- idempotency key
    ad_slot_id      UUID NOT NULL REFERENCES ad_slot(id),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    duration_ms     INTEGER,
    status          TEXT NOT NULL CHECK (status IN ('PENDING', 'COMPLETED', 'NO_BID', 'FAILED')) DEFAULT 'PENDING',
    winning_bid_id  UUID
);

CREATE TABLE bid (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auction_id          UUID NOT NULL REFERENCES auction(id) ON DELETE CASCADE,
    dsp_id              UUID NOT NULL REFERENCES dsp(id),
    campaign_id         UUID NOT NULL REFERENCES campaign(id),
    amount              NUMERIC(10, 4) NOT NULL CHECK (amount >= 0),
    response_time_ms    INTEGER,
    status              TEXT NOT NULL CHECK (
                            status IN ('VALID', 'TIMEOUT', 'INVALID', 'BELOW_FLOOR',
                                       'BUDGET_EXCEEDED', 'WON', 'LOST')
                        ),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

## 3. Indexes

```sql
CREATE INDEX idx_campaign_status          ON campaign(status);
CREATE INDEX idx_campaign_advertiser_id   ON campaign(advertiser_id);
CREATE INDEX idx_campaign_start_end       ON campaign(start_time, end_time);

CREATE INDEX idx_bid_auction_id           ON bid(auction_id);
CREATE INDEX idx_bid_dsp_id               ON bid(dsp_id);

CREATE INDEX idx_auction_started_at       ON auction(started_at);
CREATE INDEX idx_auction_status           ON auction(status);

CREATE INDEX idx_impression_campaign_id   ON impression(campaign_id);
CREATE INDEX idx_impression_timestamp     ON impression("timestamp");
```

PostgreSQL does not index foreign-key columns automatically, so each FK used
in a join or lookup gets an explicit index.

| Index | Why |
|---|---|
| `campaign(status)` | Auction eligibility filters on `status = 'ACTIVE'` when the Redis campaign cache misses. The column has only three values, so at larger scale a partial index on active campaigns would be the better choice. |
| `campaign(advertiser_id)` | Campaign list views (`GET /campaigns?advertiser_id=`) and FK joins. |
| `campaign(start_time, end_time)` | Eligibility also filters on flight dates (`now() BETWEEN start_time AND end_time`). |
| `bid(auction_id)` | Fetching all bids for one auction (`GET /api/v1/bids/{auction_id}` and the auction-detail page), the most frequent read after an auction completes. |
| `bid(dsp_id)` | Per-DSP analytics such as win rate and timeout rate. |
| `auction(started_at)` | Time-windowed analytics ("auctions in the last hour") without a sequential scan as the table grows. |
| `auction(status)` | Separating `COMPLETED`, `FAILED` and `NO_BID` for monitoring and the analytics overview. |
| `impression(campaign_id)` | Budget reconciliation and per-campaign rollups. |
| `impression(timestamp)` | Time-windowed impression and CTR reporting. |

`request_id` and `dsp.name` get unique indexes from their `UNIQUE`
constraints, which makes the idempotency lookup an index probe rather than a
scan.

## 4. Atomic budget reservation

The winning campaign's budget is reserved with a single conditional update:

```sql
UPDATE campaign
SET remaining_budget = remaining_budget - $2
WHERE id = $1
  AND remaining_budget >= $2
RETURNING remaining_budget;
```

If no row is returned, the campaign cannot afford the bid. That outcome is
handled as a rejected bid (`BUDGET_EXCEEDED`), not as an error.

**Why this is safe under concurrency.** The `UPDATE` takes a row-level lock on
the campaign. A concurrent `UPDATE` on the same row waits for that lock. Under
the default `READ COMMITTED` isolation level, once the first transaction
commits, PostgreSQL re-evaluates the second update's `WHERE` clause against the
newly committed row before applying it. Two auctions therefore cannot both
spend the last of a budget. The `CHECK (remaining_budget >= 0)` constraint is a
second line of defense: an overspend caused by an application bug fails the
transaction instead of writing a negative balance.

**Why there is no `SELECT ... FOR UPDATE`.** The update already takes the lock
it needs. A separate locking read would add a round trip and hold the lock
longer, which only helps when application code must read the balance and make
a decision before writing.

**Contention limit (not implemented).** Every auction won by the same campaign
serializes on that campaign's row, so very high per-campaign win rates would
make this row the bottleneck. Two standard ways to address it:

- Keep a Redis copy of each budget and reserve with a Lua script that checks
  and decrements in one step, reconciling against Postgres periodically.
  Plain `DECRBY` is not enough on its own, because it can take the balance
  below zero.
- Pre-allocate slices of each budget to workers so most reservations never
  touch the shared row.

## 5. Why PostgreSQL

The domain is relational, and its writes need strong consistency:

- Budgets must never go negative under concurrent writes, which calls for
  transactions and row-level locking.
- Campaigns, creatives, bids and auctions have real foreign-key relationships
  that are queried in both directions (campaign → bids, bid → campaign).
- Reporting queries are aggregate-and-filter (`GROUP BY` over time ranges),
  which SQL and the Postgres planner handle well.
- There is no need for flexible document shapes, the main reason to prefer a
  document store.
