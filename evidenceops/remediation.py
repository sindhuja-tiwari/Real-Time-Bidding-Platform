"""Remediation proposals: typed, allowlisted changes behind an approval gate.

A remediation is a list of changes, each one of three kinds:

- ``deploy_setting``: set an allowlisted platform setting (redeploys
  backend and worker), e.g. ``AUCTION_GLOBAL_TIMEOUT_MS`` to ``180``.
- ``rollback_setting``: put a setting back to its value before the most
  recent deploy that changed it (resolved against the run's deployment log).
- ``dsp_timeout_ms``: set the per-DSP timeout on named DSP rows through the
  platform's admin API.

Nothing else can be expressed, so there is nothing to sanitize: a proposal
that does not parse into these kinds is rejected, never "best-effort" run.

Flow: ``propose`` writes ``remediation/<method>.proposal.json`` with status
``awaiting_approval``. ``approve`` re-validates that exact file, records who
approved it and the proposal's hash, and only then does the sandbox run it.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from evidenceops.faults import DEPLOYABLE_SETTINGS
from evidenceops.telemetry import RunEvidence

DSP_ROW_NAMES = frozenset({"DSP-A", "DSP-B", "DSP-C", "DSP-D", "DSP-E"})
TIMEOUT_RANGE_MS = (10, 2000)

# Numeric bounds for settings a remediation may set. Wider than any sane
# value, narrow enough that a typo cannot take the sandbox down for good.
SETTING_BOUNDS = {
    "AUCTION_GLOBAL_TIMEOUT_MS": (10, 2000),
    "DSP_DEFAULT_TIMEOUT_MS": (10, 2000),
    "REDIS_CACHE_TTL_SECONDS": (1, 3600),
    "RATE_LIMIT_PUBLISHER_PER_MIN": (1, 1_000_000),
    "RATE_LIMIT_ADMIN_PER_MIN": (1, 1_000_000),
    "RATE_LIMIT_DSP_PER_MIN": (1, 1_000_000),
    "EVENT_MAX_RETRIES": (0, 20),
    "EVENT_RETRY_BASE_SECONDS": (0, 60),
    "DB_POOL_SIZE": (1, 100),
    "DB_MAX_OVERFLOW": (0, 100),
    "DB_POOL_TIMEOUT_SECONDS": (1, 120),
}

# Which root-cause category a setting can plausibly cause; used to pick what
# to roll back for a hypothesis.
SETTING_CATEGORY = {
    "AUCTION_GLOBAL_TIMEOUT_MS": "config_regression",
    "DSP_DEFAULT_TIMEOUT_MS": "config_regression",
    "DB_POOL_SIZE": "db_pool_exhaustion",
    "DB_MAX_OVERFLOW": "db_pool_exhaustion",
    "DB_POOL_TIMEOUT_SECONDS": "db_pool_exhaustion",
}

CHANGE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["deploy_setting", "rollback_setting", "dsp_timeout_ms"]},
        "setting": {"type": "string", "description": "for deploy_setting and rollback_setting"},
        "value": {"type": "string", "description": "for deploy_setting and dsp_timeout_ms"},
        "dsps": {"type": "array", "items": {"type": "string"}, "description": "DSP names, for dsp_timeout_ms"},
    },
    "required": ["kind"],
    "additionalProperties": False,
}


class InvalidChange(ValueError):
    pass


def parse_change(raw: Dict[str, Any]) -> Dict[str, Any]:
    kind = raw.get("kind")
    if kind in ("deploy_setting", "rollback_setting"):
        setting = raw.get("setting")
        if setting not in DEPLOYABLE_SETTINGS:
            raise InvalidChange(f"{setting!r} is not a deployable setting")
        if kind == "rollback_setting":
            return {"kind": kind, "setting": setting}
        lo, hi = SETTING_BOUNDS[setting]
        try:
            number = float(raw.get("value"))
        except (TypeError, ValueError):
            raise InvalidChange(f"{setting} value {raw.get('value')!r} is not a number") from None
        if not lo <= number <= hi:
            raise InvalidChange(f"{setting}={number:g} is outside {lo}..{hi}")
        value = str(int(number)) if number == int(number) and "." not in str(raw.get("value")) else str(number)
        return {"kind": kind, "setting": setting, "value": value}
    if kind == "dsp_timeout_ms":
        dsps = sorted({str(d).upper() for d in raw.get("dsps") or []})
        if not dsps or not set(dsps) <= DSP_ROW_NAMES:
            raise InvalidChange(f"dsps must be a non-empty subset of {sorted(DSP_ROW_NAMES)}")
        try:
            value = int(float(raw.get("value")))
        except (TypeError, ValueError):
            raise InvalidChange(f"timeout {raw.get('value')!r} is not a number") from None
        if not TIMEOUT_RANGE_MS[0] <= value <= TIMEOUT_RANGE_MS[1]:
            raise InvalidChange(f"timeout {value}ms is outside {TIMEOUT_RANGE_MS[0]}..{TIMEOUT_RANGE_MS[1]}ms")
        return {"kind": kind, "dsps": dsps, "value": value}
    raise InvalidChange(f"unknown change kind {kind!r}")


def resolve(changes: List[Dict[str, Any]], ev: RunEvidence) -> List[Dict[str, Any]]:
    """Turn rollbacks into concrete settings using the run's deployment log."""
    out = []
    for change in changes:
        if change["kind"] != "rollback_setting":
            out.append(change)
            continue
        previous = None
        for deploy in reversed(ev.deployments):
            for c in deploy.get("config_changes") or []:
                if c["setting"] == change["setting"]:
                    previous = c["from"]
                    break
            if previous is not None:
                break
        if previous is None:
            raise InvalidChange(f"no deploy in this run changed {change['setting']}, so there is nothing to roll back")
        out.append({"kind": "deploy_setting", "setting": change["setting"], "value": str(previous), "rolled_back": True})
    return out


def _recent_changes(ev: RunEvidence) -> Dict[str, Dict[str, Any]]:
    changed: Dict[str, Dict[str, Any]] = {}
    for d in ev.deployments:
        for c in d.get("config_changes") or []:
            changed[c["setting"]] = c
    return changed


def plan(report: Dict[str, Any], ev: RunEvidence) -> Optional[Dict[str, Any]]:
    """A proposal from a report: the model's own, else one derived by rule.

    When the report abstained, the proposal is an experiment rather than a
    fix: roll back what the suspect deploy changed and see whether the
    platform recovers. Either outcome tells you something the telemetry
    could not.
    """
    if report.get("remediation"):
        raw = report["remediation"]
        return {
            "source": "investigator",
            "purpose": "experiment" if report.get("abstained") else "fix",
            "changes": [parse_change(c) for c in raw.get("changes") or []],
            "rationale": raw.get("rationale", ""),
        }
    hyps = report.get("hypotheses") or []
    changed = _recent_changes(ev)
    if report.get("abstained"):
        suspects = [s for s in changed if s in SETTING_CATEGORY]
        if not suspects:
            return None
        return {
            "source": "planner",
            "purpose": "experiment",
            "changes": [parse_change({"kind": "rollback_setting", "setting": s}) for s in sorted(suspects)],
            "rationale": "the investigation abstained; rolling back the suspect deploy's risky settings shows "
            "whether that deploy is a sufficient cause",
        }
    if not hyps:
        return None
    top = hyps[0]
    category = top["category"]
    if category in ("config_regression", "db_pool_exhaustion"):
        targets = sorted(s for s in changed if SETTING_CATEGORY.get(s) == category)
        if not targets and top.get("component") in changed:
            targets = [top["component"]]
        if not targets:
            return None
        return {
            "source": "planner",
            "purpose": "fix",
            "changes": [parse_change({"kind": "rollback_setting", "setting": s}) for s in targets],
            "rationale": f"roll back the {category} settings changed by the suspect deploy: {', '.join(targets)}",
        }
    if category == "external_dsp_latency":
        named = sorted(d for d in DSP_ROW_NAMES if d in (top.get("component") or "") + " " + top.get("statement", ""))
        dsps = named or sorted(DSP_ROW_NAMES)
        return {
            "source": "planner",
            "purpose": "fix",
            "changes": [
                parse_change({"kind": "deploy_setting", "setting": "AUCTION_GLOBAL_TIMEOUT_MS", "value": "200"}),
                parse_change({"kind": "dsp_timeout_ms", "dsps": dsps, "value": "200"}),
            ],
            "rationale": f"give the slowed bidders ({', '.join(dsps)}) room: per-DSP timeout and global deadline to 200ms",
        }
    return None


def _digest(proposal: Dict[str, Any]) -> str:
    body = {k: proposal[k] for k in ("run_id", "method", "changes")}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def proposal_path(run_dir: Path, method: str) -> Path:
    return Path(run_dir) / "remediation" / f"{method}.proposal.json"


def propose(run_dir: Path, method: str) -> Dict[str, Any]:
    run_dir = Path(run_dir)
    report = json.loads((run_dir / "investigations" / f"{method}.json").read_text())
    ev = RunEvidence(run_dir / "observed")
    planned = plan(report, ev)
    if planned is None:
        raise SystemExit(f"{method} gives nothing to remediate for {run_dir.name}")
    proposal = {
        "run_id": run_dir.name,
        "method": method,
        "hypothesis": (report.get("hypotheses") or [{}])[0].get("category"),
        **planned,
        "resolved_changes": resolve(planned["changes"], ev),
        "status": "awaiting_approval",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    proposal["digest"] = _digest(proposal)
    path = proposal_path(run_dir, method)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposal, indent=2) + "\n")
    return proposal


def approve(run_dir: Path, method: str, approver: str) -> Dict[str, Any]:
    """Validate the saved proposal again and mark it approved by ``approver``."""
    if not approver.strip():
        raise SystemExit("approval needs a name: --approve 'Your Name'")
    path = proposal_path(run_dir, method)
    if not path.exists():
        raise SystemExit(f"no proposal at {path}; run 'remediate' without --approve first")
    proposal = json.loads(path.read_text())
    changes = [parse_change(c) for c in proposal["changes"]]
    if changes != proposal["changes"] or _digest(proposal) != proposal["digest"]:
        raise SystemExit(f"{path} changed after it was proposed; propose again")
    proposal["resolved_changes"] = resolve(changes, RunEvidence(Path(run_dir) / "observed"))
    proposal.update(
        status="approved",
        approved_by=approver.strip(),
        approved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        approved_from=os.environ.get("USER", ""),
    )
    path.write_text(json.dumps(proposal, indent=2) + "\n")
    return proposal
