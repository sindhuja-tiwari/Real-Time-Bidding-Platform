import json
import time

import pytest
from fastapi.testclient import TestClient

from evidenceops import api, sandbox, service

RUN_ID = "20261015T130000Z-s03-db-pool-exhaustion"
DEPLOY = {
    "started_at": "2026-10-15T13:00:20Z", "finished_at": "2026-10-15T13:00:28Z",
    "from_version": "1.0.0", "to_version": "1.3.0", "services": ["backend", "worker"],
    "config_changes": [{"setting": "DB_POOL_SIZE", "from": "20", "to": "2"}],
}
TRUTH = {
    "scenario_id": "s03-db-pool-exhaustion", "category": "db_pool_exhaustion", "ambiguous": False,
    "acceptable_categories": ["db_pool_exhaustion"], "component": "DB_POOL_SIZE",
}


@pytest.fixture
def runs(run_dir, tmp_path_factory, monkeypatch):
    """The shared fixture run, filed under RUNS_DIR the way the runner does."""
    root = tmp_path_factory.mktemp("runs")
    run = root / RUN_ID
    run_dir.rename(run)
    (run / "observed" / "deployments.jsonl").write_text(json.dumps(DEPLOY) + "\n")
    (run / "ground_truth").mkdir()
    (run / "ground_truth" / "ground_truth.json").write_text(json.dumps(TRUTH))
    monkeypatch.setattr(service, "RUNS_DIR", root)
    return run


@pytest.fixture
def client(runs):
    return TestClient(api.create_app(token="", cors_origins=[]))


def _wait(client, job):
    for _ in range(200):
        job = client.get(f"/jobs/{job['id']}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job never finished: {job}")


def _save_report(run, category):
    (run / "investigations").mkdir(exist_ok=True)
    (run / "investigations" / "agent_offline.json").write_text(json.dumps({
        "method": "agent_offline", "incident_id": "inc-test", "abstained": False, "tool_calls": 3,
        "hypotheses": [{"category": category, "component": "", "statement": "s", "confidence": 0.8,
                        "supporting": ["E1"], "refuting": []}],
        "remediation": {},
    }))


def test_scenario_catalogue_does_not_reveal_the_answer(client):
    scenarios = client.get("/scenarios").json()
    assert len(scenarios) >= 20
    assert set(scenarios[0]) == {"id", "title", "report", "alert", "ambiguous"}


def test_runs_are_listed_without_ground_truth(client):
    [summary] = client.get("/runs").json()
    assert summary["run_id"] == RUN_ID and summary["incident_id"] == "inc-test"
    detail = client.get(f"/runs/{RUN_ID}").json()
    assert detail["deployments"][0]["to_version"] == "1.3.0"
    assert "ground_truth" not in json.dumps(detail)
    assert client.get(f"/runs/{RUN_ID}/grading").json()["ground_truth"]["category"] == "db_pool_exhaustion"


@pytest.mark.parametrize("bad", ["nope", "..", "20261015T130000Z-..%2F..%2Fetc"])
def test_only_recorded_runs_can_be_addressed(client, bad):
    assert client.get(f"/runs/{bad}").status_code == 404


def test_evidence_tools_are_read_only_and_validated(client):
    result = client.post(f"/runs/{RUN_ID}/tools/list_deployments", json={"args": {}}).json()
    assert result["evidence_id"] == "E1" and result["deployments"][0]["to_version"] == "1.3.0"
    assert client.post(f"/runs/{RUN_ID}/tools/shell", json={"args": {"cmd": "id"}}).status_code == 404
    assert client.post(f"/runs/{RUN_ID}/tools/db_indexes", json={"args": {"sql": "x"}}).status_code == 422


def test_investigation_runs_as_a_job_and_is_saved(client, runs):
    job = client.post(f"/runs/{RUN_ID}/investigations", json={"method": "agent_offline"})
    assert job.status_code == 202
    done = _wait(client, job.json())
    assert done["status"] == "succeeded", done["error"]
    saved = client.get(f"/runs/{RUN_ID}/investigations/agent_offline").json()
    assert saved["method"] == "agent_offline"
    assert (runs / "investigations" / "agent_offline.json").exists()


def test_model_methods_without_a_key_are_refused_up_front(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    response = client.post(f"/runs/{RUN_ID}/investigations", json={"method": "agent"})
    assert response.status_code == 409 and "ANTHROPIC_API_KEY" in response.json()["detail"]
    assert client.post(f"/runs/{RUN_ID}/investigations", json={"method": "rm"}).status_code == 409


def test_remediation_needs_approval_of_the_reviewed_digest(client, runs, monkeypatch):
    _save_report(runs, "db_pool_exhaustion")
    proposal = client.post(f"/runs/{RUN_ID}/remediation/propose", json={"method": "agent_offline"}).json()
    assert proposal["status"] == "awaiting_approval"
    assert proposal["resolved_changes"] == [
        {"kind": "deploy_setting", "setting": "DB_POOL_SIZE", "value": "20", "rolled_back": True}
    ]
    test_body = {"method": "agent_offline"}
    assert client.post(f"/runs/{RUN_ID}/remediation/test", json=test_body).status_code == 409

    wrong = {"method": "agent_offline", "approver": "Rishabh", "digest": "0" * 16}
    assert client.post(f"/runs/{RUN_ID}/remediation/approve", json=wrong).status_code == 409
    right = {**wrong, "digest": proposal["digest"]}
    approved = client.post(f"/runs/{RUN_ID}/remediation/approve", json=right).json()
    assert approved["status"] == "approved" and approved["approved_by"] == "Rishabh"

    seen = {}

    def fake_experiment(run_dir, approved_proposal, stack=None, time_scale=1.0):
        seen["changes"] = approved_proposal["resolved_changes"]
        return {"verdict": "verified"}

    monkeypatch.setattr(sandbox, "run_experiment", fake_experiment)
    done = _wait(client, client.post(f"/runs/{RUN_ID}/remediation/test", json=test_body).json())
    assert done["status"] == "succeeded" and done["result"] == {"verdict": "verified"}
    assert seen["changes"] == proposal["resolved_changes"]


def test_a_proposal_edited_on_disk_cannot_be_approved(client, runs):
    _save_report(runs, "db_pool_exhaustion")
    proposal = client.post(f"/runs/{RUN_ID}/remediation/propose", json={"method": "agent_offline"}).json()
    path = runs / "remediation" / "agent_offline.proposal.json"
    tampered = json.loads(path.read_text())
    tampered["changes"] = [{"kind": "deploy_setting", "setting": "DB_POOL_SIZE", "value": "30"}]
    path.write_text(json.dumps(tampered))
    body = {"method": "agent_offline", "approver": "Rishabh", "digest": proposal["digest"]}
    response = client.post(f"/runs/{RUN_ID}/remediation/approve", json=body)
    assert response.status_code == 409 and "changed after it was proposed" in response.json()["detail"]


def test_token_guards_every_call_that_starts_work(runs):
    client = TestClient(api.create_app(token="s3cret", cors_origins=[]))
    assert client.get("/runs").status_code == 200
    assert client.post(f"/runs/{RUN_ID}/investigations", json={"method": "fixed_workflow"}).status_code == 401
    assert client.post("/runs", json={"scenario_ids": ["s01-slow-external-bidders"]}).status_code == 401
    ok = client.post(f"/runs/{RUN_ID}/investigations", json={"method": "fixed_workflow"},
                     headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 202


def test_unknown_scenarios_are_rejected_before_any_docker_work(client):
    assert client.post("/runs", json={"scenario_ids": ["s99-nope"]}).status_code == 404
    assert client.get("/jobs").json() == []


def test_server_will_not_listen_publicly_without_a_token(monkeypatch):
    monkeypatch.delenv(api.TOKEN_ENV, raising=False)
    with pytest.raises(SystemExit, match="refusing"):
        api.serve("0.0.0.0", 8100)
