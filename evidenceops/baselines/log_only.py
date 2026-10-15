"""Log-only prompt baseline: one Claude call, logs in, report out.

This is what "paste the logs into a chatbot" looks like. The model gets the
on-call report and the raw backend and worker logs for the telemetry window,
and no tools: no traces, no database, no deployment records. Repeated lines
are collapsed so the window fits in one request; nothing else is filtered.

Each service's log excerpt is registered as one piece of evidence (E1, E2),
so the report can be graded with the same rules as the other methods.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from evidenceops.agent import claude, spec
from evidenceops.investigation import Hypothesis, Report
from evidenceops.telemetry import RunEvidence, classify_log

METHOD = "log_only"
SERVICES = ("backend", "worker")
MAX_LINES_PER_SERVICE = 2_500

SYSTEM = """\
You are investigating a production incident on a real-time bidding platform
(FastAPI backend that runs auctions against external DSPs, Postgres, Redis,
Kafka and a worker). You are given the on-call report and raw service logs.
Rank the likely root causes using these categories: {categories}, or "other".
Cite the log excerpts you rely on by their evidence ids. Abstain, with a
reason, if the logs do not show what caused the incident.
"""


def excerpt(ev: RunEvidence, service: str, start: float, end: float) -> List[str]:
    """Window lines with runs of the same event kind collapsed into one line."""
    out: List[str] = []
    run_key, run_len = None, 0
    for line in ev.log_lines(service):
        if not start <= line["_ts"] < end:
            continue
        key = classify_log(line["msg"])
        if key == run_key and key != "other":
            run_len += 1
            continue
        if run_len > 1:
            out.append(f"    ... {run_len - 1} more lines of the same kind")
        run_key, run_len = key, 1
        out.append(f'{line["line"]}: {line["msg"].strip()[:400]}')
    if run_len > 1:
        out.append(f"    ... {run_len - 1} more lines of the same kind")
    if len(out) > MAX_LINES_PER_SERVICE:
        half = MAX_LINES_PER_SERVICE // 2
        out = out[:half] + [f"    ... {len(out) - 2 * half} lines omitted ..."] + out[-half:]
    return out


def investigate(run_dir: Path, model: str = claude.DEFAULT_MODEL, effort: str = claude.DEFAULT_EFFORT, client: Optional[Any] = None) -> Report:
    started = time.perf_counter()
    ev = RunEvidence(Path(run_dir) / "observed")
    start, end = ev.window
    evidence: Dict[str, Any] = {}
    sections = []
    for service in SERVICES:
        lines = excerpt(ev, service, start, end)
        eid = f"E{len(evidence) + 1}"
        evidence[eid] = {"id": eid, "tool": "raw_logs", "args": {"service": service}, "result": {"lines": len(lines)}}
        sections.append(f"<logs evidence_id=\"{eid}\" service=\"{service}\">\n" + "\n".join(lines) + "\n</logs>")

    prompt = f"On-call report:\n{ev.incident['report'].strip()}\n\n" + "\n\n".join(sections)
    client = client or claude.make_client()
    response = claude.create(
        client,
        system=SYSTEM.format(categories=", ".join(spec.CATEGORIES)),
        messages=[{"role": "user", "content": prompt}],
        **{**claude.request_options(model, effort), "output_config": {
            "effort": effort, "format": {"type": "json_schema", "schema": spec.REPORT_SCHEMA},
        }},
    )
    usage = claude.usage_dict(response.usage)
    served = getattr(response, "model", None) or model
    common = dict(
        method=METHOD,
        incident_id=ev.incident["incident_id"],
        evidence=evidence,
        tool_calls=0,
        elapsed_seconds=round(time.perf_counter() - started, 3),
        cost_usd=round(claude.cost_of(served, usage), 6),
        input_tokens=usage["input_tokens"] + usage["cache_read_input_tokens"] + usage["cache_creation_input_tokens"],
        output_tokens=usage["output_tokens"],
        meta={"model": model, "served_by": [served], "usage": usage},
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        return Report(hypotheses=[], abstained=True, abstain_reason=f"harness: stop_reason {response.stop_reason}", **common)
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    problems = spec.validate_report(data, set(evidence))
    hypotheses = [
        Hypothesis(
            category=h["category"], statement=h["statement"], confidence=float(h["confidence"]),
            supporting=list(h["supporting"]), refuting=list(h["refuting"]), component=h["component"],
        )
        for h in data["hypotheses"]
    ]
    common["meta"]["validation_problems"] = problems
    return Report(
        hypotheses=hypotheses,
        abstained=bool(data["abstain"]),
        abstain_reason=data["abstain_reason"],
        timeline=data["timeline"],
        **common,
    )
