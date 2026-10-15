"""Offline stand-in for the model: hypothesis-driven tool choice by rule.

It speaks the same ``Model`` protocol as ``ClaudeModel`` and goes through the
same harness (budget, evidence ids, report validation), so the whole pipeline
can be exercised and graded with no API key. It is not the LLM, and its scores
say nothing about how the LLM would do.

What it does differently from the fixed workflow: it reads the symptom first
(are auctions stuck, or are bidders not answering?) and only calls the tools
that separate the causes that symptom allows, then drills into one slow trace.
It also cites evidence that cuts against the hypotheses it ranks lower.
"""
from __future__ import annotations

import json
import statistics
from typing import Any, Dict, Generator, List, Optional, Tuple

from evidenceops.agent.loop import ToolUse, Turn
from evidenceops.telemetry import parse_ts

Call = Tuple[str, Dict[str, Any]]
Results = List[Dict[str, Any]]

SETTING_EFFECTS = {
    "AUCTION_GLOBAL_TIMEOUT_MS": "config_regression",
    "DSP_DEFAULT_TIMEOUT_MS": "config_regression",
    "DB_POOL_SIZE": "db_pool_exhaustion",
    "DB_MAX_OVERFLOW": "db_pool_exhaustion",
    "DB_POOL_TIMEOUT_SECONDS": "db_pool_exhaustion",
}

# Spans that wrap a whole request; the time inside them is spent in their children.
ENCLOSING_SPANS = {"POST /api/v1/auctions", "auction"}


def _onset(buckets: List[Dict[str, Any]]) -> Optional[Tuple[str, float]]:
    if len(buckets) < 3:
        return None
    baseline = statistics.median(b["success_rate"] for b in buckets[:3])
    for a, b in zip(buckets, buckets[1:]):
        if a["success_rate"] < baseline / 2 and b["success_rate"] < baseline / 2 and a["requests"] >= 5:
            return a["window_start"], baseline
    return None


def _share(counts: Dict[str, int], key: str) -> float:
    total = sum(counts.values())
    return counts.get(key, 0) / total if total else 0.0


def _p(result: Dict[str, Any], group: str = "all", q: str = "p95") -> float:
    g = result["groups"].get(group)
    return float(g[q]) if g and g.get(q) is not None else 0.0


def policy() -> Generator[List[Call], Results, Dict[str, Any]]:
    alert = (yield [("alert_timeline", {})])[0]
    onset = _onset(alert["buckets"])
    if onset is None:
        return {
            "timeline": [], "hypotheses": [], "abstain": True,
            "abstain_reason": "the alert timeline shows no sustained drop to investigate",
        }
    onset_iso, baseline = onset
    start, end = alert["telemetry_window"]
    before, after = {"start": start, "end": onset_iso}, {"start": onset_iso, "end": end}

    deploys, auc_before, auc_after = yield [
        ("list_deployments", {}), ("auction_outcomes", before), ("auction_outcomes", after)
    ]
    ids = {"alert": alert["evidence_id"], "deploys": deploys["evidence_id"],
           "auc_before": auc_before["evidence_id"], "auc_after": auc_after["evidence_id"]}
    onset_ts = parse_ts(onset_iso)
    near = [d for d in deploys["deployments"] if d.get("from_version") and onset_ts - 60 <= parse_ts(d["started_at"]) <= onset_ts + 10]
    changed = {c["setting"]: c for d in near for c in d["config_changes"]}

    stuck = (auc_after["duration_ms"]["p50"] or 0) > 5 * max(auc_before["duration_ms"]["p50"] or 1, 1) or (
        _share(auc_after["status_counts"], "PENDING") + _share(auc_after["status_counts"], "FAILED") > 0.1
    )
    no_bids = _share(auc_after["status_counts"], "NO_BID") - _share(auc_before["status_counts"], "NO_BID") > 0.3

    scores: Dict[str, float] = {}
    support: Dict[str, List[str]] = {}
    against: Dict[str, List[str]] = {}
    why: Dict[str, List[str]] = {}
    component: Dict[str, str] = {}

    def add(cat: str, pts: float, evidence: List[str], reason: str, comp: str = "") -> None:
        scores[cat] = scores.get(cat, 0.0) + pts
        support.setdefault(cat, [])
        support[cat] += [e for e in evidence if e not in support[cat]]
        why.setdefault(cat, []).append(reason)
        if comp:
            component[cat] = comp

    def refute(cat: str, evidence: List[str]) -> None:
        against.setdefault(cat, [])
        against[cat] += [e for e in evidence if e not in against[cat]]

    deep_trace: Optional[str] = None
    if stuck:
        add("db_pool_exhaustion", 0.1, [ids["auc_after"]],
            f"auction p50 went from {auc_before['duration_ms']['p50']:.0f}ms to {auc_after['duration_ms']['p50']:.0f}ms with "
            f"{auc_after['status_counts'].get('PENDING', 0)} PENDING auctions")
        pool_before, pool_after, logs = yield [
            ("span_latency", {"name": "db.pool.acquire", **before}),
            ("span_latency", {"name": "db.pool.acquire", **after}),
            ("log_events", {"service": "backend", **after, "contains": "Error"}),
        ]
        wait_b, wait_a = _p(pool_before), _p(pool_after)
        if wait_a > max(200.0, 10 * wait_b):
            add("db_pool_exhaustion", 0.4, [pool_before["evidence_id"], pool_after["evidence_id"]],
                f"waiting for a DB connection: p95 {wait_b:.0f}ms before, {wait_a:.0f}ms after")
            deep_trace = pool_after["groups"]["all"]["slowest_trace"]
        pool_errors = [e for e in logs["events"] if "QueuePool" in e["event"]]
        if pool_errors:
            add("db_pool_exhaustion", 0.2, [logs["evidence_id"]],
                f"{pool_errors[0]['count']} '{pool_errors[0]['event'][10:70]}' errors ({pool_errors[0]['first_seen']})")
        conns = (yield [("db_connections", after)])[0]
        busy = [s["by_state"].get("active", 0) + s["by_state"].get("idle in transaction", 0) for s in conns["samples"]]
        if busy and max(busy) <= 6 and wait_a > 1000:
            add("db_pool_exhaustion", 0.1, [conns["evidence_id"]],
                f"Postgres itself is quiet (at most {max(busy)} busy connections), so the wait is in the app's pool")
            refute("missing_index", [conns["evidence_id"]])
        for setting, c in changed.items():
            if SETTING_EFFECTS.get(setting) == "db_pool_exhaustion" and "db_pool_exhaustion" in scores:
                add("db_pool_exhaustion", 0.15, [ids["deploys"]],
                    f"deploy changed {setting} {c['from']} -> {c['to']}", comp=setting)

    if no_bids:
        bids_before, bids_after, fanout = yield [
            ("bid_outcomes", before), ("bid_outcomes", after),
            ("span_latency", {"name": "dsp.fanout", **after, "group_by": "auction.global_timeout_ms"}),
        ]
        chronic = {d for d, s in bids_before["per_dsp"].items() if s["timeout_share"] >= 0.9}
        rising = {d: s for d, s in bids_after["per_dsp"].items() if d not in chronic and s["timeout_share"] - bids_before["per_dsp"].get(d, {}).get("timeout_share", 0) > 0.3}
        budgets = bids_after["dsp_timeout_ms"]
        cut_short = [d for d, s in rising.items() if (s["by_status"].get("TIMEOUT", {}).get("response_time_ms_p50") or 0) < 0.6 * budgets.get(d, 100)]
        surge = [bids_before["evidence_id"], bids_after["evidence_id"]]
        deadlines = sorted(fanout["groups"], key=lambda k: -fanout["groups"][k]["count"])
        if rising and len(cut_short) > len(rising) / 2:
            add("config_regression", 0.5, surge + [fanout["evidence_id"]],
                f"{len(rising)} DSPs went from answering to timing out, but their TIMEOUTs land at "
                f"~{statistics.median(rising[d]['by_status']['TIMEOUT']['response_time_ms_p50'] for d in cut_short):.0f}ms, "
                f"well inside their own budgets; fan-outs ran under a global deadline of {deadlines[0] if deadlines else '?'}ms")
            refute("external_dsp_latency", surge)
            deep_trace = fanout["groups"][deadlines[0]]["slowest_trace"] if deadlines else deep_trace
        elif rising:
            add("external_dsp_latency", 0.5, surge,
                f"{len(rising)} DSPs ({', '.join(sorted(rising))}) went from answering to timing out at their full "
                f"per-DSP budget, so they are slower than the budget allows")
            deep_trace = fanout["groups"][deadlines[0]]["slowest_trace"] if deadlines else deep_trace
            if not any(SETTING_EFFECTS.get(s) == "config_regression" for s in changed):
                add("external_dsp_latency", 0.2, [ids["deploys"]], "no deploy near the onset changed a timeout setting")
                refute("config_regression", [ids["deploys"]])
        for setting, c in changed.items():
            if SETTING_EFFECTS.get(setting) == "config_regression":
                add("config_regression", 0.3, [ids["deploys"]],
                    f"deploy changed {setting} {c['from']} -> {c['to']}", comp=setting)
        if "external_dsp_latency" in scores:
            component.setdefault("external_dsp_latency", ", ".join(sorted(rising)))

    if deep_trace:
        trace = (yield [("trace_detail", {"trace_id": deep_trace})])[0]
        inner = [s for s in trace["spans"] if s["name"] not in ENCLOSING_SPANS]
        top = max(inner, key=lambda s: s["duration_ms"], default=None)
        lead = max(scores, key=scores.get) if scores else None
        if top and lead:
            add(lead, 0.05, [trace["evidence_id"]],
                f"in the slowest trace, {top['name']} took {top['duration_ms']:.0f}ms of the request")

    if changed and not scores:
        add("config_regression", 0.2, [ids["deploys"]],
            f"a deploy changed {len(changed)} setting(s) near the onset, but no symptom points at them")

    ranked = sorted(scores, key=lambda c: -scores[c])
    hypotheses = [
        {
            "category": c,
            "component": component.get(c, ""),
            "statement": "; ".join(why[c]),
            "confidence": round(min(scores[c], 1.0), 2),
            "supporting": support[c],
            "refuting": against.get(c, []),
        }
        for c in ranked
    ]
    reason = ""
    if not ranked or scores[ranked[0]] < 0.5:
        reason = "no cause is supported strongly enough"
    elif len(ranked) > 1 and scores[ranked[0]] - scores[ranked[1]] < 0.15:
        reason = f"{ranked[0]} and {ranked[1]} are about equally supported"
    timeline = [
        {"at": d["started_at"], "event": f"deploy {d['from_version']} -> {d['to_version']} changes {', '.join(c['setting'] for c in d['config_changes'])}", "evidence": [ids["deploys"]]}
        for d in near
    ] + [{"at": onset_iso, "event": f"success rate drops below half of its {baseline:.0%} baseline", "evidence": [ids["alert"]]}]
    timeline.sort(key=lambda t: parse_ts(t["at"]))
    return {"timeline": timeline, "hypotheses": hypotheses, "abstain": bool(reason), "abstain_reason": reason}


class OfflinePolicy:
    """Adapts the policy generator to the ``Model`` protocol."""

    name = "offline-policy"

    def __init__(self) -> None:
        self._gen = policy()
        self._started = False
        self._turns = 0

    def respond(self, system: str, tools: List[Dict[str, Any]], messages: List[Dict[str, Any]]) -> Turn:
        self._turns += 1
        try:
            if not self._started:
                self._started = True
                calls = next(self._gen)
            else:
                calls = self._gen.send(self._last_results(messages))
        except StopIteration as done:
            return self._turn([("submit_report", done.value)])
        return self._turn(calls)

    def _turn(self, calls: List[Call]) -> Turn:
        uses = [ToolUse(f"t{self._turns}_{i}", name, args) for i, (name, args) in enumerate(calls)]
        content = [{"type": "tool_use", "id": u.id, "name": u.name, "input": u.input} for u in uses]
        return Turn(content=content, tool_uses=uses, stop_reason="tool_use", model=self.name)

    @staticmethod
    def _last_results(messages: List[Dict[str, Any]]) -> Results:
        results = []
        for block in messages[-1]["content"]:
            if block.get("is_error"):
                raise RuntimeError(f"offline policy got a tool error: {block['content']}")
            results.append(json.loads(block["content"]))
        return results
