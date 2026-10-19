# EvidenceOps architecture

EvidenceOps is an incident investigator for this platform whose diagnoses are
checked by experiment. It breaks a real copy of the platform in a known way,
records what an on-call engineer would see, lets an investigator work through
that evidence with read-only tools, and tests the fix it proposes, once a
person approves it, in a disposable copy of the platform. Every incident has
an answer key, so investigators can be graded and compared.

This page explains how the pieces fit together. The
[EvidenceOps README](../evidenceops/README.md) covers each part in detail and
holds the results; [evidenceops-benchmark.md](evidenceops-benchmark.md) says
how to reproduce them, and [evidenceops-demo.md](evidenceops-demo.md) walks
through one incident end to end.

## The loop

```
 scenario YAML                      recorded run (files)                     grading
 (fault + answer key)               runs/<run_id>/
      |                             |- observed/      <- investigators read only this
      v                             |   incident.json, deployments, logs,
 +-----------+   Docker Compose     |   db exports, metrics, traces
 |  runner   |-----------------+    '- ground_truth/  <- graders only
 +-----------+                 |        answer key, harness timeline,
   | open-loop traffic         |        per-request traffic, verification
   | + timed fault steps       v
   |                 +-------------------+
   '---------------->|  RTB platform     |  backend, worker, DSP simulator,
                     |  (fresh per run)  |  Postgres, Redis, Kafka, OTel
                     +-------------------+
                                                  investigation methods
 observed/ ---> 14 read-only diagnostic tools ---> fixed_workflow | agent_offline
                (evidence ids E1, E2, ...)         agent (Claude, Gemini, Groq)
                                                   log_only (no tools)
                                                         |
                                                         v
                                        report: ranked hypotheses citing evidence ids,
                                        or an abstention, plus a remediation request
                                                         |
                                                         v
                         planner: allowlisted, bounded changes only -> proposal + digest
                                                         |
                                       a person approves the exact digest
                                                         |
                                                         v
                         sandbox: rebuild the platform, replay the incident,
                         apply the fix mid-incident, measure recovery -> verdict
```

## Components

| Part | Code | What it does |
|---|---|---|
| Scenarios | `evidenceops/scenarios/*.yaml`, `scenario.py` | 22 incidents: traffic shape, timed fault steps (deploys, DSP behaviour, Kafka messages, consumer rewinds), decoys, and the answer key. Validated statically; a scenario cannot carry SQL, payloads or commands. |
| Fault actions | `faults.py` | The only ways a scenario can change the platform: settings from a fixed allowlist, migrations chosen by name from fixed SQL, allowlisted DSP simulator fields, named message templates, bounded consumer rewinds. |
| Platform control | `stack.py` | Docker Compose with fixed argument lists and no shell. Read-only database exports run with `default_transaction_read_only=on`. |
| Runner | `runner.py`, `loadgen.py` | Resets the platform, drives open-loop traffic, applies fault steps on time, then records `observed/` and `ground_truth/`. A run counts only if the incident actually reproduced. |
| Diagnostic tools | `telemetry.py` | 14 functions over the recorded files (alert timeline, deployments, auction and bid outcomes, span latency, traces, logs, DB connections, slow queries, table scans, indexes, consumer lag, analytics consistency, repeated values). Every result gets an evidence id. |
| Investigators | `baselines/fixed_workflow.py`, `agent/`, `baselines/log_only.py` | A fixed runbook; a tool-using model loop (Claude, or Gemini and Groq free tiers); a rule-based offline policy that runs the same loop without a key; and a log-only prompt with no tools. |
| Reports and grading | `investigation.py` | Reports must cite evidence ids the investigator actually saw, or they are sent back. Grading checks top-1 and top-3 against the answer key, correct abstention on ambiguous incidents, and unsupported diagnoses. |
| Remediation | `remediation.py` | Turns a diagnosis into a proposal using only allowlisted, bounded change kinds (deploy settings, DSP timeouts, rolling back a migration this run applied, skipping a stuck Kafka message). Each proposal has a digest. |
| Sandbox | `sandbox.py` | Replays the incident on a freshly built platform, applies the approved changes mid-incident, and judges recovery at steady state. |
| Shared operations | `service.py` | One implementation of list, run, investigate, propose, approve, test and evaluate, used by both front ends. |
| Front ends | `cli.py`, `api.py` | `python -m evidenceops <command>` and an HTTP API (`python -m evidenceops serve`) a web UI can drive. |

## Why the answer key is kept apart

An investigator only ever sees `observed/`, the same material an on-call
engineer would have: the incident report, the alert timeline, deployments,
logs, database exports, metrics and traces. The answer key, the harness's own
timeline and the per-request traffic live in `ground_truth/` and are read only
by the grader. The HTTP API keeps the same split: run listings and details come
from `observed/`, and the answer key is served only by the separate grading
endpoint.

## Safety model

- **Read-only diagnosis.** Every tool reads recorded files. Nothing an
  investigator does reaches a running system.
- **No model-written commands.** A model can call the 14 tools by name with
  typed arguments and can request remediation only as structured change kinds.
  The planner re-validates every change against the allowlist and bounds,
  resolves rollbacks against what the run actually deployed, and refuses
  anything else. There is no shell action anywhere.
- **A person approves the exact fix.** Approval names a person and the
  proposal's digest; if the proposal changed after review, approval fails.
  Testing is a separate step, and it runs only in a disposable copy of the
  platform, which is torn down afterwards.
- **Keys from the environment only.** Model API keys are read from
  `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` or `GROQ_API_KEY`, never from files.

## HTTP API

`python -m evidenceops serve` starts the API on `127.0.0.1:8100` (FastAPI;
interactive docs at `/docs`). It runs on the host next to Docker, because
recording a run or testing a fix rebuilds the platform with Docker Compose.
Long operations return `202` with a job to poll; jobs that use Docker run one
at a time, because they share one platform stack.

| Method and path | Purpose |
|---|---|
| `GET /health` | liveness, and whether a token is required |
| `GET /scenarios` | the scenario catalogue (no answer key) |
| `POST /runs` `{scenario_ids, quick}` | record new runs (job, needs Docker) |
| `GET /runs`, `GET /runs/{run_id}` | recorded incidents, their investigations and remediation status |
| `GET /tools`, `POST /runs/{run_id}/tools/{tool}` `{args}` | the read-only diagnostic tools, for an evidence explorer |
| `POST /runs/{run_id}/investigations` `{method, provider, model, effort, max_tool_calls}` | investigate (job) |
| `GET /runs/{run_id}/investigations/{method}` | a saved report with its evidence |
| `POST /runs/{run_id}/remediation/propose` `{method}` | turn a report into a proposal with a digest |
| `GET /runs/{run_id}/remediation/{method}` | the proposal, its approval and any sandbox result |
| `POST /runs/{run_id}/remediation/approve` `{method, approver, digest}` | a person approves the reviewed proposal |
| `POST /runs/{run_id}/remediation/test` `{method, quick}` | test an approved fix in a sandbox (job, needs Docker) |
| `GET /runs/{run_id}/grading` | the answer key and how each saved report scored |
| `POST /evaluate` `{run_ids, methods}` | suite-level comparison of methods |
| `GET /jobs`, `GET /jobs/{id}` | job status, progress and result |

Set `EVIDENCEOPS_API_TOKEN` to require `Authorization: Bearer <token>` on every
call that starts work or approves something; the server refuses to listen on a
non-loopback address without one. Browser origins allowed by CORS default to
`http://localhost:3000` and can be changed with
`EVIDENCEOPS_API_CORS_ORIGINS` (comma-separated).

The platform dashboard in `frontend/` does not have EvidenceOps screens yet;
the API is the contract they will use. A natural mapping is an incidents list
(`/runs`), an incident page with the report, the cited evidence and a "test
this fix" approval form (`/investigations`, `/tools`, `/remediation/*`), and a
results page (`/evaluate`).
