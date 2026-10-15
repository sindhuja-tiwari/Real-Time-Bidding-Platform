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
        traces/spans.otlp.jsonl OpenTelemetry traces (OTLP JSON, one batch per line)
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
from typing import Any, Awaitable, Dict, List, Optional

import httpx
import yaml

from evidenceops import loadgen
from evidenceops.faults import (
    MIGRATIONS,
    POISON_TEMPLATES,
    DeployState,
    DeployStep,
    DspConfigStep,
    KafkaPublishStep,
    KafkaReplayStep,
    read_env_file,
)
from evidenceops.paths import ENV_EXAMPLE_FILE, ENV_FILE, RUNS_DIR
from evidenceops.scenario import Scenario
from evidenceops.stack import (
    BACKEND_URL,
    LOG_SERVICES,
    READ_QUERIES,
    SAMPLED_QUERIES,
    Stack,
    csv_rows,
    dsp_configs,
    set_dsp_config,
)

WARMUP_SECONDS = 5
METRICS_INTERVAL_SECONDS = 5
KAFKA_LAG_INTERVAL_SECONDS = 10


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
    # Seconds of traffic after the incident phase; subclasses use it for
    # remediation experiments.
    extra_seconds: float = 0.0

    def __init__(self, scenario: Scenario, stack: Stack, time_scale: float = 1.0, run_dir: Optional[Path] = None):
        self.scenario = scenario
        self.stack = stack
        self.time_scale = time_scale
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = f"{stamp}-{scenario.id}"
        self.incident_id = "inc-" + hashlib.sha1(self.run_id.encode()).hexdigest()[:10]
        self.dir = run_dir or RUNS_DIR / self.run_id
        self.observed = self.dir / "observed"
        self.truth = self.dir / "ground_truth"
        self.deploy_state: DeployState
        self.step_times: Dict[int, List[float]] = {}  # index -> [started, finished]
        # Logs of containers replaced by a deploy (compose only keeps the
        # current container's logs, so they are saved before each recreate).
        self.replaced_logs: Dict[str, List[str]] = {}

    # ------------------------------------------------------------ helpers

    def _event(self, kind: str, **fields: Any) -> None:
        _append_jsonl(self.truth / "timeline.jsonl", {"at": _iso(time.time()), "event": kind, **fields})

    def _scaled(self, seconds: float) -> float:
        return seconds * self.time_scale

    def _apply_deploy(self, index: int, step: DeployStep) -> None:
        started = time.time()
        record = self.deploy_state.apply(step)
        # Migrations run first, as a pre-deploy job would.
        for name in step.migrations:
            self.stack.write_sql(MIGRATIONS[name]["up"])
        override = self.dir / "deploy.override.yml"
        override.write_text(yaml.safe_dump(self.deploy_state.compose_override(), sort_keys=True))
        for service in ("backend", "worker"):
            self.replaced_logs.setdefault(service, []).append(self.stack.logs(service))
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

    def _apply_kafka_publish(self, index: int, step: KafkaPublishStep) -> None:
        template = POISON_TEMPLATES[step.template]
        lines = [(template % (i, i) if b"%d" in template else template).decode() for i in range(step.count)]
        self.stack.kafka_produce(lines)
        self._event("kafka_publish", step=index, template=step.template, count=step.count)

    def _apply_kafka_replay(self, index: int, step: KafkaReplayStep) -> None:
        to = datetime.fromtimestamp(time.time() - step.minutes * 60, tz=timezone.utc)
        self.stack.kafka_rewind(step.group, to.strftime("%Y-%m-%dT%H:%M:%S.000"))
        self._event("kafka_replay", step=index, group=step.group, minutes=step.minutes)

    async def _run_step(self, index: int, step, incident_start: float) -> None:
        # Each step keeps its own schedule, so a slow deploy never delays the
        # steps after it.
        delay = incident_start + self._scaled(step.at) - time.time()
        if delay > 0:
            await asyncio.sleep(delay)
        started = time.time()
        apply = {
            DeployStep: self._apply_deploy,
            DspConfigStep: self._apply_dsp_config,
            KafkaPublishStep: self._apply_kafka_publish,
            KafkaReplayStep: self._apply_kafka_replay,
        }[type(step)]
        await asyncio.to_thread(apply, index, step)
        self.step_times[index] = [started, time.time()]

    def _after_seed(self) -> None:
        """Hook: runs once the platform is seeded, before any traffic."""

    def _extra_tasks(self, incident_start: float, incident_end: float) -> List[Awaitable[None]]:
        """Hook: more coroutines to run alongside the scenario's steps."""
        return []

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

    async def _sample_kafka_lag(self, until: float) -> None:
        while time.time() < until:
            sample: Dict[str, Any] = {"sampled_at": _iso(time.time())}
            try:
                sample["text"] = await asyncio.to_thread(self.stack.kafka_lag)
            except Exception as exc:  # noqa: BLE001 - a missed sample is not fatal
                sample["error"] = str(exc)[:200]
            _append_jsonl(self.observed / "kafka" / "consumer_groups.samples.jsonl", sample)
            await asyncio.sleep(KAFKA_LAG_INTERVAL_SECONDS)

    # ------------------------------------------------------------ main

    def execute(self) -> Dict[str, Any]:
        s = self.scenario
        self.dir.mkdir(parents=True, exist_ok=True)
        _write_json(self.truth / "scenario.json", s.raw)

        self._event("reset_start")
        self.stack.reset()
        ad_slot_id = self.stack.seed()
        self._event("seeded", ad_slot_id=ad_slot_id)
        if s.history_auctions:
            self.stack.seed_history(s.history_auctions)
            self._event("history_seeded", auctions=s.history_auctions)
        self._after_seed()

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
        incident_s = self._scaled(s.traffic.incident_seconds)
        total_s = baseline_s + incident_s + self.extra_seconds
        t_start = time.time()
        incident_start = t_start + baseline_s
        self._event("traffic_start", rps=rps, baseline_seconds=baseline_s, total_seconds=total_s)

        async def drive() -> List[loadgen.RequestOutcome]:
            load = asyncio.create_task(
                loadgen.run_load(
                    self.run_id, ad_slot_id, rps, total_s, s.traffic.publishers, s.traffic.client_timeout_seconds
                )
            )
            await asyncio.gather(
                self._run_steps(incident_start),
                self._scrape_metrics(t_start + total_s),
                self._sample_kafka_lag(t_start + total_s),
                *self._extra_tasks(incident_start, incident_start + incident_s),
            )
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

    def _analytics_samples(self) -> List[Dict[str, Any]]:
        """(time, finished, rolled_up) from the sampled consistency query."""
        out = []
        path = self.observed / "db" / "analytics_consistency.samples.jsonl"
        if not path.exists():
            return out
        for line in path.read_text().splitlines():
            sample = json.loads(line)
            rows = csv_rows(sample.get("csv") or "")
            if rows:
                ts = datetime.fromisoformat(sample["sampled_at"]).timestamp()
                finished, rolled = int(rows[0]["finished_auctions"]), int(rows[0]["rolled_up"])
                out.append({"ts": ts, "finished": finished, "rolled_up": rolled, "gap": finished - rolled})
        return out

    def _analytics_drift(self, start: float, end: float) -> Optional[int]:
        """Largest drift in the alert's direction between start and end."""
        sign = 1 if self.scenario.alert == "analytics_backlog" else -1
        gaps = [sign * x["gap"] for x in self._analytics_samples() if start <= x["ts"] < end]
        return max(gaps) if gaps else None

    def _capture_platform_evidence(self) -> None:
        self.stack.collect_traces(self.observed / "traces" / "spans.otlp.jsonl")
        for service in LOG_SERVICES:
            path = self.observed / "logs" / f"{service}.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(self.replaced_logs.get(service, [])) + self.stack.logs(service))
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
        extra: Dict[str, Any] = {}
        if s.alert == "auction_success_rate":
            checks = {
                "baseline_healthy": baseline is not None and baseline >= s.verify.min_baseline_success_rate,
                "incident_reproduced": incident is not None and drop >= s.verify.min_success_rate_drop,
            }
        else:
            before = self._analytics_drift(t_start, incident_start)
            during = self._analytics_drift(causal_done, t_end)
            extra = {"baseline_analytics_drift": before, "incident_analytics_drift": during}
            checks = {
                "baseline_healthy": before is not None and before < s.verify.min_analytics_gap / 3,
                "incident_reproduced": during is not None and during >= s.verify.min_analytics_gap,
            }
        return {
            "scenario_id": s.id,
            "run_id": self.run_id,
            "alert": s.alert,
            **extra,
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
        if self.scenario.alert == "auction_success_rate":
            alert = {
                "metric": "auction_success_rate",
                "definition": "share of publisher auction requests answered 201 with status COMPLETED within 2s",
                "timeline": [
                    {"window_start": _iso(t_start + row["offset_s"]), **{k: v for k, v in row.items() if k != "offset_s"}}
                    for row in loadgen.bucketed(outcomes, t_start)
                ],
            }
        else:
            alert = {
                "metric": self.scenario.alert,
                "definition": (
                    "finished auctions (auction table) minus auctions counted by the analytics rollup "
                    "(auction_minute_rollup); near 0 when analytics keeps up"
                ),
                "timeline": [
                    {"sampled_at": _iso(x["ts"]), "finished_auctions": x["finished"],
                     "rolled_up": x["rolled_up"], "not_yet_counted": x["gap"]}
                    for x in self._analytics_samples() if t_start <= x["ts"] <= t_end
                ],
            }
        return {
            "incident_id": self.incident_id,
            "report": self.scenario.report,
            "telemetry_window": [_iso(t_start), _iso(t_end)],
            "services": ["backend", "worker", "dsp-simulator", "postgres", "redis", "kafka"],
            "alert": alert,
        }


def run_scenario(scenario: Scenario, stack: Stack, time_scale: float = 1.0) -> Dict[str, Any]:
    run = ScenarioRun(scenario, stack, time_scale)
    result = run.execute()
    result["run_dir"] = str(run.dir)
    return result
