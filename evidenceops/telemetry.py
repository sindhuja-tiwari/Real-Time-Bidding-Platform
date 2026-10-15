"""Read-only diagnostic tools over a recorded run's ``observed/`` evidence.

Every investigator (the fixed baseline now, the agent later) gets exactly
these tools and nothing else: no access to ``ground_truth/``, no shell, no
writes. Each call is recorded in an ``EvidenceStore`` and gets an id
(``E1``, ``E2``, ...) that hypotheses must cite, which is what makes an
"unsupported diagnosis" measurable.

Times are ISO-8601 strings; windows are half-open ``[start, end)``.
"""
from __future__ import annotations

import csv
import json
import re
import statistics
import time
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

LOG_SERVICES = ("backend", "worker", "dsp-simulator", "postgres", "kafka", "redis")
_LOG_LINE = re.compile(r"^(?P<svc>[\w-]+)-\d+\s+\|\s+(?P<ts>\d{4}-\d\d-\d\dT[\d:.]+Z)\s?(?P<msg>.*)$")
_ACCESS = re.compile(r'"(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[\d.]+" (?P<status>\d{3})')
_EXC = re.compile(r"^(?P<exc>[\w.]+(?:Error|Exception|Timeout))\b:?\s?(?P<detail>.*)")


def parse_ts(value: str) -> float:
    """Parse the timestamp formats found in run files into epoch seconds."""
    v = value.strip().replace(" ", "T")
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    elif re.search(r"[+-]\d\d$", v):
        v += ":00"
    # Python <3.11 only accepts 0, 3 or 6 fractional digits.
    v = re.sub(r"\.(\d{6})\d+", r".\1", v)
    return datetime.fromisoformat(v).timestamp()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds")


def _pct(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * q))], 2)


def _summary(values: List[float]) -> Dict[str, Any]:
    return {
        "count": len(values),
        "p50": _pct(values, 0.5),
        "p95": _pct(values, 0.95),
        "max": round(max(values), 2) if values else None,
    }


class RunEvidence:
    """Lazy, read-only loaders over one run's observed/ directory."""

    def __init__(self, observed_dir: Path):
        self.dir = Path(observed_dir)
        if self.dir.name != "observed":
            self.dir = self.dir / "observed"

    @cached_property
    def incident(self) -> Dict[str, Any]:
        return json.loads((self.dir / "incident.json").read_text())

    @cached_property
    def window(self) -> List[float]:
        start, end = self.incident["telemetry_window"]
        return [parse_ts(start), parse_ts(end)]

    @cached_property
    def deployments(self) -> List[Dict[str, Any]]:
        path = self.dir / "deployments.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def _csv(self, name: str, ts_field: str) -> List[Dict[str, Any]]:
        rows = []
        with open(self.dir / "db" / f"{name}.csv") as f:
            for row in csv.DictReader(f):
                row["_ts"] = parse_ts(row[ts_field])
                rows.append(row)
        return rows

    @cached_property
    def bids(self) -> List[Dict[str, Any]]:
        return self._csv("bids", "created_at")

    @cached_property
    def auctions(self) -> List[Dict[str, Any]]:
        return self._csv("auctions", "started_at")

    @cached_property
    def dsps(self) -> List[Dict[str, Any]]:
        with open(self.dir / "db" / "dsps.csv") as f:
            return list(csv.DictReader(f))

    def samples(self, name: str) -> List[Dict[str, Any]]:
        """A sampled query's rows over time: [{_ts, rows, error}], oldest first."""
        cache = self.__dict__.setdefault("_samples", {})
        if name not in cache:
            path = self.dir / "db" / f"{name}.samples.jsonl"
            out = []
            for line in (path.read_text().splitlines() if path.exists() else []):
                sample = json.loads(line)
                rows = list(csv.DictReader(sample["csv"].splitlines())) if sample.get("csv") else []
                out.append({"_ts": parse_ts(sample["sampled_at"]), "rows": rows, "error": sample.get("error")})
            cache[name] = out
        return cache[name]

    @cached_property
    def pg_samples(self) -> List[Dict[str, Any]]:
        return self.samples("pg_stat_activity")

    @cached_property
    def indexes(self) -> List[Dict[str, Any]]:
        path = self.dir / "db" / "indexes.csv"
        if not path.exists():
            return []
        with open(path) as f:
            return list(csv.DictReader(f))

    @cached_property
    def kafka_samples(self) -> List[Dict[str, Any]]:
        """Consumer-group describe output over time: [{_ts, groups: {group: {...}}}]."""
        path = self.dir / "kafka" / "consumer_groups.samples.jsonl"
        out = []
        for line in (path.read_text().splitlines() if path.exists() else []):
            sample = json.loads(line)
            out.append({"_ts": parse_ts(sample["sampled_at"]), "groups": parse_consumer_groups(sample.get("text") or "")})
        return out

    @cached_property
    def spans(self) -> List[Dict[str, Any]]:
        path = self.dir / "traces" / "spans.otlp.jsonl"
        spans: List[Dict[str, Any]] = []
        if not path.exists():
            return spans
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            for rs in json.loads(line).get("resourceSpans", []):
                for ss in rs.get("scopeSpans", []):
                    for sp in ss.get("spans", []):
                        attrs = {}
                        for a in sp.get("attributes", []):
                            value = a["value"]
                            attrs[a["key"]] = next(iter(value.values())) if value else None
                        start = int(sp["startTimeUnixNano"]) / 1e9
                        end = int(sp["endTimeUnixNano"]) / 1e9
                        spans.append(
                            {
                                "trace_id": sp["traceId"],
                                "span_id": sp["spanId"],
                                "parent_id": sp.get("parentSpanId") or None,
                                "name": sp["name"],
                                "start": start,
                                "duration_ms": (end - start) * 1000,
                                "attributes": attrs,
                                "error": (sp.get("status") or {}).get("code") == 2,
                            }
                        )
        return spans

    def log_lines(self, service: str) -> List[Dict[str, Any]]:
        if service not in LOG_SERVICES:
            raise ValueError(f"unknown service '{service}'")
        cache = self.__dict__.setdefault("_logs", {})
        if service not in cache:
            lines = []
            path = self.dir / "logs" / f"{service}.log"
            text = path.read_text() if path.exists() else ""
            for n, raw in enumerate(text.splitlines(), start=1):
                m = _LOG_LINE.match(raw)
                if m:
                    lines.append({"line": n, "_ts": parse_ts(m["ts"]), "msg": m["msg"]})
            cache[service] = lines
        return cache[service]


def classify_log(msg: str) -> str:
    """Group a log line into a stable event key for counting."""
    msg = msg.strip()
    if msg.startswith("{"):
        try:
            data = json.loads(msg)
            return f'{data.get("level", "info")}:{data.get("event", "?")}'
        except ValueError:
            pass
    access = _ACCESS.search(msg)
    if access:
        return f'http:{access["method"]} {access["path"].split("?")[0]} {access["status"]}'
    exc = _EXC.match(msg)
    if exc:
        return f'exception:{exc["exc"]}: {exc["detail"][:60]}'
    return "other"


def parse_consumer_groups(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse ``kafka-consumer-groups --describe --all-groups`` output.

    Sums offsets and lag over a group's partitions. A group whose rows show
    no consumer id has no live member: nothing is consuming it right now.
    """
    groups: Dict[str, Dict[str, Any]] = {}
    header: List[str] = []
    for raw in text.splitlines():
        cols = raw.split()
        if not cols:
            continue
        if cols[0] == "GROUP":
            header = cols
            continue
        if not header or len(cols) < len(header):
            continue
        row = dict(zip(header, cols))
        g = groups.setdefault(row["GROUP"], {"committed_offset": 0, "log_end_offset": 0, "lag": 0, "active_members": 0})
        for key, col in (("committed_offset", "CURRENT-OFFSET"), ("log_end_offset", "LOG-END-OFFSET"), ("lag", "LAG")):
            if row.get(col, "-").isdigit():
                g[key] += int(row[col])
        if row.get("CONSUMER-ID", "-") != "-":
            g["active_members"] += 1
    return groups


_SQL_LITERAL = re.compile(r"'(?:[^']|'')*'|\b\d+(?:\.\d+)?\b")


def normalize_sql(query: str) -> str:
    return re.sub(r"\s+", " ", _SQL_LITERAL.sub("?", query)).strip()


def _in(row_ts: float, start: Optional[float], end: Optional[float]) -> bool:
    return (start is None or row_ts >= start) and (end is None or row_ts < end)


# --------------------------------------------------------------------- tools


def alert_timeline(ev: RunEvidence) -> Dict[str, Any]:
    """The alert that opened the incident: success rate and latency per 10s."""
    return {
        "report": ev.incident["report"],
        "metric": ev.incident["alert"]["metric"],
        "definition": ev.incident["alert"]["definition"],
        "telemetry_window": ev.incident["telemetry_window"],
        "buckets": ev.incident["alert"]["timeline"],
    }


def list_deployments(ev: RunEvidence) -> Dict[str, Any]:
    """Every deployment in the telemetry window, with its config diff."""
    return {"deployments": ev.deployments}


def auction_outcomes(ev: RunEvidence, start: str, end: str) -> Dict[str, Any]:
    """Auction status counts and server-side duration percentiles."""
    s, e = parse_ts(start), parse_ts(end)
    rows = [a for a in ev.auctions if _in(a["_ts"], s, e)]
    statuses: Dict[str, int] = {}
    for a in rows:
        statuses[a["status"]] = statuses.get(a["status"], 0) + 1
    durations = [float(a["duration_ms"]) for a in rows if a["duration_ms"]]
    return {"window": [start, end], "auctions": len(rows), "status_counts": statuses, "duration_ms": _summary(durations)}


def bid_outcomes(ev: RunEvidence, start: str, end: str) -> Dict[str, Any]:
    """Per-DSP bid outcomes with response times, split by outcome."""
    s, e = parse_ts(start), parse_ts(end)
    per_dsp: Dict[str, Dict[str, List[float]]] = {}
    for b in ev.bids:
        if _in(b["_ts"], s, e):
            per_dsp.setdefault(b["dsp_name"], {}).setdefault(b["status"], []).append(float(b["response_time_ms"] or 0))
    out = {}
    for dsp, by_status in sorted(per_dsp.items()):
        total = sum(len(v) for v in by_status.values())
        out[dsp] = {
            "bids": total,
            "timeout_share": round(len(by_status.get("TIMEOUT", [])) / total, 3),
            "by_status": {k: {"count": len(v), "response_time_ms_p50": _pct(v, 0.5)} for k, v in sorted(by_status.items())},
        }
    timeouts = {d["name"]: int(d["timeout_ms"]) for d in ev.dsps}
    return {"window": [start, end], "per_dsp": out, "dsp_timeout_ms": timeouts}


def span_latency(ev: RunEvidence, name: str, start: str, end: str, group_by: Optional[str] = None) -> Dict[str, Any]:
    """Duration percentiles of one span name, optionally grouped by an attribute."""
    s, e = parse_ts(start), parse_ts(end)
    groups: Dict[str, List[float]] = {}
    slowest: Dict[str, tuple] = {}  # group -> (duration_ms, trace_id)
    for sp in ev.spans:
        if sp["name"] == name and _in(sp["start"], s, e):
            key = str(sp["attributes"].get(group_by)) if group_by else "all"
            groups.setdefault(key, []).append(sp["duration_ms"])
            if key not in slowest or sp["duration_ms"] > slowest[key][0]:
                slowest[key] = (sp["duration_ms"], sp["trace_id"])
    return {
        "span": name,
        "window": [start, end],
        "group_by": group_by,
        "groups": {k: {**_summary(v), "slowest_trace": slowest[k][1]} for k, v in sorted(groups.items())},
    }


def trace_detail(ev: RunEvidence, trace_id: str) -> Dict[str, Any]:
    """All spans of one trace, in start order, with their attributes."""
    spans = sorted((sp for sp in ev.spans if sp["trace_id"] == trace_id), key=lambda sp: sp["start"])
    if not spans:
        return {"trace_id": trace_id, "spans": [], "note": "trace not found"}
    t0 = spans[0]["start"]
    return {
        "trace_id": trace_id,
        "spans": [
            {
                "name": sp["name"],
                "offset_ms": round((sp["start"] - t0) * 1000, 1),
                "duration_ms": round(sp["duration_ms"], 1),
                "attributes": {k: v for k, v in sp["attributes"].items() if not k.startswith("db.statement")},
                "error": sp["error"],
            }
            for sp in spans[:60]
        ],
    }


def log_events(
    ev: RunEvidence, service: str, start: str, end: str, contains: Optional[str] = None, top: int = 12
) -> Dict[str, Any]:
    """Count log events by kind in a window, with a sample line reference for each."""
    s, e = parse_ts(start), parse_ts(end)
    counts: Dict[str, int] = {}
    samples: Dict[str, str] = {}
    for line in ev.log_lines(service):
        if not _in(line["_ts"], s, e) or (contains and contains not in line["msg"]):
            continue
        key = classify_log(line["msg"])
        counts[key] = counts.get(key, 0) + 1
        samples.setdefault(key, f'logs/{service}.log:{line["line"]}')
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:top]
    return {
        "service": service,
        "window": [start, end],
        "filter": contains,
        "events": [{"event": k, "count": c, "first_seen": samples[k]} for k, c in ranked],
    }


def db_connections(ev: RunEvidence, start: str, end: str) -> Dict[str, Any]:
    """Postgres connection states sampled every ~5s (pg_stat_activity)."""
    s, e = parse_ts(start), parse_ts(end)
    samples = []
    for sample in ev.pg_samples:
        if _in(sample["_ts"], s, e):
            states: Dict[str, int] = {}
            waits = 0
            for row in sample["rows"]:
                states[row["state"] or "unknown"] = states.get(row["state"] or "unknown", 0) + int(row["connections"])
                if row.get("wait_event_type") == "Lock":
                    waits += int(row["connections"])
            samples.append({"at": iso(sample["_ts"]), "by_state": states, "lock_waits": waits})
    totals = [sum(x["by_state"].values()) for x in samples]
    return {"window": [start, end], "samples": samples, "total_connections": _summary(totals)}


def slow_queries(ev: RunEvidence, start: str, end: str, top: int = 8) -> Dict[str, Any]:
    """Statements seen running in Postgres (sampled every ~5s), grouped by shape."""
    s, e = parse_ts(start), parse_ts(end)
    by_query: Dict[str, List[float]] = {}
    samples = 0
    for sample in ev.samples("active_queries"):
        if not _in(sample["_ts"], s, e):
            continue
        samples += 1
        for row in sample["rows"]:
            by_query.setdefault(normalize_sql(row["query"]), []).append(float(row["running_ms"] or 0))
    ranked = sorted(by_query.items(), key=lambda kv: -sum(kv[1]))[:top]
    return {
        "window": [start, end],
        "samples": samples,
        "queries": [
            {"query": q, "seen_running": len(v), "running_ms": _summary(v), "avg_concurrent": round(len(v) / max(samples, 1), 2)}
            for q, v in ranked
        ],
    }


def table_scans(ev: RunEvidence, start: str, end: str) -> Dict[str, Any]:
    """Per-table sequential vs index scans in a window (pg_stat_user_tables deltas)."""
    s, e = parse_ts(start), parse_ts(end)
    inside = [x for x in ev.samples("table_scans") if _in(x["_ts"], s, e) and x["rows"]]
    if len(inside) < 2:
        return {"window": [start, end], "tables": {}, "note": "fewer than two samples in this window"}
    first, last = inside[0], inside[-1]
    seconds = last["_ts"] - first["_ts"]
    before = {r["relname"]: r for r in first["rows"]}
    tables = {}
    for row in last["rows"]:
        prev = before.get(row["relname"])
        if not prev:
            continue
        delta = {k: int(row[k]) - int(prev[k]) for k in ("seq_scan", "seq_tup_read", "idx_scan")}
        tables[row["relname"]] = {
            **delta,
            "seq_scans_per_s": round(delta["seq_scan"] / seconds, 2),
            "rows_read_by_seq_scans_per_s": round(delta["seq_tup_read"] / seconds),
            "live_rows": int(row["n_live_tup"]),
        }
    busy = dict(sorted(tables.items(), key=lambda kv: -(kv[1]["seq_tup_read"] + kv[1]["idx_scan"])))
    return {"window": [iso(first["_ts"]), iso(last["_ts"])], "seconds": round(seconds, 1), "tables": busy}


def db_indexes(ev: RunEvidence, table: Optional[str] = None) -> Dict[str, Any]:
    """Indexes and unique constraints on the platform's tables, as of the end of the window."""
    rows = [r for r in ev.indexes if table is None or r["tablename"] == table]
    by_table: Dict[str, List[str]] = {}
    for r in rows:
        by_table.setdefault(r["tablename"], []).append(r["indexdef"])
    return {"table": table, "captured": "end of telemetry window", "indexes": by_table}


def consumer_lag(ev: RunEvidence, start: str, end: str) -> Dict[str, Any]:
    """Kafka consumer groups over time: committed offset, lag and live members (~10s samples)."""
    s, e = parse_ts(start), parse_ts(end)
    series: Dict[str, List[Dict[str, Any]]] = {}
    for sample in ev.kafka_samples:
        if _in(sample["_ts"], s, e):
            for group, g in sample["groups"].items():
                series.setdefault(group, []).append({"at": iso(sample["_ts"]), **g})
    out = {}
    for group, points in sorted(series.items()):
        first, last = points[0], points[-1]
        # The earliest sample from which the committed offset never moved
        # again while new messages kept arriving: the group is stuck there.
        stalled_since = None
        for p in reversed(points[:-1]):
            if p["committed_offset"] != last["committed_offset"]:
                break
            if last["log_end_offset"] > p["log_end_offset"]:
                stalled_since = p["at"]
        step = max(1, len(points) // 12)
        out[group] = {
            "committed_advanced_by": last["committed_offset"] - first["committed_offset"],
            # A committed offset that moves backwards means the group was rewound.
            "largest_committed_rewind": max(
                [0] + [a["committed_offset"] - b["committed_offset"] for a, b in zip(points, points[1:])]
            ),
            "log_end_advanced_by": last["log_end_offset"] - first["log_end_offset"],
            "lag_first": first["lag"],
            "lag_last": last["lag"],
            "lag_max": max(p["lag"] for p in points),
            "stalled_since": stalled_since,
            "samples_without_live_member": sum(1 for p in points if not p["active_members"]),
            "samples": len(points),
            "series": points[::step],
        }
    return {"window": [start, end], "groups": out}


def analytics_consistency(ev: RunEvidence, start: str, end: str) -> Dict[str, Any]:
    """Finished auctions vs auctions counted by the analytics rollup, sampled every ~5s."""
    s, e = parse_ts(start), parse_ts(end)
    points = []
    for sample in ev.samples("analytics_consistency"):
        if _in(sample["_ts"], s, e) and sample["rows"]:
            row = sample["rows"][0]
            finished, rolled = int(row["finished_auctions"]), int(row["rolled_up"])
            points.append({"at": iso(sample["_ts"]), "finished_auctions": finished, "rolled_up": rolled, "not_yet_counted": finished - rolled})
    step = max(1, len(points) // 15)
    gaps = [p["not_yet_counted"] for p in points]
    return {
        "window": [start, end],
        "note": "not_yet_counted below 0 means the rollup counted more auctions than finished",
        "not_yet_counted": {"first": gaps[0] if gaps else None, "last": gaps[-1] if gaps else None,
                            "min": min(gaps) if gaps else None, "max": max(gaps) if gaps else None},
        "series": points[::step],
    }


def repeated_values(ev: RunEvidence, service: str, event: str, field: str, start: str, end: str) -> Dict[str, Any]:
    """For one structured log event, how often each value of a field repeats (e.g. an id processed twice)."""
    s, e = parse_ts(start), parse_ts(end)
    counts: Dict[str, int] = {}
    first_line: Dict[str, str] = {}
    for line in ev.log_lines(service):
        if not _in(line["_ts"], s, e) or not line["msg"].lstrip().startswith("{"):
            continue
        try:
            data = json.loads(line["msg"])
        except ValueError:
            continue
        if data.get("event") != event or field not in data:
            continue
        value = str(data[field])
        counts[value] = counts.get(value, 0) + 1
        first_line.setdefault(value, f'logs/{service}.log:{line["line"]}')
    repeated = {v: c for v, c in counts.items() if c > 1}
    histogram: Dict[str, int] = {}
    for c in counts.values():
        histogram[str(c)] = histogram.get(str(c), 0) + 1
    examples = sorted(repeated.items(), key=lambda kv: -kv[1])[:5]
    return {
        "service": service, "event": event, "field": field, "window": [start, end],
        "events": sum(counts.values()), "distinct_values": len(counts), "values_seen_more_than_once": len(repeated),
        "times_seen_histogram": histogram,
        "examples": [{"value": v, "times": c, "first_seen": first_line[v]} for v, c in examples],
    }


Tool = Callable[..., Dict[str, Any]]

TOOLS: Dict[str, Dict[str, Any]] = {
    "alert_timeline": {"fn": alert_timeline, "params": {}},
    "list_deployments": {"fn": list_deployments, "params": {}},
    "auction_outcomes": {"fn": auction_outcomes, "params": {"start": "iso", "end": "iso"}},
    "bid_outcomes": {"fn": bid_outcomes, "params": {"start": "iso", "end": "iso"}},
    "span_latency": {
        "fn": span_latency,
        "params": {"name": "span name", "start": "iso", "end": "iso", "group_by": "attribute (optional)"},
    },
    "trace_detail": {"fn": trace_detail, "params": {"trace_id": "hex"}},
    "log_events": {
        "fn": log_events,
        "params": {"service": list(LOG_SERVICES), "start": "iso", "end": "iso", "contains": "substring (optional)"},
    },
    "db_connections": {"fn": db_connections, "params": {"start": "iso", "end": "iso"}},
    "slow_queries": {"fn": slow_queries, "params": {"start": "iso", "end": "iso"}},
    "table_scans": {"fn": table_scans, "params": {"start": "iso", "end": "iso"}},
    "db_indexes": {"fn": db_indexes, "params": {"table": "table name (optional)"}},
    "consumer_lag": {"fn": consumer_lag, "params": {"start": "iso", "end": "iso"}},
    "analytics_consistency": {"fn": analytics_consistency, "params": {"start": "iso", "end": "iso"}},
    "repeated_values": {
        "fn": repeated_values,
        "params": {"service": list(LOG_SERVICES), "event": "log event name", "field": "field", "start": "iso", "end": "iso"},
    },
}


class EvidenceStore:
    """Runs tools against a run and keeps every result under a citable id."""

    def __init__(self, run_evidence: RunEvidence):
        self.ev = run_evidence
        self.items: Dict[str, Dict[str, Any]] = {}
        self.tool_seconds = 0.0

    def call(self, tool: str, **args: Any) -> Dict[str, Any]:
        if tool not in TOOLS:
            raise KeyError(f"unknown tool '{tool}'")
        started = time.perf_counter()
        result = TOOLS[tool]["fn"](self.ev, **args)
        self.tool_seconds += time.perf_counter() - started
        evidence_id = f"E{len(self.items) + 1}"
        self.items[evidence_id] = {"id": evidence_id, "tool": tool, "args": args, "result": result}
        return {"evidence_id": evidence_id, **result}

    @property
    def calls(self) -> int:
        return len(self.items)
