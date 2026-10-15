"""Run one incident scenario end to end and record everything.

Layout of a run directory::

    runs/<run_id>/
      observed/                 what an investigator may look at
        incident.json           the report, time range, and alert timeline
        deployments.jsonl       deployment log (CD history), incl. decoys
        logs/<service>.log      container logs with timestamps
        db/<table>.csv          read-only exports of auction/bid/... tables
        db/pg_stat_activity.samples.jsonl  connection states sampled every 5s
        metrics/scrapes.jsonl   periodic /metrics scrapes of the backend
      ground_truth/             graders only, never shown to an investigator
        ground_truth.json       root cause, causal + decoy steps, remediation
        timeline.jsonl          every harness action with timestamps
        traffic.jsonl           per-request outcomes from the load generator
        dsp_config_before.json / dsp_config_after.json
        verification.json       measured baseline vs incident success rate
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import httpx
import yaml

from evidenceops import loadgen
from evidenceops.faults import DeployState, DeployStep, DspConfigStep, read_env_file
from evidenceops.paths import ENV_EXAMPLE_FILE, ENV_FILE, RUNS_DIR
from evidenceops.scenario import Scenario
from evidenceops.stack import (
    BACKEND_URL,
    LOG_SERVICES,
    READ_QUERIES,
    SAMPLED_QUERIES,
    Stack,
    dsp_configs,
    set_dsp_config,
)

WARMUP_SECONDS = 5
METRICS_INTERVAL_SECONDS = 5


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="milliseconds")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


class ScenarioRun:
    def __init__(self, scenario: Scenario, stack: Stack, time_scale: float = 1.0):
        self.scenario = scenario
        self.stack = stack
        self.time_scale = time_scale
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = f"{stamp}-{scenario.id}"
        self.incident_id = "inc-" + hashlib.sha1(self.run_id.encode()).hexdigest()[:10]
        self.dir = RUNS_DIR / self.run_id
        self.observed = self.dir / "observed"
        self.truth = self.dir / "ground_truth"
        self.deploy_state: DeployState
        self.step_times: Dict[int, List[float]] = {}  # index -> [started, finished]

    # ------------------------------------------------------------ helpers

    def _event(self, kind: str, **fields: Any) -> None:
        _append_jsonl(self.truth / "timeline.jsonl", {"at": _iso(time.time()), "event": kind, **fields})

    def _scaled(self, seconds: float) -> float:
        return seconds * self.time_scale

    def _apply_deploy(self, index: int, step: DeployStep) -> None:
        started = time.time()
        record = self.deploy_state.apply(step)
        override = self.dir / "deploy.override.yml"
        override.write_text(yaml.safe_dump(self.deploy_state.compose_override(), sort_keys=True))
        self.stack.redeploy(override)
        self.stack.wait_healthy()
        finished = time.time()
        _append_jsonl(
            self.observed / "deployments.jsonl",
            {"started_at": _iso(started), "finished_at": _iso(finished), **record},
        )
        self._event("deploy", step=index, version=step.version, env=step.env)

    def _apply_dsp_config(self, index: int, step: DspConfigStep) -> None:
        current = dsp_configs()
        for name in step.dsps:
            set_dsp_config(name, {**current[name], **step.set})
        self._event("dsp_config", step=index, dsps=step.dsps, set=step.set)

    async def _run_step(self, index: int, step, incident_start: float) -> None:
        # Each step keeps its own schedule, so a slow deploy never delays the
        # steps after it.
        delay = incident_start + self._scaled(step.at) - time.time()
        if delay > 0:
            await asyncio.sleep(delay)
        started = time.time()
        if isinstance(step, DeployStep):
            await asyncio.to_thread(self._apply_deploy, index, step)
        else:
            await asyncio.to_thread(self._apply_dsp_config, index, step)
        self.step_times[index] = [started, time.time()]

    async def _run_steps(self, incident_start: float) -> None:
        await asyncio.gather(*(self._run_step(i, s, incident_start) for i, s in enumerate(self.scenario.steps)))

    async def _scrape_metrics(self, until: float) -> None:
        async with httpx.AsyncClient(timeout=3) as client:
            while time.time() < until:
                record: Dict[str, Any] = {"scraped_at": _iso(time.time())}
                try:
                    resp = await client.get(f"{BACKEND_URL}/metrics")
                    record["status"] = resp.status_code
                    record["body"] = resp.text
                except httpx.HTTPError as exc:
                    record["error"] = type(exc).__name__
                _append_jsonl(self.observed / "metrics" / "scrapes.jsonl", record)
                for name in SAMPLED_QUERIES:
                    sample: Dict[str, Any] = {"sampled_at": _iso(time.time())}
                    try:
                        sample["csv"] = await asyncio.to_thread(self.stack.export_query, name)
                    except Exception as exc:  # noqa: BLE001 - a missed sample is not fatal
                        sample["error"] = str(exc)[:200]
                    _append_jsonl(self.observed / "db" / f"{name}.samples.jsonl", sample)
                await asyncio.sleep(METRICS_INTERVAL_SECONDS)

    # ------------------------------------------------------------ main

    def execute(self) -> Dict[str, Any]:
        s = self.scenario
        self.dir.mkdir(parents=True, exist_ok=True)
        _write_json(self.truth / "scenario.json", s.raw)

        self._event("reset_start")
        self.stack.reset()
        ad_slot_id = self.stack.seed()
        self._event("seeded", ad_slot_id=ad_slot_id)

        # Settings missing from an older .env fall back to .env.example, which
        # matches the platform's built-in defaults.
        base_env = {**read_env_file(ENV_EXAMPLE_FILE.read_text()), **read_env_file(ENV_FILE.read_text())}
        self.deploy_state = DeployState(base_env=base_env, version=base_env.get("APP_VERSION", "1.0.0"))
        _append_jsonl(
            self.observed / "deployments.jsonl",
            {
                "started_at": _iso(time.time()),
                "finished_at": _iso(time.time()),
                "from_version": None,
                "to_version": self.deploy_state.version,
                "services": ["backend", "worker"],
                "config_changes": [],
            },
        )

        rps = s.traffic.rps
        asyncio.run(loadgen.run_load(f"{self.run_id}-warmup", ad_slot_id, rps, WARMUP_SECONDS, s.traffic.publishers))
        _write_json(self.truth / "dsp_config_before.json", dsp_configs())

        baseline_s = self._scaled(s.traffic.baseline_seconds)
        total_s = baseline_s + self._scaled(s.traffic.incident_seconds)
        t_start = time.time()
        incident_start = t_start + baseline_s
        self._event("traffic_start", rps=rps, baseline_seconds=baseline_s, total_seconds=total_s)

        async def drive() -> List[loadgen.RequestOutcome]:
            load = asyncio.create_task(
                loadgen.run_load(
                    self.run_id, ad_slot_id, rps, total_s, s.traffic.publishers, s.traffic.client_timeout_seconds
                )
            )
            await asyncio.gather(self._run_steps(incident_start), self._scrape_metrics(t_start + total_s))
            return await load

        outcomes = asyncio.run(drive())
        t_end = time.time()
        self._event("traffic_end", requests=len(outcomes))

        with open(self.truth / "traffic.jsonl", "w") as f:
            for o in outcomes:
                f.write(json.dumps(loadgen.to_dict(o)) + "\n")

        _write_json(self.truth / "dsp_config_after.json", dsp_configs())
        self._capture_platform_evidence()

        verification = self._verify(outcomes, t_start, incident_start, t_end)
        _write_json(self.truth / "verification.json", verification)
        _write_json(self.truth / "ground_truth.json", self._ground_truth())
        _write_json(self.observed / "incident.json", self._incident(outcomes, t_start, t_end))
        return verification

    def _capture_platform_evidence(self) -> None:
        for service in LOG_SERVICES:
            path = self.observed / "logs" / f"{service}.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.stack.logs(service))
        for name in READ_QUERIES:
            path = self.observed / "db" / f"{name}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.stack.export_query(name))

    def _verify(self, outcomes, t_start: float, incident_start: float, t_end: float) -> Dict[str, Any]:
        s = self.scenario
        # The incident window opens once every causal step has finished (a
        # deploy restarts the backend) plus a settle period, so the restart
        # blip itself is never counted as the incident.
        causal_done = max(self.step_times[i][1] for i in s.ground_truth.causal_steps)
        window_start = causal_done + s.verify.settle_seconds
        baseline = loadgen.success_rate(loadgen.window(outcomes, t_start, incident_start))
        incident = loadgen.success_rate(loadgen.window(outcomes, window_start, t_end))
        drop = (baseline or 0) - (incident or 0)
        checks = {
            "baseline_healthy": baseline is not None and baseline >= s.verify.min_baseline_success_rate,
            "incident_reproduced": incident is not None and drop >= s.verify.min_success_rate_drop,
        }
        return {
            "scenario_id": s.id,
            "run_id": self.run_id,
            "baseline_success_rate": baseline,
            "incident_success_rate": incident,
            "success_rate_drop": round(drop, 4),
            "incident_window": [_iso(window_start), _iso(t_end)],
            "thresholds": asdict(s.verify),
            "checks": checks,
            "passed": all(checks.values()),
        }

    def _ground_truth(self) -> Dict[str, Any]:
        gt = asdict(self.scenario.ground_truth)
        gt["scenario_id"] = self.scenario.id
        gt["ambiguous"] = self.scenario.ambiguous
        gt["step_times"] = {
            str(i): {"started": _iso(a), "finished": _iso(b)} for i, (a, b) in sorted(self.step_times.items())
        }
        return gt

    def _incident(self, outcomes, t_start: float, t_end: float) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "report": self.scenario.report,
            "telemetry_window": [_iso(t_start), _iso(t_end)],
            "services": ["backend", "worker", "dsp-simulator", "postgres", "redis", "kafka"],
            "alert": {
                "metric": "auction_success_rate",
                "definition": "share of publisher auction requests answered 201 with status COMPLETED within 2s",
                "timeline": [
                    {"window_start": _iso(t_start + row["offset_s"]), **{k: v for k, v in row.items() if k != "offset_s"}}
                    for row in loadgen.bucketed(outcomes, t_start)
                ],
            },
        }


def run_scenario(scenario: Scenario, stack: Stack, time_scale: float = 1.0) -> Dict[str, Any]:
    run = ScenarioRun(scenario, stack, time_scale)
    result = run.execute()
    result["run_dir"] = str(run.dir)
    return result
