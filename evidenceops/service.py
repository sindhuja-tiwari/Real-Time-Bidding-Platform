"""Operations shared by the command line and the HTTP API.

Both front ends call these functions, so a run, an investigation or a
remediation started from the API is the same thing, on disk, as one started
from the CLI. Everything here reads or writes run directories under
``RUNS_DIR``; the functions that touch Docker are ``record_run`` and
``test_remediation``, and only ever one of those may run at a time because
they share one platform stack.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from evidenceops import investigation, remediation
from evidenceops import scenario as scenario_mod
from evidenceops.paths import RUNS_DIR

PROVIDERS = ("anthropic", "gemini", "groq")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
_RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-z0-9-]+$")
_METHOD_NAME = re.compile(r"^[a-z_]+$")


class NotFound(LookupError):
    pass


class Rejected(ValueError):
    """The request is understood but not allowed (bad input or wrong state)."""


# ---------------------------------------------------------------- scenarios


def scenarios() -> List[Dict[str, Any]]:
    """The scenario catalogue, without the answer key."""
    return [
        {"id": s.id, "title": s.title, "report": s.report, "alert": s.alert, "ambiguous": s.ambiguous}
        for s in scenario_mod.load_all()
    ]


def find_scenario(scenario_id: str) -> scenario_mod.Scenario:
    try:
        return scenario_mod.find(scenario_id)
    except scenario_mod.ScenarioError as exc:
        raise NotFound(str(exc)) from None


def record_run(scenario_ids: List[str], quick: bool = False, keep_up: bool = False,
               on_result: Optional[Callable[[Dict[str, Any]], None]] = None) -> List[Dict[str, Any]]:
    """Reset the platform, inject each scenario and record a run (needs Docker)."""
    from evidenceops.runner import run_scenario
    from evidenceops.stack import Stack

    targets = [find_scenario(i) for i in scenario_ids]
    stack = Stack()
    results = []
    try:
        for s in targets:
            result = run_scenario(s, stack, time_scale=0.5 if quick else 1.0)
            result["run_id"] = Path(result["run_dir"]).name
            results.append(result)
            if on_result:
                on_result(result)
    finally:
        if not keep_up:
            stack.down()
    return results


# --------------------------------------------------------------------- runs


def run_dir(run_id: str) -> Path:
    """The directory of a recorded run, refusing anything that is not one."""
    if not _RUN_ID.match(run_id):
        raise NotFound(f"no run '{run_id}'")
    path = RUNS_DIR / run_id
    if not (path / "observed" / "incident.json").exists():
        raise NotFound(f"no run '{run_id}'")
    return path


def all_run_dirs() -> List[Path]:
    if not RUNS_DIR.is_dir():
        return []
    return sorted(p for p in RUNS_DIR.iterdir() if (p / "observed" / "incident.json").exists())


def _read(path: Path) -> Optional[Dict[str, Any]]:
    return json.loads(path.read_text()) if path.exists() else None


def _reports(directory: Path) -> Dict[str, Dict[str, Any]]:
    found = sorted(p for p in (directory / "investigations").glob("*.json") if not p.name.endswith(".transcript.json"))
    return {p.stem: json.loads(p.read_text()) for p in found}


def _top(report: Dict[str, Any]) -> Optional[str]:
    if report.get("abstained") or not report.get("hypotheses"):
        return None
    return report["hypotheses"][0]["category"]


def run_summary(directory: Path) -> Dict[str, Any]:
    """What an operator sees in a list: the incident, never the answer key."""
    incident = json.loads((directory / "observed" / "incident.json").read_text())
    remediations = {}
    for path in sorted((directory / "remediation").glob("*.proposal.json")):
        method = path.name[: -len(".proposal.json")]
        proposal = json.loads(path.read_text())
        result = _read(directory / "remediation" / f"{method}.result.json")
        remediations[method] = {
            "status": proposal.get("status"),
            "verdict": result.get("verdict") if result and result.get("proposal_digest") == proposal.get("digest") else None,
        }
    return {
        "run_id": directory.name,
        "incident_id": incident.get("incident_id"),
        "report": incident.get("report"),
        "alert_metric": incident.get("alert", {}).get("metric"),
        "telemetry_window": incident.get("telemetry_window"),
        "investigations": {
            m: {"top": _top(r), "abstained": bool(r.get("abstained")), "tool_calls": r.get("tool_calls")}
            for m, r in _reports(directory).items()
        },
        "remediations": remediations,
    }


def run_detail(directory: Path) -> Dict[str, Any]:
    return {
        **run_summary(directory),
        "incident": json.loads((directory / "observed" / "incident.json").read_text()),
        "deployments": [
            json.loads(line) for line in (directory / "observed" / "deployments.jsonl").read_text().splitlines() if line
        ],
    }


def grading(directory: Path) -> Dict[str, Any]:
    """The answer key and how each saved investigation scored against it."""
    truth = _read(directory / "ground_truth" / "ground_truth.json")
    if truth is None:
        raise NotFound(f"{directory.name} has no ground truth")
    return {
        "ground_truth": truth,
        "verification": _read(directory / "ground_truth" / "verification.json"),
        "grades": [investigation.grade(r, truth) for r in _reports(directory).values()],
    }


# ----------------------------------------------------------- investigations


def _model(provider: str, model: Optional[str], effort: str):
    if provider not in PROVIDERS:
        raise Rejected(f"provider must be one of {list(PROVIDERS)}")
    try:
        if provider == "anthropic":
            from evidenceops.agent import claude

            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise SystemExit("No anthropic key found. Export it as ANTHROPIC_API_KEY where EvidenceOps runs.")
            return claude.ClaudeModel(model=model or claude.DEFAULT_MODEL, effort=effort)
        from evidenceops.agent.openai_compat import OpenAICompatModel

        return OpenAICompatModel(provider, model=model)
    except SystemExit as exc:
        raise Rejected(str(exc)) from None


def _suffix(provider: str) -> str:
    return "" if provider == "anthropic" else f"_{provider}"


def _fixed_workflow(directory: Path, opts: Dict[str, Any]):
    from evidenceops.baselines import fixed_workflow

    return fixed_workflow.investigate(directory)


def _agent_offline(directory: Path, opts: Dict[str, Any]):
    from evidenceops.agent import loop, offline

    return loop.investigate(directory, offline.OfflinePolicy(), method="agent_offline",
                            max_tool_calls=opts["max_tool_calls"])


def _agent(directory: Path, opts: Dict[str, Any]):
    from evidenceops.agent import loop

    return loop.investigate(directory, opts["model"], method="agent" + _suffix(opts["provider"]),
                            max_tool_calls=opts["max_tool_calls"])


def _log_only(directory: Path, opts: Dict[str, Any]):
    from evidenceops.baselines import log_only

    return log_only.investigate(directory, opts["model"], method="log_only" + _suffix(opts["provider"]))


# name -> (function, needs a model API key)
METHODS: Dict[str, Tuple[Callable[[Path, Dict[str, Any]], investigation.Report], bool]] = {
    "fixed_workflow": (_fixed_workflow, False),
    "agent_offline": (_agent_offline, False),
    "agent": (_agent, True),
    "log_only": (_log_only, True),
}


class Investigator:
    """One investigation method, configured once and reused across runs."""

    def __init__(self, method: str, provider: str = "anthropic", model: Optional[str] = None,
                 effort: str = "high", max_tool_calls: int = 20):
        if method not in METHODS:
            raise Rejected(f"method must be one of {list(METHODS)}")
        if effort not in EFFORTS:
            raise Rejected(f"effort must be one of {list(EFFORTS)}")
        if not 1 <= max_tool_calls <= 50:
            raise Rejected("max_tool_calls must be between 1 and 50")
        self.fn, needs_model = METHODS[method]
        self.opts: Dict[str, Any] = {"provider": provider, "max_tool_calls": max_tool_calls, "model": None}
        if needs_model:
            self.opts["model"] = _model(provider, model, effort)

    def __call__(self, directory: Path) -> Tuple[investigation.Report, Path]:
        report = self.fn(directory, self.opts)
        return report, investigation.save(report, directory)


def report(directory: Path, method: str) -> Dict[str, Any]:
    if not _METHOD_NAME.match(method):
        raise NotFound(f"no investigation '{method}'")
    found = _read(directory / "investigations" / f"{method}.json")
    if found is None:
        raise NotFound(f"no {method} investigation for {directory.name}")
    return found


def evaluate(directories: List[Path], methods: Optional[List[str]] = None) -> Dict[str, Any]:
    rows = []
    for directory in directories:
        truth = _read(directory / "ground_truth" / "ground_truth.json")
        if truth is None:
            continue
        for method, found in _reports(directory).items():
            if methods and method not in methods:
                continue
            row = investigation.grade(found, truth)
            result = _read(directory / "remediation" / f"{method}.result.json")
            if result:
                row["remediation_verdict"] = result["verdict"]
            rows.append(row)
    by_method: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_method.setdefault(r["method"], []).append(r)
    return {"runs": rows, "summary": {m: investigation.aggregate(rs) for m, rs in by_method.items()}}


# -------------------------------------------------------------- remediation


def _remediation_call(fn, *args):
    try:
        return fn(*args)
    except FileNotFoundError:
        raise NotFound("no saved investigation for that method; investigate first") from None
    except (SystemExit, remediation.InvalidChange) as exc:
        raise Rejected(str(exc)) from None


def propose(directory: Path, method: str) -> Dict[str, Any]:
    if not _METHOD_NAME.match(method):
        raise NotFound(f"no investigation '{method}'")
    return _remediation_call(remediation.propose, directory, method)


def proposal(directory: Path, method: str) -> Dict[str, Any]:
    found = _read(remediation.proposal_path(directory, method)) if _METHOD_NAME.match(method) else None
    if found is None:
        raise NotFound(f"no {method} proposal for {directory.name}")
    return found


def approve(directory: Path, method: str, approver: str, digest: str) -> Dict[str, Any]:
    """Approve exactly the proposal the approver reviewed, identified by digest."""
    current = proposal(directory, method)
    if digest != current.get("digest"):
        raise Rejected("the proposal changed since it was reviewed (digest mismatch); review it again")
    return _remediation_call(remediation.approve, directory, method, approver)


def test_remediation(directory: Path, method: str, quick: bool = False) -> Dict[str, Any]:
    """Run an approved proposal in a disposable copy of the platform (needs Docker)."""
    from evidenceops.sandbox import run_experiment

    approved = proposal(directory, method)
    if approved.get("status") != "approved":
        raise Rejected("the proposal has not been approved")
    return _remediation_call(run_experiment, directory, approved, None, 0.5 if quick else 1.0)


def remediation_result(directory: Path, method: str) -> Dict[str, Any]:
    found = _read(directory / "remediation" / f"{method}.result.json") if _METHOD_NAME.match(method) else None
    if found is None:
        raise NotFound(f"no {method} sandbox result for {directory.name}")
    return found
