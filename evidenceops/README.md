# EvidenceOps

An incident investigator for the RTB platform in this repository, built so
its diagnoses can be checked against known causes and its remediations
tested in a disposable copy of the platform.

The target question:

> Auction success rate dropped after a deployment. Identify the likely cause,
> show the supporting evidence, and test a remediation without touching the
> live system.

This directory currently holds **milestones 1 to 5**:

- a reproducible incident harness with 22 injected incidents across six root
  causes, each with recorded ground truth,
- OpenTelemetry traces from the platform,
- read-only diagnostic tools over a recorded run,
- a tool-using investigator (Claude) that has to cite evidence for every claim,
- two baselines to compare it with: a fixed diagnostic workflow and a
  log-only prompt,
- approval-gated remediation experiments in a disposable copy of the
  platform, and an ambiguous scenario where abstaining is the right answer,
- a grader that scores any investigation method against ground truth, and
  [results across the whole suite](#results-across-the-suite).

## Quick start

Requirements: Docker with Compose v2, Python 3.10+.

```bash
pip install -r evidenceops/requirements.txt

python -m evidenceops list          # scenarios and their root-cause category
python -m evidenceops validate      # static checks, no Docker needed
python -m evidenceops run s02-global-timeout-misconfigured
python -m evidenceops run --all     # every scenario, 3 to 5 minutes each (about 90 minutes)
python -m evidenceops investigate   # run the fixed workflow on every recorded run
python -m evidenceops investigate --method agent_offline   # no API key needed
python -m evidenceops investigate --method agent           # needs ANTHROPIC_API_KEY
python -m evidenceops investigate --method log_only        # needs ANTHROPIC_API_KEY
python -m evidenceops investigate --method agent --provider gemini   # free tier, GEMINI_API_KEY
python -m evidenceops remediate --method agent_offline   # propose fixes; nothing runs yet
python -m evidenceops remediate --method agent_offline --approve "Your Name"   # test them in a sandbox
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
4. **Incident.** The scenario's steps fire at their offsets, some causal and
   some decoys. A step is one of:
   - `deploy`: change allowlisted settings on backend and worker, optionally
     running named schema migrations first (`faults.MIGRATIONS`);
   - `dsp_config`: degrade simulated external bidders;
   - `kafka_publish`: publish one of the fixed malformed messages in
     `faults.POISON_TEMPLATES` to `auction-events`, as a buggy producer would;
   - `kafka_replay`: rewind a worker consumer group's offsets by some minutes,
     as an operator replaying a topic would.

   A scenario can also ask for `setup.history_auctions`: old auctions written
   before traffic starts, so the auction table is large enough for a missing
   index to matter.
5. **Capture** logs, read-only database exports, metrics, and per-request
   outcomes, then **verify** the incident actually happened.

Two kinds of alert open an incident. `auction_success_rate` is verified by a
drop in success rate. `analytics_backlog` and `analytics_overcount` are
verified by the analytics rollup drifting at least 300 auctions behind, or
ahead of, the auction table while auctions themselves stay healthy.

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
    db/indexes.csv                   index definitions at the end of the run
    db/<query>.samples.jsonl         every 5s: connection states, running
                                     statements, table scan counters, and
                                     auction table vs analytics rollup counts
    kafka/consumer_groups.samples.jsonl  consumer offsets and lag every 10s
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
`incident.json` uses an opaque incident id, and all scenarios with the same
alert share the same report text, so nothing outside the evidence hints at the
cause. Decoy
config changes ride along in the same deployments as the real cause.

## Scenarios

22 scenarios, six root causes, three kinds of alert. Every scenario with the
same alert shares one report text, and most carry decoys: harmless settings in
the same deploy, an unrelated deploy just before the onset, extra migrations,
or a resized pool that looks relevant. Two are ambiguous on purpose.

| Root cause | Scenarios | What has to be told apart |
|---|---|---|
| `external_dsp_latency` | s01, s06, s07, s22 | slow bidders vs a deploy that landed just before; one variant has no deploy at all |
| `config_regression` | s02, s09, s10, s11 | a bad deadline or rate limit vs harmless settings in the same deploy, or the earlier of two deploys |
| `db_pool_exhaustion` | s03, s12, s13, s14 | a starved app pool (Postgres idle) vs slow queries; one variant fails fast after 1s instead of queueing |
| `missing_index` | s05, s15, s16 | a migration that drops an index on a 2M-row table vs the pool it exhausts, a pool resize, and decoy migrations |
| `poison_message` | s08, s17, s18 | an undecodable message crash-looping the worker, or rejected messages stalling it in retries, vs a deploy that restarted it |
| `duplicate_delivery_idempotency` | s19, s20 | a consumer replay double-counting in a non-idempotent rollup vs a worker deploy |
| ambiguous | s04, s21 | a shorter deadline and slower bidders at the same moment; telemetry cannot say which would break auctions alone |

Each scenario's `ground_truth` names the root-cause category (from a fixed
taxonomy in `scenario.py`), the causal and decoy steps and settings, the
evidence that distinguishes it, and the remediation expected to fix it.

### Measured results

One run of every scenario on a 4-core Linux machine, with each method's top
answer (✓ correct; on an ambiguous scenario, abstaining is correct):

| Scenario | Alert | True cause | Measured | Fixed workflow | agent_offline |
|---|---|---|---|---|---|
| `s01-slow-external-bidders`: External bidders slow down right after an unrelated deploy | success rate | `external_dsp_latency` | 100.0% → 0.3% | `external_dsp_latency` ✓ | `external_dsp_latency` ✓ |
| `s02-global-timeout-misconfigured`: A deploy shortens the auction deadline to 15ms | success rate | `config_regression` | 99.9% → 3.5% | `config_regression` ✓ | `config_regression` ✓ |
| `s03-db-pool-exhaustion`: A deploy shrinks the database connection pool below peak demand | success rate | `db_pool_exhaustion` | 100.0% → 0.0% | `db_pool_exhaustion` ✓ | `db_pool_exhaustion` ✓ |
| `s04-ambiguous-deadline-and-slow-bidders`: A shorter deadline ships just as the bidders slow down | success rate | ambiguous: `config_regression` / `external_dsp_latency` | 100.0% → 0.0% | abstains ✓ | abstains ✓ |
| `s05-missing-index-after-migration`: A schema migration drops the index behind the idempotency lookup | success rate | `missing_index` | 99.9% → 0.0% | `db_pool_exhaustion` ✗ | `missing_index` ✓ |
| `s06-bidders-slow-after-cache-deploy`: The healthy bidders slow past their timeout just after a cache-tuning deploy | success rate | `external_dsp_latency` | 99.5% → 0.0% | `external_dsp_latency` ✓ | `external_dsp_latency` ✓ |
| `s07-bidders-degrade-in-stages`: Every bidder degrades in two stages with no deploy at all | success rate | `external_dsp_latency` | 99.5% → 0.0% | `external_dsp_latency` ✓ | `external_dsp_latency` ✓ |
| `s08-poison-message-crash-loop`: A malformed event crash-loops the worker and analytics stops updating | analytics behind | `poison_message` | drift 1 → 1096 | `poison_message` ✓ | `poison_message` ✓ |
| `s09-publisher-rate-limit-lowered`: A deploy lowers the per-publisher rate limit and turns traffic away | success rate | `config_regression` | 99.5% → 0.0% | abstains ✗ | `config_regression` ✓ |
| `s10-deadline-cut-with-pool-increase`: A deploy shortens the auction deadline and also grows the DB pool | success rate | `config_regression` | 99.6% → 47.7% | `config_regression` ✓ | `config_regression` ✓ |
| `s11-second-of-two-deploys-cuts-deadline`: Two deploys land close together and only the second one is bad | success rate | `config_regression` | 99.9% → 20.8% | `config_regression` ✓ | `config_regression` ✓ |
| `s12-pool-too-small-for-peak`: A modest pool cut is fine at low traffic but not at today's rate | success rate | `db_pool_exhaustion` | 98.3% → 0.2% | `db_pool_exhaustion` ✓ | `db_pool_exhaustion` ✓ |
| `s13-small-pool-fails-fast`: A small pool with a 1s checkout timeout fails auctions outright | success rate | `db_pool_exhaustion` | 99.6% → 30.6% | `db_pool_exhaustion` ✓ | `db_pool_exhaustion` ✓ |
| `s14-pool-cut-bundled-with-deadline-raise`: A deploy shrinks the pool and also raises the auction deadline | success rate | `db_pool_exhaustion` | 100.0% → 0.0% | `db_pool_exhaustion` ✓ | `db_pool_exhaustion` ✓ |
| `s15-missing-index-among-three-migrations`: A release ships three migrations and one of them loses an index | success rate | `missing_index` | 99.7% → 0.0% | `db_pool_exhaustion` ✗ | `missing_index` ✓ |
| `s16-missing-index-with-pool-resize`: A migration loses an index in the same deploy that resizes the pool | success rate | `missing_index` | 100.0% → 0.0% | `db_pool_exhaustion` ✗ | `missing_index` ✓ |
| `s17-legacy-events-retry-storm`: A burst of old-format events stalls the worker in retries | analytics behind | `poison_message` | drift 0 → 1113 | `poison_message` ✓ | `poison_message` ✓ |
| `s18-poison-message-after-worker-deploy`: A malformed event arrives just after a deploy restarts the worker | analytics behind | `poison_message` | drift 1 → 899 | `poison_message` ✓ | `poison_message` ✓ |
| `s19-replay-double-counts-analytics`: An operator replays the analytics consumer and the rollup double-counts | analytics overcount | `duplicate_delivery_idempotency` | drift 0 → 1002 | abstains ✗ | `duplicate_delivery_idempotency` ✓ |
| `s20-replay-after-worker-retry-change`: A worker deploy is followed by a consumer replay that double-counts | analytics overcount | `duplicate_delivery_idempotency` | drift 0 → 1199 | abstains ✗ | `duplicate_delivery_idempotency` ✓ |
| `s21-ambiguous-deadline-60-and-bidders-70`: The deadline drops to 60ms while bidders slow to about 70ms | success rate | ambiguous: `config_regression` / `external_dsp_latency` | 99.1% → 17.3% | abstains ✓ | abstains ✓ |
| `s22-slow-bidders-after-pool-resize`: Bidders slow down right after a deploy resized the DB pool | success rate | `external_dsp_latency` | 99.9% → 0.0% | `external_dsp_latency` ✓ | `external_dsp_latency` ✓ |

A deploy restarts the backend and costs about 7 seconds of failed requests.
Verification only measures the incident from 5 seconds after the last causal
step finished, so that blip never counts toward the drop. DSP-C always times
out, even in the baseline (it is seeded at 150ms latency), which gives
investigators some realistic background noise to rule out. Analytics drift is
finished auctions minus auctions counted by the rollup; it is negative for an
overcount, and shown here as the size of the drift.

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
| `slow_queries(start, end)` | statements seen running, grouped by shape with literals removed, and how long they had been running |
| `table_scans(start, end)` | per-table sequential scans, rows read by them, and index scans in the window |
| `db_indexes(table)` | index and unique-constraint definitions at the end of the window |
| `consumer_lag(start, end)` | per consumer group: committed offset, lag, live members, where it stalled, and any rewind |
| `analytics_consistency(start, end)` | finished auctions vs auctions counted by the analytics rollup |
| `repeated_values(service, event, field, start, end)` | how often each value of a structured log field repeats, e.g. an auction id processed twice |

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

`baselines/fixed_workflow.py` is a runbook encoded as code. For a
success-rate alert it runs the same 10 tool calls in the same order:

1. Find the onset: a sustained drop below half the baseline success rate.
2. Find deploys in the 60s before the onset.
3. Compare auctions, per-DSP bids, DB pool wait, backend log events and
   Postgres connections before and after the onset.

It then scores the three categories it has rules for, using fixed
thresholds, and abstains when the best score is weak or two causes are close.
For an analytics alert it runs a shorter fixed checklist (deployments,
consumer lag, worker log events) with one rule: a worker that keeps failing on
messages while a group falls behind is a poison message. It never asks a
follow-up question of the data, and it has no rule for missing indexes or
duplicate delivery.

On the original three scenarios:

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
that a runbook is enough. See [Results across the suite](#results-across-the-suite)
for how it does on the scenarios it was not written for.

## The investigator

`agent/` is a tool-using investigator. The model gets the on-call report and
the fourteen read-only tools above, decides which to call, and finishes by
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

### Free-tier providers

`--provider gemini` or `--provider groq` runs the same agent and log-only
baseline on a model with a free tier, through their OpenAI-compatible chat
APIs (`agent/openai_compat.py`). The harness is unchanged: same tools, same
citation checks, same grading. Reports are saved as `agent_gemini`,
`log_only_groq` and so on, so they can be compared with the Claude runs.

| Provider | Get a key | Export | Default model |
|---|---|---|---|
| Gemini | <https://aistudio.google.com/apikey> | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| Groq | <https://console.groq.com/keys> | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |

Pass `--model` to use another model; provider model lists change often.
Free tiers have tight rate limits, and cost is recorded as $0 for them.

### Without a key: `agent_offline`

`agent/offline.py` stands in for the model so the whole pipeline (loop,
citation checks, transcript, grading) runs and is tested without a key. It is
a rule-driven policy, not an LLM, and its scores say nothing about how the
model will do. It works the way the system prompt asks the model to: it reads
the symptom first (auctions stuck, bidders not answering, requests turned
away, analytics behind or overcounting) and only calls the tools that separate
the causes that symptom allows, then drills into the slowest trace. When
Postgres turns out to be busy rather than idle, for example, it asks which
statements are running and which tables are being scanned before blaming the
connection pool. Its rules were written with these scenarios in view, so its
scores are an upper bound for a rule-based method, not a prediction of the
model's.

## Baseline: log-only prompt

`baselines/log_only.py` is "paste the logs into a chatbot": one Claude call
with the on-call report and the raw backend and worker logs for the telemetry
window, no tools, no traces, no database and no deployment records. Repeated
lines of the same kind are collapsed so the window fits in one request. It
answers in the same report schema through structured outputs, citing each
service's log excerpt as one evidence id. It shows what the tools and traces
add over the logs alone.

## Remediation experiments

`remediate` turns an investigation into a proposed fix, and tests it only
after a person approves it.

**What can be proposed** (`remediation.py`). A proposal is a list of typed
changes, and only these kinds exist:

- `deploy_setting`: set an allowlisted setting to a value inside fixed bounds.
- `rollback_setting`: restore a setting to its value before the last deploy
  that changed it, looked up in the run's deployment log.
- `dsp_timeout_ms`: set the per-DSP timeout on named DSP rows, through a new
  admin `PATCH /api/v1/dsps/{id}` endpoint.
- `rollback_migration`: run the fixed `down` SQL of a named migration from
  `faults.MIGRATIONS`, and only if a deploy in this run applied it.
- `skip_stuck_message`: stop the worker, move named consumer groups one
  message past their committed offset, and start it again.

Anything else, including a shell command, a setting outside the allowlist, or
a value out of bounds, fails to parse and is rejected. Nothing tries to
"clean it up" and run it anyway.

**Where proposals come from.** The investigator may include a remediation in
its report, and it is validated with the report. For methods that don't,
including the baselines, a rule planner derives one from the top hypothesis:

- a deploy-borne cause gets a rollback of the matching settings, never of the
  harmless decoy settings in the same deploy;
- slow bidders get longer per-DSP timeouts and a longer deadline;
- a missing index gets the migration named in the diagnosis rolled back;
- a crash-looping worker gets the undecodable message skipped, and a worker
  stalled retrying rejected messages gets `EVENT_MAX_RETRIES=0`, which
  dead-letters them on the first failure;
- duplicate delivery gets no proposal: the fix is code (record applied event
  ids in the rollup transaction) plus a data rebuild, neither of which is an
  allowlisted runtime change.

When a report abstained, the proposal is marked as an **experiment** rather
than a fix. It rolls back the suspect deploy's risky settings, so the result
tells you whether that deploy was a sufficient cause, which is the thing the
telemetry could not show.

**The approval gate.** Without `--approve`, `remediate` only writes
`remediation/<method>.proposal.json` with status `awaiting_approval` and
prints it. `--approve "Name"` then:

1. re-parses that exact file,
2. checks its digest, so a proposal edited after it was made is refused,
3. records who approved it and when, and only then
4. runs it.

**The sandbox** (`sandbox.py`). An approved remediation runs in a freshly built
copy of the platform with wiped volumes. The copy replays the original
incident's scenario step for step, applies the changes once the incident is
in full swing, and keeps traffic flowing for 90s more. The verdict needs both
of these in the same experiment:

- the incident reproduced, and
- the alerting metric recovered by the end. For success-rate alerts, success
  over the last 30s must be within 5 points of the experiment's own
  baseline; the first minute after the change is allowed for requests that
  were already queued to drain. For analytics alerts, the rollup's drift in the last samples
  must fall below a third of the alert threshold.

The possible verdicts are `verified`, `not_fixed` (it reproduced but did not
recover), or `inconclusive` (it never reproduced). `evaluate` reports the share
of tested remediations that were verified.

Results for all 20 proposals are in
[Results across the suite](#results-across-the-suite).

## Ambiguous incidents

`s04-ambiguous-deadline-and-slow-bidders` ships a deploy that trims the
auction deadline from 100ms to 80ms. Two seconds later, four bidders slow to
about 85ms. Neither change breaks auctions on its own. Together they make
every call to those bidders end at the 80ms cut, so their real latency never
shows up in the telemetry. A careful investigator can see two things:

- the deadline is cutting the calls, and
- the bidders did slow down: DSP-A went from about 26ms to timing out.

It cannot see whether the slowed bidders would fit the old deadline. The
grader therefore counts abstaining as correct here. It also records whether a
non-abstaining report kept both causes in its top three. An abstained report's
remediation, rolling the deadline back in the sandbox, is the experiment that
settles it.

On the recorded run (success 99.4% to 0%), both rule-based methods abstain:

| Method | Outcome | Why |
|---|---|---|
| fixed workflow | abstains | its two rules happen to score 0.6 and 0.5, inside its margin; its statement also wrongly calls the 80ms cut "the 100ms per-DSP budget" |
| agent_offline | abstains | it spots that the timeouts land at the global deadline, below the per-DSP budget, and that bidders which used to answer in ~38ms now hit it |

`s21-ambiguous-deadline-60-and-bidders-70` is the same trap at different
numbers: the deadline drops to 60ms while four bidders slow to about 72ms.
Both methods abstain on it too, and the rollback experiment recovers success
from 11.6% to 98.9%.

## Results across the suite

All 22 scenarios, recorded once each and investigated by both rule-based
methods. Run it yourself with `run --all`, `investigate` for each method, and
`evaluate`.

| | Fixed workflow | agent_offline |
|---|---|---|
| Top-1 accuracy (20 clear incidents) | 14/20 (70%) | 20/20 (100%) |
| Top-3 accuracy | 70% | 100% |
| Abstained on a clear incident | 3/20 | 0/20 |
| Correct abstention (2 ambiguous) | 2/2 | 2/2 |
| Unsupported diagnoses | 0 | 0 |
| Mean tool calls | 8.6 | 8.0 |
| Mean time to a correct diagnosis | 0.32s | 0.24s |
| Cost | $0 | $0 |
| Fixes verified in the sandbox | not proposed | 20/20 (100%) |

**Where the runbook fails, and why.** It blames the connection pool on all
three missing-index incidents: the pool really is exhausted, and it has no step
that asks what the connections are busy doing. It abstains on the rate-limit
incident because none of its rules looks at requests that never became
auctions, and on both double-count incidents because it has no rule for
duplicates. These are exactly the cases where the next question depends on the
last answer.

**How to read agent_offline's 100%.** Its rules were written by someone who
had these scenarios in front of them, so treat it as an upper bound for a
rule-based investigator and a check that the evidence is sufficient, not as a
measurement of the model. The model's numbers come from
`investigate --method agent` (or a free-tier provider) and the log-only
baseline from `--method log_only`; both need an API key, and neither has been
run for this table.

### Remediation experiments

Every agent_offline proposal across the suite was approved by a person and
tested in its own freshly built sandbox:

| Scenario | Change tested | Before | During | After | Verdict |
|---|---|---|---|---|---|
| `s01-slow-external-bidders` | `AUCTION_GLOBAL_TIMEOUT_MS=200`; timeout 200ms on DSP-A, DSP-B, DSP-D, DSP-E | 99.1% | 0.0% | 99.3% | verified |
| `s02-global-timeout-misconfigured` | `AUCTION_GLOBAL_TIMEOUT_MS=100` (rollback) | 99.2% | 0.6% | 99.3% | verified |
| `s03-db-pool-exhaustion` | `DB_MAX_OVERFLOW=10` (rollback); `DB_POOL_SIZE=20` (rollback) | 99.7% | 0.0% | 99.6% | verified |
| `s04-ambiguous-deadline-and-slow-bidders` (experiment) | `AUCTION_GLOBAL_TIMEOUT_MS=100` (rollback) | 99.4% | 0.0% | 95.4% | verified |
| `s05-missing-index-after-migration` | roll back `0004_auction_request_id_collation` | 99.4% | 0.0% | 99.4% | verified |
| `s06-bidders-slow-after-cache-deploy` | `AUCTION_GLOBAL_TIMEOUT_MS=200`; timeout 200ms on DSP-A, DSP-B, DSP-D, DSP-E | 99.2% | 0.0% | 99.5% | verified |
| `s07-bidders-degrade-in-stages` | `AUCTION_GLOBAL_TIMEOUT_MS=200`; timeout 200ms on DSP-A, DSP-B, DSP-D, DSP-E | 99.5% | 0.0% | 98.6% | verified |
| `s08-poison-message-crash-loop` | skip the stuck message in all three groups | drift 1 | drift 1099 | drift 1 | verified |
| `s09-publisher-rate-limit-lowered` | `RATE_LIMIT_PUBLISHER_PER_MIN=1000` (rollback) | 99.2% | 0.0% | 99.3% | verified |
| `s10-deadline-cut-with-pool-increase` | `AUCTION_GLOBAL_TIMEOUT_MS=100` (rollback) | 99.6% | 45.6% | 99.8% | verified |
| `s11-second-of-two-deploys-cuts-deadline` | `AUCTION_GLOBAL_TIMEOUT_MS=100` (rollback) | 99.6% | 20.5% | 100.0% | verified |
| `s12-pool-too-small-for-peak` | `DB_MAX_OVERFLOW=10` (rollback); `DB_POOL_SIZE=20` (rollback) | 78.2% | 0.1% | 89.9% | verified |
| `s13-small-pool-fails-fast` | `DB_MAX_OVERFLOW=10` (rollback); `DB_POOL_SIZE=20` (rollback); `DB_POOL_TIMEOUT_SECONDS=30` (rollback) | 98.7% | 24.8% | 99.8% | verified |
| `s14-pool-cut-bundled-with-deadline-raise` | `DB_MAX_OVERFLOW=10` (rollback); `DB_POOL_SIZE=20` (rollback) | 99.6% | 0.2% | 99.8% | verified |
| `s15-missing-index-among-three-migrations` | roll back `0004_auction_request_id_collation` | 95.8% | 0.0% | 99.7% | verified |
| `s16-missing-index-with-pool-resize` | roll back `0004_auction_request_id_collation` | 99.4% | 0.0% | 98.9% | verified |
| `s17-legacy-events-retry-storm` | `EVENT_MAX_RETRIES=0` | drift 1 | drift 1092 | drift 1 | verified |
| `s18-poison-message-after-worker-deploy` | skip the stuck message in all three groups | drift 1 | drift 880 | drift 1 | verified |
| `s19-replay-double-counts-analytics` | none proposed (code fix) | | | | not tested |
| `s20-replay-after-worker-retry-change` | none proposed (code fix) | | | | not tested |
| `s21-ambiguous-deadline-60-and-bidders-70` (experiment) | `AUCTION_GLOBAL_TIMEOUT_MS=100` (rollback) | 94.0% | 11.6% | 98.9% | verified |
| `s22-slow-bidders-after-pool-resize` | `AUCTION_GLOBAL_TIMEOUT_MS=200`; timeout 200ms on DSP-A, DSP-B, DSP-D, DSP-E | 98.6% | 0.0% | 98.6% | verified |

The missing-index experiments also exposed a second, cascading platform
fault. While the index was missing, hundreds of requests queued for a database
connection; when the rollback released them together, their DSP calls flooded
the backend's shared HTTP client, and in about one replay in three the client
never recovered. Every later DSP call timed out after 100ms without the
simulator receiving it, so auctions ended `NO_BID` until the backend restarted.
The cause was a connection-slot leak in httpcore's pool (1.0.x): when a queued
request is handed a brand-new connection at the moment its pool timeout fires,
the request gives up and the pool keeps the connection, which stays
`CONNECTING` forever. DSP calls use pool timeouts of about 100ms, so a burst
leaks slots quickly, and once all 100 are gone the client is wedged. The
backend now uses `DSPTransport` (`backend/app/services/bidding/transport.py`),
which returns orphaned slots to the pool whenever a request fails; a single
replay drops up to a few hundred of them. With it, ten replays of s05 and s15
all verified, as did the recorded runs above. This is why verification runs
the whole platform instead of checking only that the index exists.

s12's sandbox baseline was only 78% at 32 auctions/s, close to what one
backend process can serve, so its "verified" compares against a weaker
baseline than the others.

The two double-count incidents get no proposal: their fix is code (make the
rollup idempotent) plus a data rebuild, which no allowlisted change can do.

## Safety model

- **No command execution from scenarios.** A scenario can only `deploy`
  (change settings from a fixed allowlist, and run migrations chosen by name
  from fixed SQL), `dsp_config` (change allowlisted fields of the simulated
  DSPs), publish a named message template, or rewind an allowlisted consumer
  group by a bounded number of minutes. No SQL, payload or command text ever
  comes from a scenario file. There is no shell action, and the harness
  invokes Docker with fixed argument lists and no shell.
- **Read-only evidence.** Database exports are named queries run with
  `default_transaction_read_only=on`.
- **Disposable environment.** Runs use their own Compose project and wipe
  its volumes; nothing touches a long-lived database.

The investigator follows the same rules: its tools are read-only functions
over recorded files, and model output is never executed as a shell command.
Remediation runs only in a disposable copy of the platform, only after a
named approval of an unmodified proposal, and only through the typed,
allowlisted changes above.

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

Two real bugs in the worker are left in place on purpose, because the suite's
worker incidents exercise them:

- **A message that fails to decode kills the worker.** The consumers decode
  JSON in aiokafka's `value_deserializer`, which raises inside the
  `async for` loop, outside the retry and dead-letter path. The exception
  ends `asyncio.gather` and the process; on restart it reads the same
  uncommitted message and dies again. The fix is to deserialize inside the
  handler's `try` so a bad message is dead-lettered like any other failure.
- **The analytics rollup is not idempotent.** Kafka delivers at least once,
  but `handle_analytics_event` adds 1 per event without recording which
  event ids it has applied, so any redelivery is counted twice.

The harness overlay gives the worker `restart: unless-stopped`, as production
would, so the first bug shows up as a crash loop rather than a silent stop.

One backend process tops out at roughly 45 auctions/s on a 4-core machine,
CPU bound. Scenarios run at 20–30 auctions/s to stay below that.

## Roadmap

1. ~~Reproducible platform, three injected failures with ground truth.~~
2. ~~Telemetry (OpenTelemetry traces across auction, DSP fan-out and DB) and a
   fixed diagnostic baseline workflow.~~
3. ~~A tool-using investigator with structured hypotheses and evidence
   references, plus a log-only prompt baseline.~~
4. ~~Sandbox remediation experiments behind an approval gate; ambiguous
   scenarios where abstaining is the right answer.~~
5. ~~Expand to 20–30 scenarios (missing index, poison message, duplicate
   delivery, ...) and compare the investigator with both baselines on
   accuracy, abstention, time, tool calls and cost.~~ The model's own numbers
   need an API key; see [Results across the suite](#results-across-the-suite).
6. Demo, architecture write-up, and benchmark instructions.
