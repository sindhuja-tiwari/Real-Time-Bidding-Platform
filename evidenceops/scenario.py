"""Incident scenario definitions.

A scenario is a YAML file describing:

- ``report``: what the on-call engineer is told (the only text an
  investigator gets up front).
- ``traffic``: the steady auction load driven before and during the incident.
- ``steps``: timed actions applied once the incident phase starts. Every
  action is one of a small allowlisted set (see ``faults.py``); scenarios can
  never run arbitrary commands.
- ``ground_truth``: the known root cause, which steps are causal and which
  are decoys, the evidence that distinguishes it from look-alike causes, and
  the remediation expected to fix it. Investigators never see this.
- ``verify``: what the harness must measure for the run to count as a valid
  reproduction (the incident has to actually happen, not just be injected).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from evidenceops.faults import DeployStep, Step, parse_step
from evidenceops.paths import SCENARIO_DIR

# Root-cause taxonomy shared by scenarios, graders, and (later) the agent's
# hypothesis space. Matches the incident families in the project brief.
ROOT_CAUSE_CATEGORIES = (
    "external_dsp_latency",
    "config_regression",
    "db_pool_exhaustion",
    "missing_index",
    "poison_message",
    "duplicate_delivery_idempotency",
)


class ScenarioError(ValueError):
    pass


@dataclass
class Traffic:
    rps: float = 30.0
    baseline_seconds: int = 40
    incident_seconds: int = 60
    publishers: int = 20
    client_timeout_seconds: float = 2.0


@dataclass
class GroundTruth:
    category: str
    component: str
    summary: str
    causal_steps: List[int]
    decoy_steps: List[int]
    distinguishing_evidence: List[str]
    remediation: Dict[str, Any]
    # For deploy-borne causes: which changed settings matter, and which
    # changes in the same deploys are harmless.
    causal_settings: List[str] = field(default_factory=list)
    decoy_settings: List[str] = field(default_factory=list)
    # Ambiguous scenarios only: the causes the evidence cannot tell apart.
    candidates: List[str] = field(default_factory=list)


@dataclass
class Verify:
    # Absolute drop in auction success rate (baseline minus incident window),
    # e.g. 0.3 means at least 30 percentage points.
    min_success_rate_drop: float = 0.3
    # Baseline must be healthy, otherwise the "incident" is just noise.
    min_baseline_success_rate: float = 0.9
    # Seconds after the last causal step finishes before the incident window
    # starts, so a deploy restart blip is not counted as the incident itself.
    settle_seconds: int = 5


@dataclass
class Scenario:
    id: str
    title: str
    report: str
    traffic: Traffic
    steps: List[Step]
    ground_truth: GroundTruth
    verify: Verify
    ambiguous: bool = False
    path: Optional[Path] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def first_causal_at(self) -> float:
        return min(self.steps[i].at for i in self.ground_truth.causal_steps)


def _require(data: Dict[str, Any], key: str, where: str) -> Any:
    if key not in data:
        raise ScenarioError(f"{where}: missing required field '{key}'")
    return data[key]


def parse_scenario(data: Dict[str, Any], path: Optional[Path] = None) -> Scenario:
    where = str(path) if path else "<scenario>"
    sid = _require(data, "id", where)
    traffic = Traffic(**(data.get("traffic") or {}))
    steps = [parse_step(s, f"{where} step {i}") for i, s in enumerate(_require(data, "steps", where))]
    if not steps:
        raise ScenarioError(f"{where}: at least one step is required")
    if any(s.at < 0 or s.at >= traffic.incident_seconds for s in steps):
        raise ScenarioError(f"{where}: every step's 'at' must fall inside the incident phase")

    gt_raw = _require(data, "ground_truth", where)
    gt = GroundTruth(
        category=_require(gt_raw, "category", where),
        component=_require(gt_raw, "component", where),
        summary=_require(gt_raw, "summary", where),
        causal_steps=list(_require(gt_raw, "causal_steps", where)),
        decoy_steps=list(gt_raw.get("decoy_steps") or []),
        distinguishing_evidence=list(_require(gt_raw, "distinguishing_evidence", where)),
        remediation=dict(_require(gt_raw, "remediation", where)),
        causal_settings=list(gt_raw.get("causal_settings") or []),
        decoy_settings=list(gt_raw.get("decoy_settings") or []),
        candidates=list(gt_raw.get("candidates") or []),
    )
    if gt.category not in ROOT_CAUSE_CATEGORIES:
        raise ScenarioError(f"{where}: unknown category '{gt.category}'")
    if not gt.causal_steps:
        raise ScenarioError(f"{where}: ground_truth.causal_steps must name at least one step")
    for idx in gt.causal_steps + gt.decoy_steps:
        if not 0 <= idx < len(steps):
            raise ScenarioError(f"{where}: step index {idx} out of range")
    if set(gt.causal_steps) & set(gt.decoy_steps):
        raise ScenarioError(f"{where}: a step cannot be both causal and a decoy")
    deployed = {k for st in steps if isinstance(st, DeployStep) for k in st.env}
    for key in gt.causal_settings + gt.decoy_settings:
        if key not in deployed:
            raise ScenarioError(f"{where}: setting '{key}' is not changed by any deploy step")

    ambiguous = bool(data.get("ambiguous", False))
    if ambiguous and len(gt.candidates) < 2:
        raise ScenarioError(f"{where}: an ambiguous scenario must list at least two ground_truth.candidates")
    for c in gt.candidates:
        if c not in ROOT_CAUSE_CATEGORIES:
            raise ScenarioError(f"{where}: unknown candidate category '{c}'")

    scenario = Scenario(
        id=sid,
        title=_require(data, "title", where),
        report=_require(data, "report", where).strip(),
        traffic=traffic,
        steps=steps,
        ground_truth=gt,
        verify=Verify(**(data.get("verify") or {})),
        ambiguous=ambiguous,
        path=path,
        raw=data,
    )
    if scenario.first_causal_at + scenario.verify.settle_seconds >= traffic.incident_seconds:
        raise ScenarioError(f"{where}: incident window is empty after settle_seconds")
    return scenario


def load_scenario(path: Path) -> Scenario:
    with open(path) as f:
        return parse_scenario(yaml.safe_load(f), path)


def load_all(directory: Path = SCENARIO_DIR) -> List[Scenario]:
    scenarios = [load_scenario(p) for p in sorted(directory.glob("*.yaml"))]
    ids = [s.id for s in scenarios]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ScenarioError(f"duplicate scenario ids: {sorted(dupes)}")
    return scenarios


def find(scenario_id: str, directory: Path = SCENARIO_DIR) -> Scenario:
    for s in load_all(directory):
        if s.id == scenario_id:
            return s
    raise ScenarioError(f"no scenario with id '{scenario_id}'")
