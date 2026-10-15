"""Allowlisted incident actions.

Scenarios describe faults declaratively; this module is the only code that
turns them into changes to the running stack, and it only knows two moves:

- ``deploy``: roll the backend and worker to a new version with changed
  settings. Only keys in ``DEPLOYABLE_SETTINGS`` can change. Every deploy is
  written to the deployment log, exactly as a CD system would record it, so
  investigators see the change (and any harmless decoy changes riding along).
- ``dsp_config``: change how the external DSP simulator behaves, through its
  admin API. Only fields in ``DSP_FIELDS`` can change. This models a
  third-party bidder degrading; nothing about it lands in the platform's own
  deployment log.

There is deliberately no "run a command" action.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Union

DEPLOYABLE_SETTINGS = frozenset(
    {
        "AUCTION_GLOBAL_TIMEOUT_MS",
        "AUCTION_DEFAULT_TYPE",
        "DSP_DEFAULT_TIMEOUT_MS",
        "REDIS_CACHE_TTL_SECONDS",
        "RATE_LIMIT_PUBLISHER_PER_MIN",
        "RATE_LIMIT_ADMIN_PER_MIN",
        "RATE_LIMIT_DSP_PER_MIN",
        "EVENT_MAX_RETRIES",
        "EVENT_RETRY_BASE_SECONDS",
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT_SECONDS",
    }
)

DSP_NAMES = frozenset({"dsp-a", "dsp-b", "dsp-c", "dsp-d", "dsp-e"})

DSP_FIELDS = frozenset(
    {
        "base_bid",
        "latency_ms",
        "latency_jitter_ms",
        "failure_probability",
        "timeout_probability",
        "quality_score",
    }
)


class FaultError(ValueError):
    pass


@dataclass
class DeployStep:
    at: float
    version: str
    env: Dict[str, str]
    action: str = field(default="deploy", init=False)


@dataclass
class DspConfigStep:
    at: float
    dsps: List[str]
    set: Dict[str, Any]
    action: str = field(default="dsp_config", init=False)


Step = Union[DeployStep, DspConfigStep]


def parse_step(data: Dict[str, Any], where: str) -> Step:
    action = data.get("action")
    at = float(data.get("at", 0))
    if action == "deploy":
        version = str(data.get("version") or "")
        if not version:
            raise FaultError(f"{where}: deploy needs a version")
        env = {str(k): str(v) for k, v in (data.get("env") or {}).items()}
        bad = sorted(set(env) - DEPLOYABLE_SETTINGS)
        if bad:
            raise FaultError(f"{where}: settings not deployable: {bad}")
        return DeployStep(at=at, version=version, env=env)
    if action == "dsp_config":
        dsps = [str(d) for d in data.get("dsps") or []]
        if not dsps or set(dsps) - DSP_NAMES:
            raise FaultError(f"{where}: dsps must be a non-empty subset of {sorted(DSP_NAMES)}")
        changes = dict(data.get("set") or {})
        bad = sorted(set(changes) - DSP_FIELDS)
        if not changes or bad:
            raise FaultError(f"{where}: dsp_config 'set' must use fields from {sorted(DSP_FIELDS)}")
        return DspConfigStep(at=at, dsps=dsps, set=changes)
    raise FaultError(f"{where}: unknown action '{action}'")


def read_env_file(text: str) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


@dataclass
class DeployState:
    """Settings currently deployed to backend + worker, layered over .env."""

    base_env: Dict[str, str]
    version: str
    overrides: Dict[str, str] = field(default_factory=dict)

    def current(self, key: str) -> str:
        return self.overrides.get(key, self.base_env.get(key, ""))

    def apply(self, step: DeployStep) -> Dict[str, Any]:
        """Apply a deploy and return its deployment-log record."""
        changes = [
            {"setting": k, "from": self.current(k), "to": v}
            for k, v in sorted(step.env.items())
            if self.current(k) != v
        ]
        record = {
            "from_version": self.version,
            "to_version": step.version,
            "services": ["backend", "worker"],
            "config_changes": changes,
        }
        self.overrides.update(step.env)
        self.version = step.version
        return record

    def compose_override(self) -> Dict[str, Any]:
        env = dict(self.overrides)
        env["APP_VERSION"] = self.version
        return {"services": {svc: {"environment": env} for svc in ("backend", "worker")}}
