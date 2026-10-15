import copy

import pytest

from evidenceops.faults import DeployState, DeployStep, FaultError, parse_step, read_env_file
from evidenceops.scenario import ROOT_CAUSE_CATEGORIES, ScenarioError, load_all, parse_scenario


def test_shipped_scenarios_are_valid_and_unique():
    scenarios = load_all()
    assert len(scenarios) >= 3
    for s in scenarios:
        assert s.ground_truth.category in ROOT_CAUSE_CATEGORIES
        assert s.ground_truth.distinguishing_evidence
        assert s.ground_truth.remediation.get("expected_min_success_rate")


def test_shipped_scenarios_share_one_report_per_alert_so_the_cause_is_not_given_away():
    reports = {}
    for s in load_all():
        reports.setdefault(s.alert, set()).add(s.report)
    assert all(len(r) == 1 for r in reports.values()), reports


MINIMAL = {
    "id": "x",
    "title": "t",
    "report": "r",
    "traffic": {"incident_seconds": 30},
    "steps": [{"at": 0, "action": "deploy", "version": "2.0", "env": {"DB_POOL_SIZE": "1"}}],
    "ground_truth": {
        "category": "db_pool_exhaustion",
        "component": "c",
        "summary": "s",
        "causal_steps": [0],
        "causal_settings": ["DB_POOL_SIZE"],
        "distinguishing_evidence": ["e"],
        "remediation": {"expected_min_success_rate": 0.9},
    },
}


def _with(**changes):
    data = copy.deepcopy(MINIMAL)
    for dotted, value in changes.items():
        target = data
        *path, last = dotted.split("__")
        for key in path:
            target = target[key]
        target[last] = value
    return data


def test_minimal_scenario_parses():
    assert parse_scenario(_with()).id == "x"


@pytest.mark.parametrize(
    "changes",
    [
        {"ground_truth__category": "cosmic_rays"},
        {"ground_truth__causal_steps": []},
        {"ground_truth__causal_steps": [3]},
        {"ground_truth__decoy_steps": [0]},
        {"ground_truth__causal_settings": ["AUCTION_GLOBAL_TIMEOUT_MS"]},
        {"steps": [{"at": 40, "action": "deploy", "version": "2", "env": {}}]},
    ],
)
def test_inconsistent_scenarios_are_rejected(changes):
    with pytest.raises((ScenarioError, FaultError)):
        parse_scenario(_with(**changes))


def test_deploy_cannot_touch_settings_outside_the_allowlist():
    with pytest.raises(FaultError):
        parse_step({"action": "deploy", "version": "2", "env": {"DATABASE_URL": "postgres://evil"}}, "t")
    with pytest.raises(FaultError):
        parse_step({"action": "deploy", "version": "2", "env": {"JWT_SECRET": "x"}}, "t")


def test_dsp_config_is_limited_to_known_dsps_and_fields():
    with pytest.raises(FaultError):
        parse_step({"action": "dsp_config", "dsps": ["dsp-z"], "set": {"latency_ms": 1}}, "t")
    with pytest.raises(FaultError):
        parse_step({"action": "dsp_config", "dsps": ["dsp-a"], "set": {"campaign_id": "x"}}, "t")


def test_there_is_no_command_action():
    with pytest.raises(FaultError):
        parse_step({"action": "shell", "command": "rm -rf /"}, "t")


def test_deploy_state_records_only_real_changes_and_accumulates():
    state = DeployState(base_env=read_env_file("A=1\n# comment\nDB_POOL_SIZE=20\n"), version="1.0.0")
    record = state.apply(DeployStep(at=0, version="1.1.0", env={"DB_POOL_SIZE": "2", "A": "1"}))
    assert record["config_changes"] == [{"setting": "DB_POOL_SIZE", "from": "20", "to": "2"}]
    assert record["from_version"] == "1.0.0" and record["to_version"] == "1.1.0"

    record = state.apply(DeployStep(at=0, version="1.2.0", env={"DB_POOL_SIZE": "20"}))
    assert record["config_changes"] == [{"setting": "DB_POOL_SIZE", "from": "2", "to": "20"}]
    override = state.compose_override()["services"]["backend"]["environment"]
    assert override == {"A": "1", "DB_POOL_SIZE": "20", "APP_VERSION": "1.2.0"}
