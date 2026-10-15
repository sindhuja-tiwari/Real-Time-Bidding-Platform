"""Offline stand-in for the model: hypothesis-driven tool choice by rule.

It speaks the same ``Model`` protocol as ``ClaudeModel`` and goes through the
same harness (budget, evidence ids, report validation), so the whole pipeline
can be exercised and graded with no API key. It is not the LLM, and its scores
say nothing about how the LLM would do.

What it does differently from the fixed workflow: it reads the symptom first
(are auctions stuck, are bidders not answering, are requests being turned
away, or is analytics falling behind or overcounting?) and only calls the
tools that separate the causes that symptom allows, then drills into one slow
trace. It also cites evidence that cuts against the hypotheses it ranks lower.
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
    "RATE_LIMIT_PUBLISHER_PER_MIN": "config_regression",
}

# Settings that change how the worker handles a failing message.
WORKER_SETTINGS = {"EVENT_MAX_RETRIES", "EVENT_RETRY_BASE_SECONDS"}

# Postgres busier than this many connections is doing real work, not idling
# behind a starved application pool.
BUSY_DB_CONNECTIONS = 6

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


def _timeout_p50(stats: Dict[str, Any]) -> float:
    return float(stats["by_status"].get("TIMEOUT", {}).get("response_time_ms_p50") or 0)


def _answer_p50(stats: Optional[Dict[str, Any]]) -> Optional[float]:
    """Median response time of a DSP's answered (non-timeout) bids."""
    if not stats:
        return None
    times = [v["response_time_ms_p50"] for k, v in stats["by_status"].items() if k != "TIMEOUT" and v.get("response_time_ms_p50") is not None]
    return statistics.median(times) if times else None


def _share(counts: Dict[str, int], key: str) -> float:
    total = sum(counts.values())
    return counts.get(key, 0) / total if total else 0.0


def _p(result: Dict[str, Any], group: str = "all", q: str = "p95") -> float:
    g = result["groups"].get(group)
    return float(g[q]) if g and g.get(q) is not None else 0.0


class Scorer:
    """Accumulates points, reasons and evidence per root-cause category."""

    def __init__(self) -> None:
        self.scores: Dict[str, float] = {}
        self.support: Dict[str, List[str]] = {}
        self.against: Dict[str, List[str]] = {}
        self.why: Dict[str, List[str]] = {}
        self.component: Dict[str, str] = {}

    def add(self, cat: str, pts: float, evidence: List[str], reason: str, comp: str = "") -> None:
        self.scores[cat] = self.scores.get(cat, 0.0) + pts
        self.support.setdefault(cat, [])
        self.support[cat] += [e for e in evidence if e not in self.support[cat]]
        self.why.setdefault(cat, []).append(reason)
        if comp:
            self.component[cat] = comp

    def refute(self, cat: str, evidence: List[str], pts: float = 0.0, reason: str = "") -> None:
        self.against.setdefault(cat, [])
        self.against[cat] += [e for e in evidence if e not in self.against[cat]]
        if pts and cat in self.scores:
            self.scores[cat] -= pts
            self.why[cat].append(f"but {reason}")

    def report(self, timeline: List[Dict[str, Any]], forced_reason: str = "") -> Dict[str, Any]:
        ranked = sorted(self.scores, key=lambda c: -self.scores[c])
        hypotheses = [
            {
                "category": c,
                "component": self.component.get(c, ""),
                "statement": "; ".join(self.why[c]),
                "confidence": round(max(0.0, min(self.scores[c], 1.0)), 2),
                "supporting": self.support[c],
                "refuting": self.against.get(c, []),
            }
            for c in ranked
        ]
        reason = forced_reason
        if not reason and (not ranked or self.scores[ranked[0]] < 0.5):
            reason = "no cause is supported strongly enough"
        elif not reason and len(ranked) > 1 and self.scores[ranked[0]] - self.scores[ranked[1]] < 0.15:
            reason = f"{ranked[0]} and {ranked[1]} are about equally supported"
        timeline.sort(key=lambda t: parse_ts(t["at"]))
        return {"timeline": timeline, "hypotheses": hypotheses, "abstain": bool(reason), "abstain_reason": reason}


def _deploy_event(d: Dict[str, Any], evidence: str) -> Dict[str, Any]:
    parts = [c["setting"] for c in d["config_changes"]] + [f"migration {m}" for m in d.get("migrations") or []]
    return {"at": d["started_at"], "event": f"deploy {d['from_version']} -> {d['to_version']} changes {', '.join(parts)}", "evidence": [evidence]}


def _near(deploys: Dict[str, Any], onset_ts: float, before: float = 60, after: float = 10) -> List[Dict[str, Any]]:
    return [d for d in deploys["deployments"] if d.get("from_version") and onset_ts - before <= parse_ts(d["started_at"]) <= onset_ts + after]


def _analytics_onset(points: List[Dict[str, Any]], sign: int) -> Optional[str]:
    """When the rollup started drifting from the auction table in the alert's direction."""
    if len(points) < 4:
        return None
    base = statistics.median(sign * p["not_yet_counted"] for p in points[:3])
    threshold = max(50.0, 3 * abs(base) + 20)
    for i, (a, b) in enumerate(zip(points, points[1:])):
        if sign * a["not_yet_counted"] - base > threshold and sign * b["not_yet_counted"] - base > threshold:
            return points[max(i - 1, 0)]["sampled_at"]
    return None


def _count(events: Dict[str, Any], needle: str) -> int:
    return sum(e["count"] for e in events["events"] if needle in e["event"])


def _first(events: Dict[str, Any], needle: str) -> str:
    return next((e["first_seen"] for e in events["events"] if needle in e["event"]), "")


def analytics_policy(alert: Dict[str, Any]) -> Generator[List[Call], Results, Dict[str, Any]]:
    sign = 1 if alert["metric"] == "analytics_backlog" else -1
    onset_iso = _analytics_onset(alert["buckets"], sign)
    if onset_iso is None:
        return {
            "timeline": [], "hypotheses": [], "abstain": True,
            "abstain_reason": "the analytics rollup never drifted far from the auction table",
        }
    start, end = alert["telemetry_window"]
    whole, after = {"start": start, "end": end}, {"start": onset_iso, "end": end}
    deploys, lag, worker = yield [
        ("list_deployments", {}), ("consumer_lag", whole), ("log_events", {"service": "worker", **after}),
    ]
    near = _near(deploys, parse_ts(onset_iso), before=90)
    changed = {c["setting"]: c for d in near for c in d["config_changes"]}
    sc = Scorer()
    worst = max(lag["groups"].items(), key=lambda kv: kv[1]["lag_max"], default=(None, None))
    timeline = [_deploy_event(d, deploys["evidence_id"]) for d in near] + [
        {"at": onset_iso, "event": "analytics rollup starts drifting from the auction table", "evidence": [alert["evidence_id"]]}
    ]

    if sign > 0:
        stuck = {g: x for g, x in lag["groups"].items() if x["lag_last"] > 50 and x["stalled_since"]}
        slow = {g: x for g, x in lag["groups"].items() if x["lag_last"] > 50 and g not in stuck}
        restarts = _count(worker, "worker_starting")
        decode = _count(worker, "Decode") + _count(worker, "Deserializ")
        retries = _count(worker, "consumer_retry")
        dead = _count(worker, "consumer_max_retries_exceeded")
        if stuck:
            sc.add("poison_message", 0.2, [lag["evidence_id"]],
                   f"{len(stuck)} consumer group(s) ({', '.join(sorted(stuck))}) stopped committing while the topic kept growing "
                   f"(stuck since {min(x['stalled_since'] for x in stuck.values())}, lag up to {max(x['lag_max'] for x in stuck.values())})")
        elif slow:
            sc.add("poison_message", 0.1, [lag["evidence_id"]],
                   f"{', '.join(sorted(slow))} kept committing but fell behind (lag up to {max(x['lag_max'] for x in slow.values())})")
        if restarts >= 3 or decode:
            sc.add("poison_message", 0.5, [worker["evidence_id"]],
                   f"the worker restarted {restarts} times with {decode} decode errors ({_first(worker, 'Decode') or _first(worker, 'worker_starting')}): "
                   f"a message it cannot deserialize kills it, and it reads the same message again after each restart",
                   comp="worker consumers crash-looping on an undecodable auction-events message")
        elif retries:
            sc.add("poison_message", 0.5, [worker["evidence_id"]],
                   f"{retries} consumer retries and {dead} dead-lettered messages ({_first(worker, 'consumer_retry')}): "
                   f"messages the handlers reject are each retried with backoff, stalling the consumers",
                   comp="worker consumers retrying messages their handlers reject")
        for setting, c in changed.items():
            if setting in WORKER_SETTINGS:
                sc.add("config_regression", 0.3, [deploys["evidence_id"]],
                       f"deploy changed {setting} {c['from']} -> {c['to']}, which governs how long a failing message holds a consumer",
                       comp=setting)
        if near and "poison_message" in sc.scores and not any(s in WORKER_SETTINGS for s in changed):
            sc.add("config_regression", 0.15, [deploys["evidence_id"]],
                   "a deploy restarted the worker shortly before the drift began")
            sc.refute("config_regression", [worker["evidence_id"]], 0.0)
        if "poison_message" in sc.scores:
            timeline.append({"at": onset_iso, "event": "worker consumers stop advancing", "evidence": [lag["evidence_id"], worker["evidence_id"]]})
    else:
        rewound = {g: x for g, x in lag["groups"].items() if x["largest_committed_rewind"] > 0}
        dups = (yield [("repeated_values", {"service": "worker", "event": "analytics_rollup_updated", "field": "auction_id", **whole})])[0]
        if rewound:
            sc.add("duplicate_delivery_idempotency", 0.3, [lag["evidence_id"]],
                   f"{', '.join(sorted(rewound))} had its committed offset moved back by "
                   f"{max(x['largest_committed_rewind'] for x in rewound.values())} messages, so those events were delivered again")
        if dups["values_seen_more_than_once"]:
            sc.add("duplicate_delivery_idempotency", 0.5, [dups["evidence_id"]],
                   f"{dups['values_seen_more_than_once']} auctions were added to the rollup more than once "
                   f"(e.g. {dups['examples'][0]['value']} x{dups['examples'][0]['times']}, {dups['examples'][0]['first_seen']}): "
                   f"the analytics UPSERT increments counters without remembering which events it has seen",
                   comp="analytics consumer rollup UPSERT is not idempotent")
        for setting, c in changed.items():
            sc.add("config_regression", 0.15, [deploys["evidence_id"]], f"deploy changed {setting} {c['from']} -> {c['to']} near the drift")
        if "duplicate_delivery_idempotency" in sc.scores and changed:
            sc.refute("config_regression", [dups["evidence_id"]])
    return sc.report(timeline)


def policy() -> Generator[List[Call], Results, Dict[str, Any]]:
    alert = (yield [("alert_timeline", {})])[0]
    if alert["metric"] != "auction_success_rate":
        return (yield from analytics_policy(alert))
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
    near = _near(deploys, onset_ts)
    changed = {c["setting"]: c for d in near for c in d["config_changes"]}
    migrated = [m for d in near for m in d.get("migrations") or []]

    stuck = (auc_after["duration_ms"]["p50"] or 0) > 5 * max(auc_before["duration_ms"]["p50"] or 1, 1) or (
        _share(auc_after["status_counts"], "PENDING") + _share(auc_after["status_counts"], "FAILED") > 0.1
    )
    no_bids = _share(auc_after["status_counts"], "NO_BID") - _share(auc_before["status_counts"], "NO_BID") > 0.3
    seconds_before = parse_ts(onset_iso) - parse_ts(start)
    seconds_after = parse_ts(end) - parse_ts(onset_iso)
    rate_before = auc_before["auctions"] / max(seconds_before, 1)
    rate_after = auc_after["auctions"] / max(seconds_after, 1)
    turned_away = not stuck and not no_bids and rate_after < 0.6 * rate_before

    sc = Scorer()
    add, refute, scores, component = sc.add, sc.refute, sc.scores, sc.component

    deep_trace: Optional[str] = None
    censored_conflict = False
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
        if busy and max(busy) <= BUSY_DB_CONNECTIONS and wait_a > 1000:
            add("db_pool_exhaustion", 0.1, [conns["evidence_id"]],
                f"Postgres itself is quiet (at most {max(busy)} busy connections), so the wait is in the app's pool")
            refute("missing_index", [conns["evidence_id"]])
        elif busy and max(busy) > BUSY_DB_CONNECTIONS:
            # Postgres is busy: find out with what before blaming the pool.
            queries, scans_before, scans_after = yield [
                ("slow_queries", after), ("table_scans", before), ("table_scans", after),
            ]
            slow = queries["queries"][0] if queries["queries"] else None
            hot = None
            for table, t in scans_after["tables"].items():
                was = scans_before["tables"].get(table, {}).get("rows_read_by_seq_scans_per_s", 0)
                if t["rows_read_by_seq_scans_per_s"] > max(100_000, 20 * was) and t["live_rows"] > 100_000:
                    hot = (table, t, was)
                    break
            if slow and (slow["running_ms"]["p50"] or 0) > 200:
                add("missing_index", 0.2, [queries["evidence_id"], conns["evidence_id"]],
                    f"Postgres has up to {max(busy)} busy connections, most running `{slow['query'][:90]}...` "
                    f"for a median {slow['running_ms']['p50']:.0f}ms")
            if hot:
                table, t, was = hot
                add("missing_index", 0.5, [scans_before["evidence_id"], scans_after["evidence_id"]],
                    f"sequential scans on {table} ({t['live_rows']:,} rows) now read {t['rows_read_by_seq_scans_per_s']:,} rows/s, "
                    f"up from {was:,}: a query that used an index is scanning the table", comp=f"{table} index")
                idx = (yield [("db_indexes", {"table": table})])[0]
                add("missing_index", 0.05, [idx["evidence_id"]],
                    f"{table} now has {len(idx['indexes'].get(table, []))} index(es): {'; '.join(idx['indexes'].get(table, []))[:200]}")
                for m in migrated:
                    add("missing_index", 0.2, [ids["deploys"]], f"the deploy just before the onset ran migration {m}",
                        comp=f"{table} index lost in migration {m}")
                refute("db_pool_exhaustion", [scans_after["evidence_id"], conns["evidence_id"]], 0.4,
                       "connections are held by slow scans, so the pool wait is a consequence")
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
        surge = [bids_before["evidence_id"], bids_after["evidence_id"]]
        deadlines = sorted(fanout["groups"], key=lambda k: -fanout["groups"][k]["count"])
        deadline = float(deadlines[0]) if deadlines and deadlines[0] not in ("None", "") else None
        # A TIMEOUT that lands at the global deadline, below the DSP's own
        # budget, was cut by the deadline: the DSP's real latency is unknown.
        censored = [
            d for d, st in rising.items()
            if deadline and deadline < budgets.get(d, 100) and abs(_timeout_p50(st) - deadline) <= 0.15 * deadline
        ]
        # ...but a DSP that used to answer well inside that deadline and now
        # hits it did get slower.
        slowed = [
            d for d in censored
            if (_answer_p50(bids_before["per_dsp"].get(d)) or deadline) < 0.7 * deadline
        ]
        if rising and len(censored) > len(rising) / 2:
            add("config_regression", 0.5, surge + [fanout["evidence_id"]],
                f"{len(rising)} DSPs went from answering to timing out, and their TIMEOUTs land at "
                f"~{statistics.median(_timeout_p50(rising[d]) for d in censored):.0f}ms: the global deadline of "
                f"{deadline:.0f}ms, below their own budgets, so the deadline is cutting the calls")
            deep_trace = fanout["groups"][deadlines[0]]["slowest_trace"]
            if slowed:
                add("external_dsp_latency", 0.45, surge,
                    f"{', '.join(slowed)} answered in ~{statistics.median(_answer_p50(bids_before['per_dsp'][d]) for d in slowed):.0f}ms "
                    f"before and now never finish inside {deadline:.0f}ms, so they slowed down too; how slow is hidden by the cut",
                    comp=", ".join(slowed))
                censored_conflict = True
            else:
                refute("external_dsp_latency", surge)
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

    if turned_away:
        logs = (yield [("log_events", {"service": "backend", **after})])[0]
        rejected = sum(e["count"] for e in logs["events"] if e["event"].startswith("http:") and e["event"].endswith(" 429"))
        add("config_regression", 0.1, [ids["auc_before"], ids["auc_after"]],
            f"auctions created per second fell from {rate_before:.1f} to {rate_after:.1f} while those that ran look normal")
        if rejected:
            add("config_regression", 0.3, [logs["evidence_id"]],
                f"{rejected} requests were answered 429 Too Many Requests ({_first(logs, ' 429')})")
            refute("external_dsp_latency", [ids["auc_after"]])
            refute("db_pool_exhaustion", [ids["auc_after"]])
        for setting, c in changed.items():
            if setting.startswith("RATE_LIMIT_PUBLISHER") and rejected:
                add("config_regression", 0.3, [ids["deploys"]], f"deploy changed {setting} {c['from']} -> {c['to']}", comp=setting)

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

    reason = ""
    if censored_conflict:
        reason = ("the deadline cut hides how slow the bidders now are, so the evidence cannot say whether the "
                  "deploy's shorter deadline or the slower bidders would break auctions on their own")
    timeline = [_deploy_event(d, ids["deploys"]) for d in near] + [
        {"at": onset_iso, "event": f"success rate drops below half of its {baseline:.0%} baseline", "evidence": [ids["alert"]]}
    ]
    return sc.report(timeline, reason)


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
