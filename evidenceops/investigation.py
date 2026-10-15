"""The investigation report every method produces, and how it is graded.

A report is the same shape whether it came from the fixed baseline, a
log-only prompt, or the agent, so they can be scored side by side:

- ``timeline``: what happened when, each entry citing evidence ids.
- ``hypotheses``: ranked, each with a root-cause category, a statement, and
  the evidence ids that support it (and optionally refute alternatives).
- ``abstained``: true when the method decided the evidence is insufficient.
- ``evidence``: every tool call the method made, keyed by evidence id.

Grading compares against ``ground_truth/`` (which methods never see).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Hypothesis:
    category: str
    statement: str
    confidence: float
    supporting: List[str]
    refuting: List[str] = field(default_factory=list)
    component: str = ""


@dataclass
class Report:
    method: str
    incident_id: str
    hypotheses: List[Hypothesis]
    abstained: bool
    abstain_reason: str = ""
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    tool_calls: int = 0
    elapsed_seconds: float = 0.0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)


def save(report: Report, run_dir: Path) -> Path:
    path = Path(run_dir) / "investigations" / f"{report.method}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_json(), indent=2, default=str) + "\n")
    return path


def grade(report: Dict[str, Any], ground_truth: Dict[str, Any]) -> Dict[str, Any]:
    """Score one report against one scenario's ground truth.

    - top1 / top3: the true category is ranked first / in the first three.
    - supported: the top hypothesis cites at least one evidence id that the
      method actually collected. A confident answer with no real evidence
      behind it counts as unsupported, right or wrong.
    - correct_abstention: on an ambiguous scenario, abstaining is the right
      answer; on a clear one, abstaining is a miss.
    """
    truth = ground_truth["category"]
    ambiguous = bool(ground_truth.get("ambiguous"))
    hyps = report.get("hypotheses") or []
    ranked = [h["category"] for h in hyps]
    abstained = bool(report.get("abstained"))
    evidence_ids = set((report.get("evidence") or {}).keys())

    top: Optional[Dict[str, Any]] = hyps[0] if hyps and not abstained else None
    supported = bool(top) and any(e in evidence_ids for e in top.get("supporting", []))
    top1 = bool(top) and top["category"] == truth and not ambiguous
    top3 = (not abstained) and truth in ranked[:3] and not ambiguous
    return {
        "method": report.get("method"),
        "scenario_id": ground_truth.get("scenario_id"),
        "truth": truth,
        "predicted": top["category"] if top else None,
        "top3": ranked[:3],
        "top1_correct": top1,
        "top3_correct": top3,
        "abstained": abstained,
        "correct_abstention": abstained if ambiguous else None,
        "supported": supported if top else None,
        "unsupported_diagnosis": bool(top) and not supported,
        "tool_calls": report.get("tool_calls", 0),
        "elapsed_seconds": report.get("elapsed_seconds", 0.0),
        "time_to_correct_diagnosis": report.get("elapsed_seconds") if top1 else None,
        "cost_usd": report.get("cost_usd", 0.0),
    }


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {}
    clear = [r for r in rows if r["correct_abstention"] is None]
    ambiguous = [r for r in rows if r["correct_abstention"] is not None]
    diagnosed = [r for r in rows if r["predicted"]]

    def rate(items, key):
        return round(sum(bool(r[key]) for r in items) / len(items), 3) if items else None

    times = [r["time_to_correct_diagnosis"] for r in rows if r["time_to_correct_diagnosis"] is not None]
    return {
        "runs": len(rows),
        "top1_accuracy": rate(clear, "top1_correct"),
        "top3_accuracy": rate(clear, "top3_correct"),
        "abstention_rate_on_clear": rate(clear, "abstained"),
        "correct_abstention_on_ambiguous": rate(ambiguous, "correct_abstention"),
        "unsupported_diagnosis_rate": rate(diagnosed, "unsupported_diagnosis"),
        "mean_tool_calls": round(sum(r["tool_calls"] for r in rows) / len(rows), 2),
        "mean_time_to_correct_diagnosis_s": round(sum(times) / len(times), 3) if times else None,
        "mean_cost_usd": round(sum(r["cost_usd"] for r in rows) / len(rows), 4),
    }
