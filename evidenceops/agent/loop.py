"""The investigation loop: model picks tools, harness runs them read-only.

The harness, not the model, owns every guarantee the grader relies on:

- Tools are the read-only functions in ``telemetry.TOOLS``; an unknown tool
  name or bad argument comes back to the model as an error result.
- Every tool result gets an evidence id. A submitted report that cites an id
  the model never received is sent back with the problems listed, up to
  ``max_report_retries`` times, then the run abstains.
- The tool budget is enforced here. Past it, tool calls are refused and the
  model is told to submit.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from evidenceops.agent import spec
from evidenceops.investigation import Hypothesis, Report
from evidenceops.telemetry import EvidenceStore, RunEvidence

RESULT_CHAR_LIMIT = 12_000


@dataclass
class ToolUse:
    id: str
    name: str
    input: Dict[str, Any]


@dataclass
class Turn:
    """One model response, reduced to what the loop needs."""

    content: Any                      # appended verbatim as the assistant message
    tool_uses: List[ToolUse]
    stop_reason: str
    text: str = ""
    usage: Dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    model: str = ""


class Model(Protocol):
    name: str

    def respond(self, system: str, tools: List[Dict[str, Any]], messages: List[Dict[str, Any]]) -> Turn: ...


def opening_message(incident: Dict[str, Any]) -> str:
    start, end = incident["telemetry_window"]
    return (
        f"Incident {incident['incident_id']}.\n\n"
        f"On-call report:\n{incident['report'].strip()}\n\n"
        f"Telemetry is available from {start} to {end}. Investigate and submit a report."
    )


def _render(result: Dict[str, Any]) -> str:
    text = json.dumps(result, separators=(",", ":"), default=str)
    if len(text) > RESULT_CHAR_LIMIT:
        text = text[:RESULT_CHAR_LIMIT] + f'..." [truncated {len(text) - RESULT_CHAR_LIMIT} chars; narrow the window or filter]'
    return text


def _error(tool_use_id: str, message: str) -> Dict[str, Any]:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": message, "is_error": True}


def investigate(
    run_dir: Path,
    model: Model,
    method: str,
    max_tool_calls: int = 20,
    max_turns: int = 30,
    max_report_retries: int = 2,
) -> Report:
    started = time.perf_counter()
    ev = RunEvidence(Path(run_dir) / "observed")
    store = EvidenceStore(ev)
    messages: List[Dict[str, Any]] = [{"role": "user", "content": opening_message(ev.incident)}]
    usage: Dict[str, int] = {}
    cost = 0.0
    served_by: List[str] = []
    submitted: Optional[Dict[str, Any]] = None
    rejected_reports = 0
    refused_calls = 0
    stop = ""

    for _ in range(max_turns):
        turn = model.respond(spec.SYSTEM_PROMPT, spec.TOOLS, messages)
        for k, v in turn.usage.items():
            usage[k] = usage.get(k, 0) + v
        cost += turn.cost_usd
        if turn.model and turn.model not in served_by:
            served_by.append(turn.model)
        messages.append({"role": "assistant", "content": turn.content})

        if turn.stop_reason == "refusal":
            stop = "the model declined to continue"
            break
        if not turn.tool_uses:
            if turn.stop_reason == "max_tokens":
                stop = "the model ran out of output tokens"
                break
            messages.append({"role": "user", "content": "Call submit_report to finish the investigation."})
            continue

        results: List[Dict[str, Any]] = []
        for use in turn.tool_uses:
            if use.name == "submit_report":
                problems = spec.validate_report(use.input, set(store.items))
                if problems and rejected_reports < max_report_retries:
                    rejected_reports += 1
                    results.append(_error(use.id, "Report rejected:\n- " + "\n- ".join(problems)))
                elif problems:
                    stop = "the report still cited unknown evidence after retries: " + "; ".join(problems)
                    results.append(_error(use.id, "Report rejected again; investigation ended."))
                else:
                    submitted = use.input
                    results.append({"type": "tool_result", "tool_use_id": use.id, "content": "Report accepted."})
            elif store.calls >= max_tool_calls:
                refused_calls += 1
                results.append(_error(use.id, f"Tool budget of {max_tool_calls} calls is used up. Call submit_report now."))
            else:
                try:
                    result = store.call(use.name, **use.input)
                except (KeyError, TypeError, ValueError) as exc:
                    results.append(_error(use.id, f"{type(exc).__name__}: {exc}"))
                    continue
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": _render(result)})
        messages.append({"role": "user", "content": results})
        if submitted is not None or stop:
            break
    else:
        stop = f"no accepted report after {max_turns} turns"

    elapsed = round(time.perf_counter() - started, 3)
    common = dict(
        method=method,
        incident_id=ev.incident["incident_id"],
        evidence=store.items,
        tool_calls=store.calls,
        elapsed_seconds=elapsed,
        cost_usd=round(cost, 6),
        input_tokens=usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
    )
    meta = {"model": model.name, "served_by": served_by, "usage": usage, "rejected_reports": rejected_reports, "refused_tool_calls": refused_calls}
    if submitted is None:
        return Report(hypotheses=[], abstained=True, abstain_reason=f"harness: {stop}", meta=meta, transcript=messages, **common)
    hypotheses = [
        Hypothesis(
            category=h["category"],
            statement=h["statement"],
            confidence=float(h["confidence"]),
            supporting=list(h["supporting"]),
            refuting=list(h.get("refuting") or []),
            component=h.get("component", ""),
        )
        for h in submitted.get("hypotheses") or []
    ]
    return Report(
        hypotheses=hypotheses,
        abstained=bool(submitted.get("abstain")),
        abstain_reason=submitted.get("abstain_reason", ""),
        timeline=submitted.get("timeline") or [],
        meta=meta,
        transcript=messages,
        **common,
    )
