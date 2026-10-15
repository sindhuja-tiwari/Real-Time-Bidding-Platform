import json

import pytest

from evidenceops.investigation import aggregate, grade
from evidenceops.telemetry import EvidenceStore, RunEvidence, classify_log, parse_ts


@pytest.fixture
def run_dir(tmp_path):
    obs = tmp_path / "observed"
    (obs / "db").mkdir(parents=True)
    (obs / "logs").mkdir()
    (obs / "traces").mkdir()
    (obs / "incident.json").write_text(
        json.dumps(
            {
                "incident_id": "inc-test",
                "report": "r",
                "telemetry_window": ["2026-10-15T13:00:00.000+00:00", "2026-10-15T13:01:00.000+00:00"],
                "alert": {"metric": "auction_success_rate", "definition": "d", "timeline": []},
            }
        )
    )
    (obs / "deployments.jsonl").write_text("")
    (obs / "db" / "dsps.csv").write_text("id,name,endpoint,timeout_ms,status\n1,DSP-A,x,100,ACTIVE\n")
    (obs / "db" / "bids.csv").write_text(
        "id,auction_id,dsp_name,campaign_id,amount,response_time_ms,status,created_at\n"
        "1,a,DSP-A,c,2.5,25,WON,2026-10-15 13:00:10.5+00\n"
        "2,b,DSP-A,,0,15,TIMEOUT,2026-10-15 13:00:40.123456789+00\n"
        "3,c,DSP-A,,0,15,TIMEOUT,2026-10-15 13:00:41+00\n"
    )
    (obs / "logs" / "backend.log").write_text(
        'backend-1  | 2026-10-15T13:00:40.000000001Z {"event": "auction_global_timeout", "level": "warning"}\n'
        "backend-1  | 2026-10-15T13:00:41.000000001Z sqlalchemy.exc.TimeoutError: QueuePool limit of size 2 overflow 0 reached\n"
        'backend-1  | 2026-10-15T13:00:42.000000001Z INFO:     172.18.0.1:5 - "POST /api/v1/auctions HTTP/1.1" 500 Internal Server Error\n'
    )
    span = {
        "traceId": "t1", "spanId": "s1", "name": "db.pool.acquire",
        "startTimeUnixNano": str(int(parse_ts("2026-10-15T13:00:45Z") * 1e9)),
        "endTimeUnixNano": str(int((parse_ts("2026-10-15T13:00:45Z") + 1.5) * 1e9)),
        "attributes": [{"key": "db.pool.size", "value": {"intValue": "2"}}],
    }
    (obs / "traces" / "spans.otlp.jsonl").write_text(
        json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}) + "\n"
    )
    return tmp_path


def test_timestamps_in_every_run_file_format_parse():
    assert parse_ts("2026-10-15 13:00:41+00") == parse_ts("2026-10-15T13:00:41Z")
    assert parse_ts("2026-10-15T13:00:40.123456789Z") == pytest.approx(parse_ts("2026-10-15T13:00:40.123456Z"))


def test_log_lines_are_grouped_into_stable_event_kinds():
    assert classify_log('{"event": "dsp_timeout", "level": "info"}') == "info:dsp_timeout"
    assert classify_log('1.2.3.4:5 - "POST /api/v1/auctions?x=1 HTTP/1.1" 201 Created') == "http:POST /api/v1/auctions 201"
    assert classify_log("sqlalchemy.exc.TimeoutError: QueuePool limit").startswith("exception:sqlalchemy.exc.TimeoutError")


def test_tools_return_windowed_summaries_with_evidence_ids(run_dir):
    store = EvidenceStore(RunEvidence(run_dir))
    after = {"start": "2026-10-15T13:00:30Z", "end": "2026-10-15T13:01:00Z"}

    bids = store.call("bid_outcomes", **after)
    assert bids["evidence_id"] == "E1"
    assert bids["per_dsp"]["DSP-A"]["timeout_share"] == 1.0
    assert bids["per_dsp"]["DSP-A"]["by_status"]["TIMEOUT"]["response_time_ms_p50"] == 15.0
    assert bids["dsp_timeout_ms"] == {"DSP-A": 100}

    logs = store.call("log_events", service="backend", **after)
    kinds = {e["event"]: e for e in logs["events"]}
    assert kinds["warning:auction_global_timeout"]["first_seen"] == "logs/backend.log:1"
    assert any("QueuePool" in k for k in kinds)

    pool = store.call("span_latency", name="db.pool.acquire", **after)
    assert pool["groups"]["all"]["p95"] == pytest.approx(1500, abs=1)
    assert store.calls == 3 and set(store.items) == {"E1", "E2", "E3"}


def test_tools_refuse_unknown_names(run_dir):
    store = EvidenceStore(RunEvidence(run_dir))
    with pytest.raises(KeyError):
        store.call("run_shell", command="ls")
    with pytest.raises(ValueError):
        store.call("log_events", service="../../etc", start="2026-10-15T13:00:00Z", end="2026-10-15T13:01:00Z")


TRUTH = {"scenario_id": "s", "category": "db_pool_exhaustion", "ambiguous": False}


def _report(categories, supporting=("E1",), evidence=("E1",), abstained=False):
    return {
        "method": "m",
        "hypotheses": [{"category": c, "supporting": list(supporting)} for c in categories],
        "abstained": abstained,
        "evidence": {e: {} for e in evidence},
        "tool_calls": len(evidence),
        "elapsed_seconds": 2.0,
    }


def test_grading_top1_top3_and_support():
    g = grade(_report(["config_regression", "db_pool_exhaustion"]), TRUTH)
    assert not g["top1_correct"] and g["top3_correct"] and g["supported"]

    g = grade(_report(["db_pool_exhaustion"], supporting=["E9"]), TRUTH)
    assert g["top1_correct"] and g["unsupported_diagnosis"]


def test_abstaining_is_only_right_on_ambiguous_incidents():
    clear = grade(_report(["db_pool_exhaustion"], abstained=True), TRUTH)
    assert not clear["top1_correct"] and not clear["top3_correct"] and clear["correct_abstention"] is None
    ambiguous = grade(_report([], abstained=True), {**TRUTH, "ambiguous": True})
    assert ambiguous["correct_abstention"] is True

    summary = aggregate([clear, ambiguous])
    assert summary["abstention_rate_on_clear"] == 1.0
    assert summary["correct_abstention_on_ambiguous"] == 1.0
