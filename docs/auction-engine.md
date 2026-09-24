# Auction Engine

Code: `backend/app/services/bidding/{types,validation,strategies,client}.py`,
orchestrated by `backend/app/services/auction/service.py`.

## Pipeline

```
AuctionService.run_auction()
  1. idempotency check           AuctionRepository.get_by_request_id
  2. eligible campaigns + DSPs   CampaignService / DSPService (Redis cache-aside)
  3. concurrent bid collection   bidding.client.collect_bids()
  4. per-bid validation          bidding.validation.validate_bid()
  5. ranking / winner selection  bidding.strategies.AuctionStrategy
  6. atomic budget reservation   CampaignRepository.reserve_budget()
  7. persistence                 AuctionRepository (Postgres)
  8. fire-and-forget event       events.producer.publish_auction_completed()
```

## Concurrency (Section 5)

`bidding/client.py::collect_bids` fans out to every eligible DSP with
`asyncio.create_task`, never sequentially. Two timeout layers:

- **Per-DSP** (`dsp.timeout_ms`): enforced with `asyncio.wait_for` around each
  individual HTTP call. A slow DSP only costs its own budget.
- **Global** (`AUCTION_GLOBAL_TIMEOUT_MS`, default 100ms): enforced with
  `asyncio.wait_for` around `asyncio.gather(...)`. If the deadline fires,
  any still-running tasks are cancelled and given a synthetic `TIMEOUT`
  result instead of raising -- the auction always returns a complete,
  gap-free list of one outcome per DSP.

This is verified, not just asserted: `tests/test_concurrency.py` measures
wall-clock time for 3 DSPs at 40ms each and confirms the fan-out completes
in well under the 120ms a sequential implementation would take, and confirms
that N slow DSPs never push total auction time past the global deadline.

## Bid validation (Section 6, steps 1-5)

Pure function `validate_bid(bid, campaign_snapshot, floor_price, country,
device)` in `bidding/validation.py`. Order of checks:

1. Already-terminal status (TIMEOUT from the transport layer) passes through
   unchanged.
2. Unknown/missing campaign -> `INVALID`.
3. Campaign not `ACTIVE` -> `INVALID`.
4. Targeting mismatch (country/device) -> `INVALID`.
5. Below `max(ad_slot.floor_price, campaign.bid_floor)` -> `BELOW_FLOOR`.
6. Non-positive or exceeds `campaign.remaining_budget` -> `BUDGET_EXCEEDED`.
7. Otherwise -> `VALID`.

This function has zero I/O and zero FastAPI/SQLAlchemy/Redis imports, which
is why it's exhaustively unit tested (`tests/test_bid_validation.py`)
without any infrastructure.

## Ranking strategies (Section 6/7)

`AuctionStrategy` is an abstract base with one method, `select(bids,
floor_price) -> AuctionResult`. Three implementations ship:

| Strategy | Winner | Clearing price |
|---|---|---|
| `HighestBidStrategy` (FIRST_PRICE) | highest raw bid | what it bid |
| `SecondPriceStrategy` (SECOND_PRICE) | highest raw bid | `max(second_highest_bid, floor_price)` |
| `QualityAdjustedStrategy` | highest `bid * quality_score` | what it bid |

Tie-breaking in `SecondPriceStrategy`: equal top bids are broken by response
time (the faster DSP wins) -- rewarding low latency is deliberate, given the
whole project's thesis is that latency matters.

Adding a fourth strategy means writing a class and adding one line to
`get_strategy()`'s dict -- nothing in the API layer, repository layer, or
`AuctionService` needs to change (Open/Closed principle).

## Idempotency (Section 11)

`Auction.request_id` has a `UNIQUE` constraint. `AuctionService.run_auction`
checks `get_by_request_id` before doing any work; if a row already exists,
it replays that row's result instead of running a second auction. If two
identical requests race each other, `create_pending`'s `INSERT` will
succeed for exactly one of them (Postgres enforces the uniqueness); the
loser catches the resulting `IntegrityError`, re-reads the winner's row, and
returns that instead of erroring out.

The `Idempotency-Key` HTTP header, when present, overrides the request
body's `request_id` as the dedup key, matching common REST conventions for
safe retries.

## Budget concurrency (Section 10)

`CampaignRepository.reserve_budget` uses `SELECT ... FOR UPDATE` to lock the
campaign row, then an `UPDATE ... WHERE remaining_budget >= amount` that
re-checks the balance under the lock. Two concurrent auctions targeting the
same campaign serialize on this statement; whichever loses the race gets
zero rows updated, is told `BUDGET_EXCEEDED`, and that bid is dropped from
the ranking rather than allowed to overspend.

This is the Phase-1-simple, definitely-correct version. It does mean every
winning bid for a given campaign is serialized through one row lock, which
becomes a throughput ceiling for extremely popular single campaigns at very
high QPS -- see docs/performance.md's discussion of that trade-off and how a
Redis `DECRBY`-based fast path with periodic Postgres reconciliation would
relax it.
