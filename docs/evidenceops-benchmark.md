# Reproducing the EvidenceOps benchmark

This is how to regenerate the tables in
[Results across the suite](../evidenceops/README.md#results-across-the-suite):
record all 22 incidents, run each investigation method on them, grade the
reports, and test the proposed fixes in sandboxes.

## What you need

- Docker with Compose v2, about 8 GB of free memory and 10 GB of disk. Each
  run rebuilds the whole platform (backend, worker, DSP simulator, Postgres,
  Redis, Kafka, OpenTelemetry collector).
- Python 3.12 or newer, and `pip install -r evidenceops/requirements.txt`.
- For the model-backed methods only, one API key exported in the terminal
  you run from (never written to a file):

  | Provider | Variable | Flag |
  |---|---|---|
  | Gemini (free tier) | `GEMINI_API_KEY` | `--provider gemini` |
  | Groq (free tier) | `GROQ_API_KEY` | `--provider groq` |
  | Claude | `ANTHROPIC_API_KEY` | default |

`fixed_workflow` and `agent_offline` need no key, so the whole pipeline can be
checked without one.

## Steps

```bash
# 1. Record every incident (about 3-4 minutes each, ~90 minutes in total).
#    A run that did not reproduce its incident is reported and should be rerun.
python -m evidenceops run --all

# 2. Investigate. Reports go to runs/<run_id>/investigations/<method>.json.
python -m evidenceops investigate --method fixed_workflow
python -m evidenceops investigate --method agent_offline
export GEMINI_API_KEY=...            # or GROQ_API_KEY / ANTHROPIC_API_KEY
python -m evidenceops investigate --method agent --provider gemini
python -m evidenceops investigate --method log_only --provider gemini

# 3. Grade every saved report against the answer keys.
python -m evidenceops evaluate --out evidenceops/results.json

# 4. Propose fixes, review them, then test the approved ones in sandboxes
#    (about 4-5 minutes per fix).
python -m evidenceops remediate --method agent_offline
python -m evidenceops remediate --method agent_offline --approve "Your Name"
python -m evidenceops evaluate --methods agent_offline
```

The same steps are available over HTTP through `python -m evidenceops serve`
(see [the API](evidenceops.md#http-api)); `POST /evaluate` returns the same
rows and summary as step 3.

## Reading the output

`evaluate` prints one line per report and a summary per method:

| Field | Meaning |
|---|---|
| `top1_accuracy`, `top3_accuracy` | the true cause is first, or in the first three, on clear incidents |
| `abstention_rate_on_clear` | the method declined to name a cause when there was a clear one |
| `correct_abstention_on_ambiguous` | the method declined on the incidents built to be ambiguous |
| `unsupported_diagnosis_rate` | a top hypothesis cited no evidence the method actually retrieved |
| `mean_tool_calls`, `mean_time_to_correct_diagnosis_s` | effort and speed |
| `mean_cost_usd` | model API cost per incident (zero for the keyless methods) |
| `remediation_verified_rate` | approved fixes that restored the platform in the sandbox |

Method names carry the provider when it is not Claude, for example
`agent_gemini` and `log_only_gemini`, so runs with different providers sit side
by side.

## Things that affect the numbers

- **Free tiers are rate limited.** Expect pauses or HTTP 429s over 22
  incidents; rerun `investigate` on the runs that failed by passing their
  directories.
- **Retired models.** If a provider has retired a default model, pass
  `--model <name>`.
- **Machine speed.** Scenarios are sized for a laptop running everything in
  Docker. s12 sits close to what one backend process can serve, so its
  baseline success rate varies more than the others.
- **`agent_offline` is an upper bound.** Its rules were written with these
  scenarios in view; it checks that the evidence is sufficient, not how well a
  model reasons.
- **Quick mode** (`--quick`) halves the traffic phases. It is useful for
  checking the pipeline but is not what the published tables use.
