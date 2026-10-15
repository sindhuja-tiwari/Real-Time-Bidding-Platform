import json

import pytest

from evidenceops import remediation
from evidenceops.agent import spec
from evidenceops.sandbox import run_experiment
from evidenceops.telemetry import RunEvidence

DEPLOY = {
    "started_at": "2026-10-15T13:00:20Z", "finished_at": "2026-10-15T13:00:28Z",
    "from_version": "1.0.0", "to_version": "1.3.0", "services": ["backend", "worker"],
    "config_changes": [
        {"setting": "DB_POOL_SIZE", "from": "20", "to": "2"},
        {"setting": "DB_MAX_OVERFLOW", "from": "10", "to": "0"},
        {"setting": "REDIS_CACHE_TTL_SECONDS", "from": "30", "to": "45"},
    ],
}


@pytest.fixture
def deployed_run(run_dir):
    (run_dir / "observed" / "deployments.jsonl").write_text(json.dumps(DEPLOY) + "\n")
    return run_dir


def _save_report(run_dir, method, hypotheses, abstained=False, remediation_block=None):
    path = run_dir / "investigations" / f"{method}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({
        "method": method, "hypotheses": hypotheses, "abstained": abstained,
        "remediation": remediation_block or {},
    }))


@pytest.mark.parametrize("raw, problem", [
    ({"kind": "shell", "command": "rm -rf /"}, "unknown change kind"),
    ({"kind": "deploy_setting", "setting": "DATABASE_URL", "value": "x"}, "not a deployable setting"),
    ({"kind": "deploy_setting", "setting": "DB_POOL_SIZE", "value": "20; reboot"}, "not a number"),
    ({"kind": "deploy_setting", "setting": "DB_POOL_SIZE", "value": "5000"}, "outside"),
    ({"kind": "dsp_timeout_ms", "dsps": ["DSP-Z"], "value": "200"}, "subset"),
    ({"kind": "dsp_timeout_ms", "dsps": ["DSP-A"], "value": "5"}, "outside"),
])
def test_only_allowlisted_bounded_changes_parse(raw, problem):
    with pytest.raises(remediation.InvalidChange, match=problem):
        remediation.parse_change(raw)


def test_rollbacks_resolve_to_the_value_before_the_deploy(deployed_run):
    ev = RunEvidence(deployed_run / "observed")
    resolved = remediation.resolve([{"kind": "rollback_setting", "setting": "DB_POOL_SIZE"}], ev)
    assert resolved == [{"kind": "deploy_setting", "setting": "DB_POOL_SIZE", "value": "20", "rolled_back": True}]
    with pytest.raises(remediation.InvalidChange, match="nothing to roll back"):
        remediation.resolve([{"kind": "rollback_setting", "setting": "EVENT_MAX_RETRIES"}], ev)


def test_planner_rolls_back_only_settings_that_fit_the_hypothesis(deployed_run):
    ev = RunEvidence(deployed_run / "observed")
    plan = remediation.plan({"hypotheses": [{"category": "db_pool_exhaustion", "component": ""}], "abstained": False}, ev)
    assert plan["purpose"] == "fix"
    assert {c["setting"] for c in plan["changes"]} == {"DB_MAX_OVERFLOW", "DB_POOL_SIZE"}


def test_abstaining_reports_get_an_experiment_not_a_fix(deployed_run):
    ev = RunEvidence(deployed_run / "observed")
    plan = remediation.plan({"hypotheses": [], "abstained": True}, ev)
    assert plan["purpose"] == "experiment" and len(plan["changes"]) == 2


def test_external_latency_raises_deadlines_for_the_named_bidders(deployed_run):
    ev = RunEvidence(deployed_run / "observed")
    plan = remediation.plan({"hypotheses": [{"category": "external_dsp_latency", "component": "DSP-A, DSP-D", "statement": ""}]}, ev)
    dsp_change = [c for c in plan["changes"] if c["kind"] == "dsp_timeout_ms"][0]
    assert dsp_change["dsps"] == ["DSP-A", "DSP-D"]


def test_proposals_need_a_named_approval_and_cannot_be_edited_after(deployed_run):
    _save_report(deployed_run, "m", [{"category": "db_pool_exhaustion", "component": ""}])
    proposal = remediation.propose(deployed_run, "m")
    assert proposal["status"] == "awaiting_approval"
    with pytest.raises(SystemExit, match="refusing"):
        run_experiment(deployed_run, proposal)
    with pytest.raises(SystemExit, match="needs a name"):
        remediation.approve(deployed_run, "m", " ")

    path = remediation.proposal_path(deployed_run, "m")
    tampered = json.loads(path.read_text())
    tampered["changes"].append({"kind": "deploy_setting", "setting": "DB_POOL_SIZE", "value": "1"})
    path.write_text(json.dumps(tampered))
    with pytest.raises(SystemExit, match="changed after it was proposed"):
        remediation.approve(deployed_run, "m", "Sindhuja")

    remediation.propose(deployed_run, "m")
    approved = remediation.approve(deployed_run, "m", "Sindhuja")
    assert approved["status"] == "approved" and approved["approved_by"] == "Sindhuja"


def test_investigator_remediations_are_validated_with_the_report():
    report = {"timeline": [], "hypotheses": [], "abstain": True, "abstain_reason": "unclear",
              "remediation": {"changes": [{"kind": "shell", "setting": "x"}], "rationale": "r"}}
    assert any("remediation change 1" in p for p in spec.validate_report(report, set()))
