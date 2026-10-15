"""What the investigator is told: system prompt, tool schemas, report schema.

Everything here is static so the request prefix stays byte-identical across
turns and runs, which keeps it cacheable.
"""
from __future__ import annotations

from typing import Any, Dict, List

from evidenceops.scenario import ROOT_CAUSE_CATEGORIES
from evidenceops.telemetry import LOG_SERVICES

CATEGORIES = list(ROOT_CAUSE_CATEGORIES)

SYSTEM_PROMPT = f"""\
You are investigating a production incident on a real-time bidding platform.
The platform is a FastAPI backend that runs auctions: for each request it loads
the ad slot and campaigns from Postgres (via a SQLAlchemy connection pool), fans
out bid requests to external DSPs in parallel under a global deadline, picks a
winner, reserves campaign budget, and publishes events to Kafka for a worker.
A request succeeds when the auction COMPLETES within the client's 2s timeout.

You can only read recorded telemetry for the incident window, through the tools
provided. Every tool result carries an `evidence_id` (E1, E2, ...). Nothing you
say counts unless it cites evidence ids you actually received.

How to work:
- Start from the alert, find when the drop began, and build a timeline.
- Keep several candidate causes open. Before you settle on one, call a tool
  whose answer would differ between your top candidates, and say which
  candidates it rules out.
- A change that lands near the onset is a suspect, not a conclusion: check that
  the changed setting could produce the symptom you see. Deploys often change
  harmless settings too.
- Compare before vs after the onset, not just after.
- Be economical: stop gathering once the leading cause is clearly separated
  from the alternatives.

Finish by calling `submit_report` exactly once. Rank hypotheses most likely
first, using these categories: {", ".join(CATEGORIES)}, or "other" when none
fits. Each hypothesis cites the evidence ids that support it, and optionally
those that cut against it. Set `abstain` to true, with a reason, when the
evidence does not separate the leading causes or does not show a cause at all;
an honest abstention is better than a confident wrong answer.
"""

_WINDOW = {
    "start": {"type": "string", "description": "ISO-8601 timestamp, inclusive"},
    "end": {"type": "string", "description": "ISO-8601 timestamp, exclusive"},
}


def _tool(name: str, description: str, properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TELEMETRY_TOOLS: List[Dict[str, Any]] = [
    _tool(
        "alert_timeline",
        "The alert that opened the incident: the on-call report text, the telemetry window, and auction "
        "success rate plus latency per 10s bucket. Call this first.",
        {},
        [],
    ),
    _tool(
        "list_deployments",
        "Every deployment in the telemetry window with start/finish time, version, services and the "
        "config settings it changed (from -> to).",
        {},
        [],
    ),
    _tool(
        "auction_outcomes",
        "Auction status counts (COMPLETED, NO_BID, FAILED, PENDING) and server-side auction duration "
        "percentiles for a time window.",
        dict(_WINDOW),
        ["start", "end"],
    ),
    _tool(
        "bid_outcomes",
        "Per-DSP bid outcomes in a window: count, share that TIMED OUT, and p50 response time per "
        "outcome (WON, LOST, INVALID, TIMEOUT, ERROR). Also returns each DSP's configured per-DSP "
        "timeout. A TIMEOUT recorded well below the per-DSP timeout means the call was cut short by "
        "the global auction deadline, not by the DSP's own budget.",
        dict(_WINDOW),
        ["start", "end"],
    ),
    _tool(
        "span_latency",
        "Duration percentiles (ms) for one trace span name in a window, optionally grouped by a span "
        "attribute, with the slowest trace id per group. Span names: `auction` (attrs auction.status, "
        "auction.winning_dsp), `db.pool.acquire` (wait to check out a DB connection; attrs "
        "db.pool.size, db.pool.checked_out_before), `dsp.fanout` (attrs auction.global_timeout_ms, "
        "dsp.deadline_hit, dsp.timeouts), `dsp.bid` (attrs dsp.name, dsp.timeout_ms, dsp.outcome), "
        "and `POST /api/v1/auctions` (the HTTP request).",
        {
            "name": {"type": "string", "description": "span name"},
            **_WINDOW,
            "group_by": {"type": "string", "description": "optional span attribute to group by"},
        },
        ["name", "start", "end"],
    ),
    _tool(
        "trace_detail",
        "All spans of one trace in start order with offsets, durations and attributes. Use it on a "
        "slowest_trace from span_latency to see where the time went in one request.",
        {"trace_id": {"type": "string"}},
        ["trace_id"],
    ),
    _tool(
        "log_events",
        "Counts log events by kind for one service in a window (structured events, HTTP access lines "
        "by status, exceptions), with a file:line reference for the first of each kind. `contains` "
        "filters to lines with that substring.",
        {
            "service": {"type": "string", "enum": list(LOG_SERVICES)},
            **_WINDOW,
            "contains": {"type": "string", "description": "optional substring filter"},
        },
        ["service", "start", "end"],
    ),
    _tool(
        "db_connections",
        "Postgres connections by state (active, idle, idle in transaction) and lock waits, sampled "
        "about every 5s from pg_stat_activity.",
        dict(_WINDOW),
        ["start", "end"],
    ),
]

_EVIDENCE_IDS = {"type": "array", "items": {"type": "string"}, "description": "evidence ids such as E3"}

REPORT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "at": {"type": "string", "description": "ISO-8601 timestamp"},
                    "event": {"type": "string"},
                    "evidence": _EVIDENCE_IDS,
                },
                "required": ["at", "event", "evidence"],
                "additionalProperties": False,
            },
        },
        "hypotheses": {
            "type": "array",
            "description": "ranked, most likely first",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": CATEGORIES + ["other"]},
                    "component": {"type": "string", "description": "the setting, service or dependency at fault"},
                    "statement": {"type": "string", "description": "the causal claim, with the numbers that back it"},
                    "confidence": {"type": "number", "description": "0 to 1"},
                    "supporting": _EVIDENCE_IDS,
                    "refuting": _EVIDENCE_IDS,
                },
                "required": ["category", "component", "statement", "confidence", "supporting", "refuting"],
                "additionalProperties": False,
            },
        },
        "abstain": {"type": "boolean"},
        "abstain_reason": {"type": "string", "description": "empty unless abstaining"},
    },
    "required": ["timeline", "hypotheses", "abstain", "abstain_reason"],
    "additionalProperties": False,
}

SUBMIT_TOOL = {
    "name": "submit_report",
    "description": "Submit the final investigation report. Call once, after gathering evidence. Every "
    "evidence id cited must come from a tool result you received.",
    "input_schema": REPORT_SCHEMA,
}

TOOLS: List[Dict[str, Any]] = TELEMETRY_TOOLS + [SUBMIT_TOOL]


def validate_report(report: Dict[str, Any], known_ids: set) -> List[str]:
    """Problems that make a submitted report unacceptable; empty when it is fine."""
    problems: List[str] = []
    hyps = report.get("hypotheses") or []
    abstain = bool(report.get("abstain"))
    if not hyps and not abstain:
        problems.append("no hypotheses: rank at least one cause, or abstain with a reason")
    if abstain and not (report.get("abstain_reason") or "").strip():
        problems.append("abstain is true but abstain_reason is empty")
    for i, h in enumerate(hyps, 1):
        if h.get("category") not in CATEGORIES + ["other"]:
            problems.append(f"hypothesis {i}: unknown category {h.get('category')!r}")
        conf = h.get("confidence")
        if not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
            problems.append(f"hypothesis {i}: confidence must be a number from 0 to 1")
        if not h.get("supporting"):
            problems.append(f"hypothesis {i}: cites no supporting evidence")
        unknown = [e for e in (h.get("supporting") or []) + (h.get("refuting") or []) if e not in known_ids]
        if unknown:
            problems.append(f"hypothesis {i}: cites evidence ids you never received: {unknown}")
    for i, t in enumerate(report.get("timeline") or [], 1):
        unknown = [e for e in t.get("evidence") or [] if e not in known_ids]
        if unknown:
            problems.append(f"timeline entry {i}: cites evidence ids you never received: {unknown}")
    return problems
