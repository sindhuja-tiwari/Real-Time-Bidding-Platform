# EvidenceOps demo: one incident, end to end

This walks one incident through EvidenceOps the way a web UI would: over the
[HTTP API](evidenceops.md#http-api), driven by `python -m evidenceops.demo`.
Steps 1 to 5 below are the script's real output from 2026-10-19 (long lines wrapped); steps 6 and 7
show what happens after a person approves the fix, using the sandbox result
recorded for the same scenario in the suite run.

## Running it yourself

```bash
pip install -r evidenceops/requirements.txt
python -m evidenceops serve &                      # API on 127.0.0.1:8100
python -m evidenceops.demo s03-db-pool-exhaustion  # about 4 minutes, plus ~5 if you approve the fix
```

The demo needs Docker and the host ports the platform uses (stop the dev stack
first). It pauses at step 5 and tests the fix only if you type your name; it
never approves anything itself. `--run <run_id>` reuses a recorded run instead
of recording a new one, `--method agent --provider gemini` uses a model
instead of the keyless `agent_offline` investigator, and `--quick` halves the
traffic phases.

## 1. Reproduce the incident on a fresh platform

`POST /runs {"scenario_ids": ["s03-db-pool-exhaustion"]}` returns a job. The
harness tears down and rebuilds the whole platform, drives open-loop auction
traffic, and part-way through deploys a release that, among other changes,
shrinks the database connection pool.

```
== 1. Reproduce 's03-db-pool-exhaustion' on a fresh platform
  recording: succeeded after 198s
  run 20261019T182402Z-s03-db-pool-exhaustion: success rate 97.8% -> 0.0%
```

## 2. What the on-call engineer gets

`GET /runs/{run_id}` returns the report and the deployment log, never the
answer key. The release changed three settings; only two of them matter.

```
== 2. The incident, as an on-call engineer gets it
  Auction success rate dropped sharply shortly after the auction backend was deployed this
  afternoon. Identify the likely cause, show the supporting evidence, and test a remediation
  without touching the live system.
  deploy 2026-10-19T18:25:03.815+00:00 -> 1.0.0
  deploy 2026-10-19T18:25:57.677+00:00 -> 1.3.0: DB_MAX_OVERFLOW 10->0, DB_POOL_SIZE 20->2, EVENT_MAX_RETRIES 4->3
```

## 3. Investigate with read-only tools

`POST /runs/{run_id}/investigations {"method": "agent_offline"}` runs the
investigator. Every claim in its report cites an evidence id from a tool call
it actually made; the UI can show each piece with
`GET /runs/{run_id}/investigations/agent_offline`.

```
== 3. Investigate with agent_offline
  investigating: succeeded after 3s
  1. db_pool_exhaustion (100%): auction p50 went from 125ms to 6677ms with 248 PENDING auctions;
     waiting for a DB connection: p95 13ms before, 30002ms after; 67 'sqlalchemy.exc.TimeoutError:
     QueuePool limit of size 2 overf' errors (logs/backend.log:5168); Postgres itself is quiet (at
     most 4 busy connections), so the wait is in the app's pool; deploy changed DB_MAX_OVERFLOW
     10 -> 0; deploy changed DB_POOL_SIZE 20 -> 2; in the slowest trace, db.pool.acquire took
     30233ms of the request
  9 read-only tool calls; evidence for the top hypothesis:
   E4 auction_outcomes({"start": "2026-10-19T18:25:49.059+00:00", "end": "2026-10-19T18:26:51.418+00:00"})
   E5 span_latency({"name": "db.pool.acquire", "start": "2026-10-19T18:25:09.059+00:00", "end": "2026-10-19T18:25:49.059+00:00"})
   E6 span_latency({"name": "db.pool.acquire", "start": "2026-10-19T18:25:49.059+00:00", "end": "2026-10-19T18:26:51.418+00:00"})
   E7 log_events({"service": "backend", "start": "2026-10-19T18:25:49.059+00:00", "end": "2026-10-19T18:26:51.418+00:00", "contains": "Error"})
```

A person can check any of it with the same tools. For example,
`POST /runs/{run_id}/tools/db_connections` with the incident window shows
Postgres mostly idle (2 idle, 2 idle in transaction) while requests waited
30 seconds for a connection: the bottleneck is the application's pool, not
the database.

## 4. Propose a fix from the allowlist

`POST /runs/{run_id}/remediation/propose` turns the diagnosis into typed,
bounded changes. It rolls back only the two settings that explain the
diagnosis and leaves the unrelated `EVENT_MAX_RETRIES` change alone. The digest
identifies this exact proposal.

```
== 4. Propose a remediation from the allowlist
  fix: roll back the db_pool_exhaustion settings changed by the suspect deploy: DB_MAX_OVERFLOW, DB_POOL_SIZE
   - {"kind": "deploy_setting", "setting": "DB_MAX_OVERFLOW", "value": "10", "rolled_back": true}
   - {"kind": "deploy_setting", "setting": "DB_POOL_SIZE", "value": "20", "rolled_back": true}
  digest 2930869fb31b276d
```

## 5. A person approves it

Nothing runs until a person approves. In a UI this is a button next to the
proposal; over the API it is
`POST /runs/{run_id}/remediation/approve {"method", "approver", "digest"}`.
If the proposal changed after it was reviewed, the digest no longer matches
and approval fails. The recorded demo ran without a terminal, so it stopped
here:

```
== 5. Approval (a person, not the investigator)
  stdin is not a terminal, so nothing is approved; stopping here.
```

## 6. Test the fix in a disposable platform

After approval, `POST /runs/{run_id}/remediation/test` rebuilds a fresh copy
of the platform, replays the same incident, applies the approved changes
mid-incident, and measures whether the platform recovers. For this scenario
in the suite run (approved by Rishabh):

```
VERIFIED: success rate 99.7% before, 0.0% during, 99.6% after the fix
```

## 7. Grade against the answer key

`GET /runs/{run_id}/grading` is the only endpoint that reads the answer key.
For the run above:

```
ground truth: db_pool_exhaustion
 agent_offline    predicted db_pool_exhaustion  top-1 correct
```

Across all 22 incidents, and compared with the fixed runbook, see
[Results across the suite](../evidenceops/README.md#results-across-the-suite).
