"""Fixed diagnostic workflow: a runbook encoded as code.

It runs the same tool calls in the same order for every incident and applies
hand-written thresholds, the way an on-call runbook would:

1. Find the onset: the first 10s bucket of a sustained (2+ buckets) drop to
   under half the baseline success rate.
2. Pull deployments near the onset.
3. Compare auctions, per-DSP bids, DB pool wait (traces), backend log events,
   and Postgres connections before vs after the onset.
4. Score each root-cause category it has a rule for; abstain when the best
   score is weak or two causes score about the same.

Analytics alerts get their own short runbook: deployments, consumer lag,
worker log events, and a rule for a worker that keeps failing on messages.

It cannot adapt: it never asks a follow-up question of the data, and it has
no rules for categories outside the four it knows (no missing-index or
duplicate-delivery rule). That is the point of the comparison: does an
adaptive investigator do better than this?
"""
from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from evidenceops.investigation import Hypothesis, Report
from evidenceops.telemetry import EvidenceStore, RunEvidence, parse_ts

METHOD = "fixed_workflow"

DEGRADED_FRACTION = 0.5      # success below half of baseline counts as degraded
SUSTAINED_BUCKETS = 2        # ...for at least this many consecutive buckets
DEPLOY_LOOKBACK_S = 60       # deploys this long before onset are suspects
CHRONIC_TIMEOUT_SHARE = 0.9  # DSPs already timing out this much in the baseline are ignored
TIMEOUT_JUMP = 0.3           # rise in timeout share that counts as a DSP timeout surge
TRUNCATED_FRACTION = 0.6     # TIMEOUT bids cut well before the per-DSP budget => deadline
POOL_WAIT_FLOOR_MS = 200
POOL_WAIT_RATIO = 10
ABSTAIN_BELOW = 0.5
ABSTAIN_MARGIN = 0.1
ANALYTICS_DRIFT = 100          # rollup this far from the auction table counts as drifting


def _find_onset(buckets: List[Dict[str, Any]]) -> Optional[Tuple[str, float]]:
    if len(buckets) < 3:
        return None
    baseline = statistics.median(b["success_rate"] for b in buckets[:3])
    threshold = baseline * DEGRADED_FRACTION
    for i in range(len(buckets) - SUSTAINED_BUCKETS + 1):
        window = buckets[i : i + SUSTAINED_BUCKETS]
        if all(b["success_rate"] < threshold and b["requests"] >= 5 for b in window):
            return buckets[i]["window_start"], baseline
    return None


def _timeout_profile(bids: Dict[str, Any], chronic: set) -> Tuple[float, Optional[float]]:
    """Mean timeout share and median TIMEOUT response time over non-chronic DSPs."""
    shares, times = [], []
    for dsp, stats in bids["per_dsp"].items():
        if dsp in chronic:
            continue
        shares.append(stats["timeout_share"])
        t = stats["by_status"].get("TIMEOUT", {}).get("response_time_ms_p50")
        if t is not None:
            times.append(t)
    return (statistics.mean(shares) if shares else 0.0), (statistics.median(times) if times else None)


def _analytics(store: EvidenceStore, alert: Dict[str, Any], started: float) -> Report:
    incident_id = store.ev.incident["incident_id"]
    sign = 1 if alert["metric"] == "analytics_backlog" else -1
    onset_iso = next((b["sampled_at"] for b in alert["buckets"] if sign * b["not_yet_counted"] > ANALYTICS_DRIFT), None)
    start_iso, end_iso = alert["telemetry_window"]
    deploys = store.call("list_deployments")
    lag = store.call("consumer_lag", start=start_iso, end=end_iso)
    logs = store.call("log_events", service="worker", start=onset_iso or start_iso, end=end_iso)
    hypotheses: List[Hypothesis] = []
    if onset_iso is not None:
        onset_ts = parse_ts(onset_iso)
        suspects = [
            d for d in deploys["deployments"]
            if d.get("from_version") and onset_ts - DEPLOY_LOOKBACK_S <= parse_ts(d["started_at"]) <= onset_ts + 10
        ]
        failures = sum(
            e["count"] for e in logs["events"]
            if e["event"].startswith("exception:") or "consumer_retry" in e["event"] or "max_retries" in e["event"]
        )
        lagging = [g for g, x in lag["groups"].items() if x["lag_last"] > ANALYTICS_DRIFT]
        if failures and lagging:
            hypotheses.append(Hypothesis(
                category="poison_message", confidence=0.7,
                statement=f"{failures} worker exceptions/retries after the drift began while {', '.join(lagging)} fell behind",
                supporting=[logs["evidence_id"], lag["evidence_id"]],
            ))
        if suspects:
            hypotheses.append(Hypothesis(
                category="config_regression", confidence=0.3,
                statement=f"deploy {suspects[-1]['to_version']} landed shortly before the drift",
                supporting=[deploys["evidence_id"]],
            ))
    reason = ""
    if not hypotheses or hypotheses[0].confidence < ABSTAIN_BELOW:
        reason = "no rule matched strongly enough"
    return Report(
        method=METHOD, incident_id=incident_id, hypotheses=hypotheses, abstained=bool(reason), abstain_reason=reason,
        evidence=store.items, tool_calls=store.calls, elapsed_seconds=round(time.perf_counter() - started, 3),
    )


def investigate(run_dir: Path) -> Report:
    started = time.perf_counter()
    ev = RunEvidence(Path(run_dir) / "observed")
    store = EvidenceStore(ev)
    incident_id = ev.incident["incident_id"]

    alert = store.call("alert_timeline")
    if alert["metric"] != "auction_success_rate":
        return _analytics(store, alert, started)
    onset = _find_onset(alert["buckets"])
    if onset is None:
        return Report(
            method=METHOD, incident_id=incident_id, hypotheses=[], abstained=True,
            abstain_reason="no sustained drop in success rate found in the alert timeline",
            evidence=store.items, tool_calls=store.calls, elapsed_seconds=time.perf_counter() - started,
        )
    onset_iso, baseline_rate = onset
    onset_ts = parse_ts(onset_iso)
    start_iso, end_iso = alert["telemetry_window"]

    deploys = store.call("list_deployments")
    suspects = [
        d for d in deploys["deployments"]
        if d.get("from_version") and onset_ts - DEPLOY_LOOKBACK_S <= parse_ts(d["started_at"]) <= onset_ts + 10
    ]
    changed = {c["setting"]: c for d in suspects for c in d["config_changes"]}

    # Gathered because the runbook says to look; no rule below keys off them.
    store.call("auction_outcomes", start=start_iso, end=onset_iso)
    store.call("auction_outcomes", start=onset_iso, end=end_iso)
    bids_before = store.call("bid_outcomes", start=start_iso, end=onset_iso)
    bids_after = store.call("bid_outcomes", start=onset_iso, end=end_iso)
    pool_before = store.call("span_latency", name="db.pool.acquire", start=start_iso, end=onset_iso)
    pool_after = store.call("span_latency", name="db.pool.acquire", start=onset_iso, end=end_iso)
    logs_after = store.call("log_events", service="backend", start=onset_iso, end=end_iso)
    store.call("db_connections", start=onset_iso, end=end_iso)

    chronic = {d for d, s in bids_before["per_dsp"].items() if s["timeout_share"] >= CHRONIC_TIMEOUT_SHARE}
    share_before, _ = _timeout_profile(bids_before, chronic)
    share_after, timeout_rt_after = _timeout_profile(bids_after, chronic)
    dsp_budget = statistics.median(bids_after["dsp_timeout_ms"].values()) if bids_after["dsp_timeout_ms"] else 100

    def p95(result: Dict[str, Any]) -> float:
        group = result["groups"].get("all")
        return group["p95"] if group and group["p95"] is not None else 0.0

    pool_wait_before, pool_wait_after = p95(pool_before), p95(pool_after)
    pool_errors = sum(
        e["count"] for e in logs_after["events"] if "QueuePool" in e["event"] or "TimeoutError" in e["event"]
    )

    scores: Dict[str, float] = {}
    support: Dict[str, List[str]] = {}
    statements: Dict[str, List[str]] = {}

    def add(category: str, points: float, evidence: List[str], why: str) -> None:
        scores[category] = scores.get(category, 0.0) + points
        cited = support.setdefault(category, [])
        cited.extend(e for e in evidence if e not in cited)
        statements.setdefault(category, []).append(why)

    # --- DB pool exhaustion
    if pool_wait_after >= max(POOL_WAIT_FLOOR_MS, POOL_WAIT_RATIO * max(pool_wait_before, 1)):
        add("db_pool_exhaustion", 0.5, [pool_before["evidence_id"], pool_after["evidence_id"]],
            f"DB pool acquire p95 rose from {pool_wait_before:.0f}ms to {pool_wait_after:.0f}ms")
    if pool_errors:
        add("db_pool_exhaustion", 0.3, [logs_after["evidence_id"]],
            f"{pool_errors} pool timeout errors in backend logs after onset")
    pool_settings = [k for k in changed if k.startswith("DB_POOL") or k == "DB_MAX_OVERFLOW"]
    if pool_settings and "db_pool_exhaustion" in scores:
        add("db_pool_exhaustion", 0.2, [deploys["evidence_id"]], f"a deploy changed {', '.join(pool_settings)}")

    # --- DSP timeout surge: slow bidders, or our own deadline?
    if share_after - share_before >= TIMEOUT_JUMP:
        surge = [bids_before["evidence_id"], bids_after["evidence_id"]]
        detail = f"DSP timeout share rose from {share_before:.0%} to {share_after:.0%}"
        if timeout_rt_after is not None and timeout_rt_after < TRUNCATED_FRACTION * dsp_budget:
            add("config_regression", 0.6, surge,
                f"{detail}, but TIMEOUT bids are cut at ~{timeout_rt_after:.0f}ms, well under the {dsp_budget:.0f}ms per-DSP budget")
        else:
            add("external_dsp_latency", 0.6, surge,
                f"{detail}, with TIMEOUT bids at ~{timeout_rt_after or 0:.0f}ms, the {dsp_budget:.0f}ms per-DSP budget")
        timeout_settings = [k for k in changed if "TIMEOUT_MS" in k]
        if timeout_settings:
            add("config_regression", 0.3, [deploys["evidence_id"]], f"a deploy changed {', '.join(timeout_settings)}")

    # --- Generic runbook step: a deploy just before the drop is a suspect
    if changed:
        add("config_regression", 0.2, [deploys["evidence_id"]],
            f"deploy {suspects[-1]['to_version']} changed {len(changed)} setting(s) shortly before the drop")

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    hypotheses = [
        Hypothesis(
            category=cat,
            statement="; ".join(statements[cat]),
            confidence=round(min(score, 1.0), 2),
            supporting=support[cat],
        )
        for cat, score in ranked
    ]

    abstain_reason = ""
    if not ranked or ranked[0][1] < ABSTAIN_BELOW:
        abstain_reason = "no rule matched strongly enough"
    elif len(ranked) > 1 and ranked[0][1] - ranked[1][1] < ABSTAIN_MARGIN:
        abstain_reason = f"{ranked[0][0]} and {ranked[1][0]} score about the same"

    timeline = [{"at": d["started_at"], "event": f"deploy {d['from_version']} -> {d['to_version']}", "evidence": [deploys["evidence_id"]]} for d in deploys["deployments"] if d.get("from_version")]
    timeline.append({"at": onset_iso, "event": f"success rate falls below {baseline_rate * DEGRADED_FRACTION:.0%}", "evidence": [alert["evidence_id"]]})
    timeline.sort(key=lambda t: parse_ts(t["at"]))

    return Report(
        method=METHOD,
        incident_id=incident_id,
        hypotheses=hypotheses,
        abstained=bool(abstain_reason),
        abstain_reason=abstain_reason,
        timeline=timeline,
        evidence=store.items,
        tool_calls=store.calls,
        elapsed_seconds=round(time.perf_counter() - started, 3),
    )
