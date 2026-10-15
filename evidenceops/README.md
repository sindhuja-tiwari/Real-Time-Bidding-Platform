# EvidenceOps

An incident investigator for the RTB platform in this repository, built so
its diagnoses can be checked against known causes and its remediations
tested in a disposable copy of the platform.

The target question:

> Auction success rate dropped after a deployment. Identify the likely cause,
> show the supporting evidence, and test a remediation without touching the
> live system.

This directory currently holds **milestones 1 to 3**:

- a reproducible incident harness with three injected failures and recorded
  ground truth,
- OpenTelemetry traces from the platform,
- read-only diagnostic tools over a recorded run,
- a tool-using investigator (Claude) that has to cite evidence for every claim,
- two baselines to compare it with: a fixed diagnostic workflow and a
  log-only prompt, and
- a grader that scores any investigation method against ground truth.

Remediation experiments and the larger scenario suite come next (see
[Roadmap](#roadmap)).

## Quick start

Requirements: Docker with Compose v2, Python 3.10+.

```bash
pip install -r evidenceops/requirements.txt

python -m evidenceops list          # scenarios and their root-cause category
python -m evidenceops validate      # static checks, no Docker needed
python -m evidenceops run s02-global-timeout-misconfigured
python -m evidenceops run --all     # every scenario, about 3 minutes each
python -m evidenceops investigate   # run the fixed workflow on every recorded run
python -m evidenceops investigate --method agent_offline   # no API key needed
python -m evidenceops investigate --method agent           # needs ANTHROPIC_API_KEY
python -m evidenceops investigate --method log_only        # needs ANTHROPIC_API_KEY
python -m evidenceops evaluate      # grade saved investigations against ground truth
pytest evidenceops/tests            # unit tests, no Docker needed
```

Run from the repository root. The harness uses its own Compose project
(`rtb-evidenceops`) but the same host ports as the dev stack, so stop the dev
stack first. Each run tears the platform down **including volumes**, starts it
fresh, seeds it, and records everything under `evidenceops/runs/<run_id>/`.
`--keep-up` leaves the stack running afterwards for poking around;
`--quick` halves the traffic phases.
Set `EVIDENCEOPS_EXTRA_COMPOSE` to a path (or `:`-separated paths) to layer
your own Compose overrides, such as prebuilt images, on top of the harness's.

## What a run does

1. **Reset.** `docker compose down -v`, start Postgres, Redis, Kafka, the DSP
   simulator, an OpenTelemetry collector, backend and worker, wait for health,
   and seed demo data (with budgets large enough that a long run never
   exhausts them).
2. **Warm up** for 5 seconds so caches and connection pools are primed.
3. **Baseline.** Open-loop auction traffic at a fixed rate from 20 simulated
   publishers. Open loop means requests keep arriving on schedule even when the
   platform slows down, like real publisher traffic.
4. **Incident.** The scenario's steps fire at their offsets: deployments and
   external DSP degradation, some causal and some decoys.
5. **Capture** logs, read-only database exports, metrics, and per-request
   outcomes, then **verify** the incident actually happened.

Success means HTTP 201 with auction status `COMPLETED` within the
publisher's 2 second timeout.

## Run directory layout

```
runs/<run_id>/
  observed/                          what an investigator may look at
    incident.json                    the report, telemetry window, alert timeline
    deployments.jsonl                deployment log, decoy changes included
    logs/<service>.log               container logs with timestamps
    db/auctions.csv, bids.csv, ...   read-only table exports
    db/pg_stat_activity.samples.jsonl  connection states every 5s
    metrics/scrapes.jsonl            backend /metrics every 5s
    traces/spans.otlp.jsonl          OpenTelemetry spans (OTLP JSON)
  investigations/<method>.json       reports written by `investigate`
  ground_truth/                      for graders only
    ground_truth.json                root cause, causal vs decoy steps, remediation
    timeline.jsonl                   every harness action, timestamped
    traffic.jsonl                    every request's outcome
    dsp_config_before.json / _after.json
    verification.json                measured baseline vs incident success rate
```

The split matters for evaluation. An investigator gets `observed/` only.
`incident.json` uses an opaque incident id, and all three scenarios share the
same report text, so nothing outside the evidence hints at the cause. Decoy
config changes ride along in the same deployments as the real cause.

## Scenarios

All three produce the same alert, a sharp success-rate drop right after a
deploy, so an investigator has to use the evidence to tell them apart.

| Scenario | Root cause | What separates it from the others |
|---|---|---|
| `s01-slow-external-bidders` | Four external DSPs slow to ~95–145ms, past their 100ms timeout. The deploy 12s earlier only changed a cache TTL and an admin rate limit. | TIMEOUT bids at ~100ms (the per-DSP budget), `dsp_timeout` log events, drop starts after the deploy rather than at it |
| `s02-global-timeout-misconfigured` | Deploy sets `AUCTION_GLOBAL_TIMEOUT_MS` from 100 to 15, next to two harmless changes. | TIMEOUT bids at exactly 15ms, `auction_global_timeout` with `deadline_ms=15`, server duration falls instead of rising |
| `s03-db-pool-exhaustion` | Deploy shrinks the DB pool from 20+10 to 2+0 while each auction holds a connection through the ~100ms DSP fan-out. | Client latency in seconds while server `duration_ms` stays ~100ms, DSP bids still VALID, exactly 2 connections `idle in transaction` |

s01 vs s02 is the "slow bidder or our own config?" distinction, and s01 vs
s03 is the "slow external bidder or database bottleneck?" distinction from the
project brief.

Each scenario's `ground_truth` names the root-cause category (from a fixed
taxonomy in `scenario.py`), the causal and decoy steps and settings, the
evidence that distinguishes it, and the remediation expected to restore
success above a threshold. Remediations are recorded now and will be executed
in a sandbox in milestone 4.

### Measured results

One run of `python -m evidenceops run --all` on a 4-core Linux machine:

| Scenario | Baseline success | Incident success | Evidence observed in the run |
|---|---|---|---|
| s01 slow bidders | 100.0% | 0.0% | All four degraded DSPs' bids become TIMEOUT at a median 100ms; 4,299 `dsp_timeout` log events; success back at 100% for the 10s after the deploy, then the collapse |
| s02 global timeout | 100.0% | 2.1% | Every DSP's TIMEOUT bids sit at exactly 15ms; 1,057 `auction_global_timeout` events with `deadline_ms=15`; median auction duration falls from 115ms to 20ms |
| s03 DB pool | 100.0% | 0.1% | Publishers time out at 2s while DSP bids stay VALID at normal latency; QueuePool timeout errors in the backend log; Postgres connections drop to a handful |

A deploy restarts the backend and costs about 7 seconds of failed requests.
Verification only measures the incident from 5 seconds after the last causal
step finished, so that blip never counts toward the drop. DSP-C always times
out, even in the baseline (it is seeded at 150ms latency), which gives
investigators some realistic background noise to rule out.

## Telemetry

The backend exports traces when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. The
harness overlay sets it and adds a collector that writes spans to a file.
Tracing is off in the normal dev stack. Each auction trace contains these
spans:

| Span | Key attributes | Separates |
|---|---|---|
| `db.pool.acquire` | `db.pool.size`, `db.pool.checked_out_before` | time spent waiting for a pooled connection, which is the signature of pool exhaustion |
| `auction` | `auction.status`, `auction.winning_dsp` | the overall outcome |
| `dsp.fanout` | `auction.global_timeout_ms`, `dsp.deadline_hit`, `dsp.timeouts` | the deadline actually in force |
| `dsp.bid` | `dsp.name`, `dsp.timeout_ms`, `dsp.outcome`, `dsp.response_time_ms` | slow bidders from a short deadline |

Traces also include FastAPI request spans. Per-query SQLAlchemy spans were
left out: they cost enough CPU to stall the single backend process at about
24 auctions/s.

## Diagnostic tools

`telemetry.py` holds the only interface an investigator gets to a run. Every
tool is read-only and works on `observed/` only. Each call is stored under an
evidence id (`E1`, `E2`, ...) that hypotheses must cite:

| Tool | Returns |
|---|---|
| `alert_timeline` | the report and success rate / latency per 10s |
| `list_deployments` | every deploy with its config diff |
| `auction_outcomes(start, end)` | auction status counts, server duration percentiles |
| `bid_outcomes(start, end)` | per-DSP outcome counts, timeout share, response times by outcome, configured DSP timeouts |
| `span_latency(name, start, end, group_by)` | span duration percentiles, optionally per attribute, with the slowest trace id |
| `trace_detail(trace_id)` | one trace's spans in order |
| `log_events(service, start, end, contains)` | log events counted by kind, each with a `logs/<service>.log:<line>` reference |
| `db_connections(start, end)` | sampled Postgres connection states and lock waits |

## Investigation reports and grading

Every method writes the same report shape (`investigation.py`):

- a timeline,
- ranked hypotheses, each with a root-cause category, a statement, and the
  evidence ids that support it,
- an abstain flag with a reason,
- every evidence item collected, and
- tool calls, elapsed time and cost.

`evaluate` grades each report against `ground_truth/` and reports:

- **Top-1 and top-3 accuracy** on clear incidents.
- **Unsupported diagnosis rate.** A top hypothesis that cites no evidence the
  method actually collected counts as unsupported, right or wrong.
- **Correct abstention** on ambiguous incidents, and the abstention rate on
  clear ones, where abstaining counts as a miss.
- **Tool calls, time to correct diagnosis, and cost** per investigation.

## Baseline: fixed diagnostic workflow

`baselines/fixed_workflow.py` is a runbook encoded as code. It runs the same
10 tool calls in the same order on every incident:

1. Find the onset: a sustained drop below half the baseline success rate.
2. Find deploys in the 60s before the onset.
3. Compare auctions, per-DSP bids, DB pool wait, backend log events and
   Postgres connections before and after the onset.

It then scores the three categories it has rules for, using fixed
thresholds, and abstains when the best score is weak or two causes are close.
It never asks a follow-up question of the data.

On a fresh `run --all` with traces enabled:

| Scenario | Fixed workflow's top answer | Runner-up |
|---|---|---|
| s01 slow bidders | `external_dsp_latency`: "DSP timeout share rose from 3% to 99%, with TIMEOUT bids at ~100ms, the 100ms per-DSP budget" | `config_regression` (0.2): the 1.1.0 deploy |
| s02 global timeout | `config_regression`: "...TIMEOUT bids are cut at ~15ms, well under the 100ms per-DSP budget; a deploy changed AUCTION_GLOBAL_TIMEOUT_MS" | none |
| s03 DB pool | `db_pool_exhaustion`: "DB pool acquire p95 rose from 5ms to 30001ms; 59 pool timeout errors in backend logs" | `config_regression` (0.2) |

Top-1 3/3, no abstentions, no unsupported diagnoses, 10 tool calls and
about 0.3s per investigation, no model cost.

**Read that 3/3 with care.** The workflow's thresholds were written by someone
who knew these three scenarios, so it is effectively fitted to them. It
proves the evidence is sufficient and the grader works. It does not prove
that a runbook is enough. The real comparison needs scenarios the rules were
not written for, plus ambiguous incidents. Those come with the scenario
expansion in milestone 5, where this baseline is expected to drop sharply:
it has no rules at all for missing indexes, poison messages or duplicate
delivery.

## The investigator

`agent/` is a tool-using investigator. The model gets the on-call report and
the eight read-only tools above, decides which to call, and finishes by
calling `submit_report` with a timeline and ranked hypotheses. The system
prompt (`agent/spec.py`) asks it to keep several causes open, call a tool
whose answer would separate the leading candidates before settling, treat a
deploy near the onset as a suspect rather than a conclusion, and abstain when
the evidence does not separate the causes.

The harness (`agent/loop.py`), not the model, enforces what the grader relies
on:

- **Read-only tools only.** Tool names are checked against the registry and
  arguments against each tool's signature. An unknown tool or bad argument
  returns an error to the model and produces no evidence. There is no shell
  tool.
- **Citations must be real.** A report that cites an evidence id the model
  never received is sent back with the problems listed. After two rejections
  the run ends as an abstention marked `harness:`, so a model cannot get a
  diagnosis graded by inventing evidence.
- **A tool budget** (20 calls by default). Past it, tool calls are refused and
  the model is told to submit.
- **Every request and tool result is kept** in
  `investigations/agent.transcript.json`, so any diagnosis can be traced back
  to the data it was based on.

Model settings follow current Claude API guidance: `claude-opus-5-5` with
adaptive thinking at `high` effort (both overridable with `--model` and
`--effort`), prompt caching on the static prefix (tools and system prompt), and
server-side fallback if a safety classifier declines a request. Cost is
computed from the token usage of each response.

### Running it

The real agent needs an Anthropic API key. Create one at
<https://console.anthropic.com/settings/keys> and export it:

```bash
export ANTHROPIC_API_KEY=...
python -m evidenceops investigate --method agent
```

Keys are read from the environment only; nothing in this repository stores
one.

### Without a key: `agent_offline`

`agent/offline.py` stands in for the model so the whole pipeline (loop,
citation checks, transcript, grading) runs and is tested without a key. It is
a rule-driven policy, not an LLM, and its scores say nothing about how the
model will do. It works the way the system prompt asks the model to: it reads
the symptom first (auctions stuck, or bidders not answering) and only calls
the tools that separate the causes that symptom allows, then drills into the
slowest trace. On the three recorded runs it gets the same 3/3 as the fixed
workflow with 8 to 9 tool calls instead of 10. That comparison has the same
caveat as the fixed workflow: both were written with these scenarios in view.

## Baseline: log-only prompt

`baselines/log_only.py` is "paste the logs into a chatbot": one Claude call
with the on-call report and the raw backend and worker logs for the telemetry
window, no tools, no traces, no database and no deployment records. Repeated
lines of the same kind are collapsed so the window fits in one request. It
answers in the same report schema through structured outputs, citing each
service's log excerpt as one evidence id. It shows what the tools and traces
add over the logs alone.

## Safety model

- **No command execution from scenarios.** A scenario can only `deploy`
  (change settings from a fixed allowlist on backend and worker) or
  `dsp_config` (change allowlisted fields of the simulated DSPs). There is no
  shell action, and the harness invokes Docker with fixed argument lists and
  no shell.
- **Read-only evidence.** Database exports are named queries run with
  `default_transaction_read_only=on`.
- **Disposable environment.** Runs use their own Compose project and wipe
  its volumes; nothing touches a long-lived database.

The investigator follows the same rules: its tools are read-only functions
over recorded files, and model output is never executed as a shell command.
Remediation (milestone 4) will run only in a disposable environment, after
approval, through the same allowlisted `deploy` and `dsp_config` actions.

## Platform fixes found while making it reproducible

Running the platform live under sustained load surfaced bugs that the
mocked unit tests could not see. They are fixed in this branch:

- **Every auction failed with a 500.** `reserve_budget` mixed a float bid with
  the `NUMERIC` budget column inside SQLAlchemy's session sync (`TypeError`).
- **Every auction with a timed-out DSP failed.** Timeout and no-bid outcomes
  were stored with a nil campaign id, which violates `bid.campaign_id`'s
  foreign key. Migration `0003` makes the column nullable for those rows. The
  failure path also now rolls back before recording `FAILED`.
- **Second-price auctions sometimes failed.** The floor price came through as
  a `Decimal`, which broke the Prometheus histogram.
- **Throughput collapsed permanently after a burst of slow DSPs.** Cancelling
  in-flight httpx requests with `asyncio.wait_for` left pooled connections
  stuck in `CONNECTING`; once the pool filled, every DSP call timed out, even
  to healthy DSPs, until restart. The fan-out now uses httpx's own timeouts
  and stops waiting at the deadline without cancelling requests. A regression
  test covers it. This failure mode is a good future scenario.
- Debug logs from httpx, httpcore and aiokafka are now at WARNING, since they
  produced several log lines per DSP call.

Small additions that keep defaults unchanged: `DB_POOL_SIZE`,
`DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`, `APP_VERSION` (shown on
`/health`), `SEED_CAMPAIGN_BUDGET`, and `SIM_RANDOM_SEED` for the DSP simulator.

One backend process tops out at roughly 45 auctions/s on a 4-core machine,
CPU bound. Scenarios run at 20–30 auctions/s to stay below that.

## Roadmap

1. ~~Reproducible platform, three injected failures with ground truth.~~
2. ~~Telemetry (OpenTelemetry traces across auction, DSP fan-out and DB) and a
   fixed diagnostic baseline workflow.~~
3. ~~A tool-using investigator with structured hypotheses and evidence
   references, plus a log-only prompt baseline.~~
4. Sandbox remediation experiments behind an approval gate; ambiguous
   scenarios where abstaining is the right answer.
5. Expand to 20–30 scenarios (missing index, poison message, duplicate
   delivery, connection leak cascade, budget exhaustion, ...), compare the
   investigator with both baselines on accuracy, abstention, time, tool calls
   and cost.
6. Demo, architecture write-up, and benchmark instructions.
