"""Test an approved remediation in a disposable copy of the platform.

The experiment rebuilds the platform from scratch (volumes wiped), replays
the incident's scenario exactly as the original run did, applies the approved
changes once the incident is in full swing, keeps traffic running, and
measures whether the success rate comes back. The original run's directory
is only read from; results land in ``remediation/<method>-sandbox/``.

A remediation counts as verified only if both hold in the same experiment:

- the incident reproduced before the change (otherwise there was nothing to
  fix and the experiment is inconclusive), and
- after the change, the alerting metric recovers: for success-rate alerts,
  to within 5 points of the experiment's own baseline; for analytics alerts,
  the rollup's drift from the auction table falls back under a third of the
  scenario's alert threshold by the end of the recovery window.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Awaitable, Dict, List, Optional

import httpx

from evidenceops import loadgen
from evidenceops.faults import MIGRATIONS, DeployStep
from evidenceops.runner import ScenarioRun, _iso, _write_json
from evidenceops.scenario import parse_scenario
from evidenceops.stack import BACKEND_URL, Stack

RECOVERY_SECONDS = 45
RECOVERY_SETTLE_SECONDS = 5
RECOVERY_MARGIN = 0.05
SANDBOX_ADMIN = {"email": "sandbox-admin@example.com", "password": "sandbox-only-password", "role": "ADMIN"}


class RemediationExperiment(ScenarioRun):
    extra_seconds = RECOVERY_SECONDS

    def __init__(self, scenario, stack: Stack, changes: List[Dict[str, Any]], out_dir: Path, time_scale: float = 1.0):
        super().__init__(scenario, stack, time_scale, run_dir=out_dir)
        self.changes = changes
        self.remediation_times: List[float] = []
        self.admin_token = ""

    def _after_seed(self) -> None:
        resp = httpx.post(f"{BACKEND_URL}/api/v1/auth/register", json=SANDBOX_ADMIN, timeout=10)
        resp.raise_for_status()
        self.admin_token = resp.json()["access_token"]

    def _set_dsp_timeouts(self, dsps: List[str], value: int) -> None:
        headers = {"Authorization": f"Bearer {self.admin_token}"}
        rows = httpx.get(f"{BACKEND_URL}/api/v1/dsps", timeout=10).json()
        by_name = {r["name"].upper(): r["id"] for r in rows}
        for name in dsps:
            resp = httpx.patch(f"{BACKEND_URL}/api/v1/dsps/{by_name[name]}", json={"timeout_ms": value}, headers=headers, timeout=10)
            resp.raise_for_status()

    def _apply_remediation(self) -> None:
        started = time.time()
        settings = {c["setting"]: c["value"] for c in self.changes if c["kind"] == "deploy_setting"}
        for c in self.changes:
            if c["kind"] == "dsp_timeout_ms":
                self._set_dsp_timeouts(c["dsps"], c["value"])
            elif c["kind"] == "rollback_migration":
                self.stack.write_sql(MIGRATIONS[c["migration"]]["down"])
            elif c["kind"] == "skip_stuck_message":
                self.stack.kafka_skip_one(c["groups"])
        if settings:
            step = DeployStep(at=0, version=f"{self.deploy_state.version}-remediation", env=settings)
            self._apply_deploy(-1, step)
        self.remediation_times = [started, time.time()]
        self._event("remediation_applied", changes=self.changes)

    def _extra_tasks(self, incident_start: float, incident_end: float) -> List[Awaitable[None]]:
        async def remediate() -> None:
            await asyncio.sleep(max(0.0, incident_end - time.time()))
            await asyncio.to_thread(self._apply_remediation)

        return [remediate()]

    def _verify(self, outcomes, t_start: float, incident_start: float, t_end: float) -> Dict[str, Any]:
        s = self.scenario
        causal_done = max(self.step_times[i][1] for i in s.ground_truth.causal_steps)
        applied_start, applied_done = self.remediation_times
        windows = {
            "incident": [_iso(causal_done + s.verify.settle_seconds), _iso(applied_start)],
            "recovery": [_iso(applied_done + RECOVERY_SETTLE_SECONDS), _iso(t_end)],
        }
        if s.alert == "auction_success_rate":
            baseline = loadgen.success_rate(loadgen.window(outcomes, t_start, incident_start))
            incident = loadgen.success_rate(loadgen.window(outcomes, causal_done + s.verify.settle_seconds, applied_start))
            recovered = loadgen.success_rate(loadgen.window(outcomes, applied_done + RECOVERY_SETTLE_SECONDS, t_end))
            target = (baseline or 0) - RECOVERY_MARGIN
            reproduced = incident is not None and (baseline or 0) - incident >= s.verify.min_success_rate_drop
            recovered_ok = recovered is not None and recovered >= target
            metrics = {
                "baseline_success_rate": baseline,
                "incident_success_rate": incident,
                "recovered_success_rate": recovered,
                "recovery_target": round(target, 4),
            }
        else:
            incident = self._analytics_drift(causal_done, applied_start)
            # The last few samples: the rollup must have caught up (or been
            # corrected) by the end, not merely at some moment.
            tail = [x for x in self._analytics_samples() if x["ts"] >= applied_done + RECOVERY_SETTLE_SECONDS][-3:]
            sign = 1 if s.alert == "analytics_backlog" else -1
            recovered = max((sign * x["gap"] for x in tail), default=None)
            target = s.verify.min_analytics_gap / 3
            reproduced = incident is not None and incident >= s.verify.min_analytics_gap
            recovered_ok = recovered is not None and recovered < target
            metrics = {
                "baseline_analytics_drift": self._analytics_drift(t_start, incident_start),
                "incident_analytics_drift": incident,
                "recovered_analytics_drift": recovered,
                "recovery_target": f"drift below {target:g}",
            }
        return {
            "scenario_id": s.id,
            "alert": s.alert,
            **metrics,
            "windows": windows,
            "incident_reproduced": reproduced,
            "recovered": recovered_ok,
            "verdict": "verified" if reproduced and recovered_ok else ("not_fixed" if reproduced else "inconclusive"),
        }

    def _capture_platform_evidence(self) -> None:
        # The experiment's own telemetry is not needed for the verdict, but
        # the deployment log and traffic are kept for audit.
        return None


def run_experiment(run_dir: Path, proposal: Dict[str, Any], stack: Optional[Stack] = None, time_scale: float = 1.0) -> Dict[str, Any]:
    if proposal.get("status") != "approved":
        raise SystemExit("refusing to run a remediation that has not been approved")
    run_dir = Path(run_dir)
    scenario_raw = json.loads((run_dir / "ground_truth" / "scenario.json").read_text())
    scenario = parse_scenario(scenario_raw, run_dir / "ground_truth" / "scenario.json")
    out_dir = run_dir / "remediation" / f"{proposal['method']}-sandbox"
    stack = stack or Stack()
    experiment = RemediationExperiment(scenario, stack, proposal["resolved_changes"], out_dir, time_scale)
    try:
        verification = experiment.execute()
    finally:
        stack.down()
    result = {
        "run_id": proposal["run_id"],
        "method": proposal["method"],
        "purpose": proposal["purpose"],
        "hypothesis": proposal.get("hypothesis"),
        "changes": proposal["resolved_changes"],
        "approved_by": proposal["approved_by"],
        "proposal_digest": proposal["digest"],
        **verification,
    }
    _write_json(run_dir / "remediation" / f"{proposal['method']}.result.json", result)
    return result
