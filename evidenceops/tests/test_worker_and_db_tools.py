"""Tools and rules for the database and worker incidents (milestone 5)."""
import json

import pytest

from evidenceops import remediation
from evidenceops.agent.loop import investigate
from evidenceops.agent.offline import OfflinePolicy
from evidenceops.telemetry import (
    RunEvidence,
    consumer_lag,
    normalize_sql,
    parse_consumer_groups,
    repeated_values,
    slow_queries,
    table_scans,
)

W = {"start": "2026-10-15T13:00:00Z", "end": "2026-10-15T13:01:00Z"}

DESCRIBE = """
Consumer group 'analytics-consumer' has no active members.

GROUP              TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID     HOST            CLIENT-ID
analytics-consumer auction-events  0          {committed}     {end}           {lag}           -               -               -
GROUP           TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID      HOST            CLIENT-ID
audit-consumer  auction-events  0          {end}           {end}           0               aiokafka-1       /172.18.0.8     aiokafka-0.11.0
"""


def _kafka(obs, offsets):
    (obs / "kafka").mkdir(exist_ok=True)
    lines = []
    for i, (committed, end) in enumerate(offsets):
        text = DESCRIBE.format(committed=committed, end=end, lag=end - committed)
        lines.append(json.dumps({"sampled_at": f"2026-10-15T13:00:{10 * i:02d}.000+00:00", "text": text}))
    (obs / "kafka" / "consumer_groups.samples.jsonl").write_text("\n".join(lines) + "\n")


def _samples(obs, name, rows_by_second):
    lines = []
    for second, csv_text in rows_by_second:
        lines.append(json.dumps({"sampled_at": f"2026-10-15T13:00:{second:02d}.000+00:00", "csv": csv_text}))
    (obs / "db" / f"{name}.samples.jsonl").write_text("\n".join(lines) + "\n")


def test_parse_consumer_groups_sums_partitions_and_spots_dead_groups():
    groups = parse_consumer_groups(DESCRIBE.format(committed=5, end=9, lag=4))
    assert groups["analytics-consumer"] == {"committed_offset": 5, "log_end_offset": 9, "lag": 4, "active_members": 0}
    assert groups["audit-consumer"]["active_members"] == 1


def test_normalize_sql_strips_literals():
    assert normalize_sql("SELECT *  FROM auction\n WHERE request_id = 'r-1' LIMIT 1") == "SELECT * FROM auction WHERE request_id = ? LIMIT ?"


def test_consumer_lag_finds_where_a_group_stalled_and_rewinds(run_dir):
    obs = run_dir / "observed"
    _kafka(obs, [(10, 10), (20, 20), (20, 30), (20, 40)])
    lag = consumer_lag(RunEvidence(obs), **W)["groups"]["analytics-consumer"]
    assert lag["stalled_since"] == "2026-10-15T13:00:10.000+00:00"
    assert lag["lag_last"] == 20 and lag["samples_without_live_member"] == 4
    _kafka(obs, [(100, 100), (40, 110), (120, 120)])
    lag = consumer_lag(RunEvidence(obs), **W)["groups"]["analytics-consumer"]
    assert lag["largest_committed_rewind"] == 60 and lag["stalled_since"] is None


def test_slow_queries_and_table_scans(run_dir):
    obs = run_dir / "observed"
    _samples(obs, "active_queries", [
        (5, "running_ms,query\n900,SELECT a FROM auction WHERE request_id = $1\n1100,SELECT a FROM auction WHERE request_id = $1\n"),
        (10, "running_ms,query\n"),
    ])
    out = slow_queries(RunEvidence(obs), **W)
    assert out["queries"][0]["seen_running"] == 2 and out["queries"][0]["running_ms"]["p50"] == 1100
    header = "relname,seq_scan,seq_tup_read,idx_scan,n_live_tup\n"
    _samples(obs, "table_scans", [
        (0, header + "auction,1,10,500,2000000\nbid,0,0,10,100\n"),
        (10, header + "auction,21,40000010,500,2000000\nbid,0,0,30,100\n"),
    ])
    tables = table_scans(RunEvidence(obs), **W)["tables"]
    assert list(tables)[0] == "auction"
    assert tables["auction"]["seq_scans_per_s"] == 2.0 and tables["auction"]["rows_read_by_seq_scans_per_s"] == 4_000_000


def test_repeated_values_counts_reprocessed_ids(run_dir):
    obs = run_dir / "observed"
    lines = [
        f'worker-1  | 2026-10-15T13:00:{s:02d}.000000001Z {{"event": "analytics_rollup_updated", "auction_id": "{a}"}}'
        for s, a in [(1, "x"), (2, "y"), (30, "x"), (31, "z")]
    ]
    (obs / "logs" / "worker.log").write_text("\n".join(lines) + "\n")
    out = repeated_values(RunEvidence(obs), "worker", "analytics_rollup_updated", "auction_id", **W)
    assert out["values_seen_more_than_once"] == 1
    assert out["examples"][0] == {"value": "x", "times": 2, "first_seen": "logs/worker.log:1"}


@pytest.mark.parametrize(
    "raw, problem",
    [
        ({"kind": "rollback_migration", "migration": "DROP TABLE auction"}, "not a known migration"),
        ({"kind": "skip_stuck_message", "groups": ["analytics-consumer", "evil"]}, "non-empty subset"),
        ({"kind": "skip_stuck_message", "groups": []}, "non-empty subset"),
    ],
)
def test_new_change_kinds_are_allowlisted(raw, problem):
    with pytest.raises(remediation.InvalidChange, match=problem):
        remediation.parse_change(raw)


def test_rollback_migration_must_have_been_applied(run_dir):
    obs = run_dir / "observed"
    change = remediation.parse_change({"kind": "rollback_migration", "migration": "0004_auction_request_id_collation"})
    with pytest.raises(remediation.InvalidChange, match="nothing to roll back"):
        remediation.resolve([change], RunEvidence(obs))
    (obs / "deployments.jsonl").write_text(json.dumps(
        {"started_at": "2026-10-15T13:00:20Z", "from_version": "1", "to_version": "2", "config_changes": [],
         "migrations": ["0004_auction_request_id_collation"]}) + "\n")
    assert remediation.resolve([change], RunEvidence(obs)) == [change]


def test_planner_picks_skip_for_a_crash_loop_and_fewer_retries_otherwise(run_dir):
    ev = RunEvidence(run_dir / "observed")
    crash = {"hypotheses": [{"category": "poison_message", "component": "worker crash-looping", "statement": ""}]}
    assert remediation.plan(crash, ev)["changes"][0]["kind"] == "skip_stuck_message"
    retry = {"hypotheses": [{"category": "poison_message", "component": "", "statement": "handlers retry"}]}
    assert remediation.plan(retry, ev)["changes"] == [{"kind": "deploy_setting", "setting": "EVENT_MAX_RETRIES", "value": "0"}]


def test_offline_policy_names_a_crash_looping_worker(run_dir):
    obs = run_dir / "observed"
    timeline = [
        {"sampled_at": f"2026-10-15T13:00:{s:02d}.000+00:00", "finished_auctions": 100 + 20 * s, "rolled_up": 100 + 20 * min(s, 20), "not_yet_counted": 20 * max(0, s - 20)}
        for s in range(0, 60, 5)
    ]
    incident = json.loads((obs / "incident.json").read_text())
    incident["alert"] = {"metric": "analytics_backlog", "definition": "d", "timeline": timeline}
    (obs / "incident.json").write_text(json.dumps(incident))
    _kafka(obs, [(100, 100), (300, 300), (300, 500), (300, 700), (300, 900)])
    log = [f'worker-1  | 2026-10-15T13:00:{s:02d}.000000001Z {{"event": "worker_starting", "level": "info"}}\n'
           f"worker-1  | 2026-10-15T13:00:{s:02d}.100000001Z json.decoder.JSONDecodeError: Expecting value: line 1 column 77"
           for s in range(21, 60, 6)]
    (obs / "logs" / "worker.log").write_text("\n".join(log) + "\n")
    report = investigate(run_dir, OfflinePolicy(), "agent_offline")
    assert not report.abstained, report.abstain_reason
    assert report.hypotheses[0].category == "poison_message"
    assert "crash" in report.hypotheses[0].component
