"""The investigator harness, driven by scripted models (no API calls)."""
import json
from types import SimpleNamespace

from evidenceops.agent import claude, loop, spec
from evidenceops.agent.offline import OfflinePolicy
from evidenceops.baselines import log_only

WINDOW = {"start": "2026-10-15T13:00:30Z", "end": "2026-10-15T13:01:00Z"}


def _hyp(supporting, category="db_pool_exhaustion"):
    return {"category": category, "component": "DB_POOL_SIZE", "statement": "s", "confidence": 0.8,
            "supporting": supporting, "refuting": []}


def _report(supporting):
    return {"timeline": [], "hypotheses": [_hyp(supporting)], "abstain": False, "abstain_reason": ""}


class FakeClient:
    """Stands in for anthropic.Anthropic(): returns scripted messages, records requests."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        blocks = self.script.pop(0)
        content = [
            SimpleNamespace(type="tool_use", id=f"tu{i}", name=b[0], input=b[1]) if isinstance(b, tuple)
            else SimpleNamespace(type="text", text=b)
            for i, b in enumerate(blocks)
        ]
        stop = "tool_use" if any(c.type == "tool_use" for c in content) else "end_turn"
        usage = SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        return SimpleNamespace(content=content, stop_reason=stop, usage=usage, model=kwargs["model"])


def _tool_results(request):
    return [b for b in request["messages"][-1]["content"]]


def test_claude_requests_use_current_model_settings(run_dir):
    client = FakeClient([[("alert_timeline", {})], [("submit_report", _report(["E1"]))]])
    report = loop.investigate(run_dir, claude.ClaudeModel(client=client), method="agent")

    first = client.requests[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["thinking"] == {"type": "adaptive"} and first["output_config"] == {"effort": "high"}
    assert first["fallbacks"] == "default" and first["tools"][-1]["name"] == "submit_report"
    assert not report.abstained and report.hypotheses[0].supporting == ["E1"]
    assert report.tool_calls == 1
    assert report.cost_usd == round(2 * claude.cost_of("claude-opus-5-5", {"input_tokens": 1000, "output_tokens": 200}), 6)


def test_reports_citing_unseen_evidence_are_sent_back(run_dir):
    client = FakeClient([
        [("bid_outcomes", WINDOW)],
        [("submit_report", _report(["E1", "E7"]))],
        [("submit_report", _report(["E1"]))],
    ])
    report = loop.investigate(run_dir, claude.ClaudeModel(client=client), method="agent")

    rejection = _tool_results(client.requests[2])[0]
    assert rejection["is_error"] and "E7" in rejection["content"]
    assert report.meta["rejected_reports"] == 1 and report.hypotheses[0].supporting == ["E1"]


def test_repeated_bad_citations_end_in_abstention(run_dir):
    bad = [("submit_report", _report(["E9"]))]
    client = FakeClient([bad, bad, bad])
    report = loop.investigate(run_dir, claude.ClaudeModel(client=client), method="agent", max_report_retries=2)
    assert report.abstained and report.abstain_reason.startswith("harness:") and report.hypotheses == []


def test_unknown_tools_and_bad_arguments_are_errors_not_evidence(run_dir):
    client = FakeClient([
        [("run_shell", {"command": "rm -rf /"}), ("log_events", {"service": "../etc", **WINDOW})],
        [("submit_report", {"timeline": [], "hypotheses": [], "abstain": True, "abstain_reason": "nothing"})],
    ])
    report = loop.investigate(run_dir, claude.ClaudeModel(client=client), method="agent")
    results = _tool_results(client.requests[1])
    assert all(r["is_error"] for r in results)
    assert report.tool_calls == 0 and report.abstained


def test_tool_budget_is_enforced_by_the_harness(run_dir):
    client = FakeClient([
        [("alert_timeline", {}), ("list_deployments", {}), ("bid_outcomes", WINDOW)],
        [("submit_report", _report(["E1"]))],
    ])
    report = loop.investigate(run_dir, claude.ClaudeModel(client=client), method="agent", max_tool_calls=2)
    results = _tool_results(client.requests[1])
    assert [bool(r.get("is_error")) for r in results] == [False, False, True]
    assert report.tool_calls == 2 and report.meta["refused_tool_calls"] == 1


def test_a_model_that_never_submits_is_nudged_then_stops(run_dir):
    client = FakeClient([["thinking out loud"]] * 3)
    report = loop.investigate(run_dir, claude.ClaudeModel(client=client), method="agent", max_turns=3)
    assert "submit_report" in client.requests[1]["messages"][-1]["content"]
    assert report.abstained and "no accepted report" in report.abstain_reason


def test_offline_policy_abstains_without_a_drop(run_dir):
    report = loop.investigate(run_dir, OfflinePolicy(), method="agent_offline")
    assert report.abstained and "no sustained drop" in report.abstain_reason and report.tool_calls == 1


def test_validation_catches_each_kind_of_bad_report():
    problems = spec.validate_report(
        {"timeline": [{"at": "x", "event": "e", "evidence": ["E5"]}],
         "hypotheses": [{**_hyp([]), "category": "gremlins", "confidence": 3}],
         "abstain": True, "abstain_reason": ""},
        {"E1"},
    )
    text = " | ".join(problems)
    for expected in ("abstain_reason", "unknown category", "confidence", "no supporting", "timeline entry 1"):
        assert expected in text


def test_log_only_sends_logs_and_no_tools(run_dir):
    answer = json.dumps(_report(["E1"]))
    client = FakeClient([[answer]])
    report = log_only.investigate(run_dir, client=client)

    request = client.requests[0]
    assert "tools" not in request and request["output_config"]["format"]["type"] == "json_schema"
    assert "QueuePool limit" in request["messages"][0]["content"]
    assert set(report.evidence) == {"E1", "E2"} and report.tool_calls == 0
    assert report.hypotheses[0].category == "db_pool_exhaustion" and report.meta["validation_problems"] == []
