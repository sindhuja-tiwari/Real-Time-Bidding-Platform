"""Allowlisted incident actions.

Scenarios describe faults declaratively; this module is the only code that
turns them into changes to the running stack, and it only knows two moves:

- ``deploy``: roll the backend and worker to a new version with changed
  settings. Only keys in ``DEPLOYABLE_SETTINGS`` can change. Every deploy is
  written to the deployment log, exactly as a CD system would record it, so
  investigators see the change (and any harmless decoy changes riding along).
  A deploy can also ship schema migrations, by name, from ``MIGRATIONS``.
- ``dsp_config``: change how the external DSP simulator behaves, through its
  admin API. Only fields in ``DSP_FIELDS`` can change. This models a
  third-party bidder degrading; nothing about it lands in the platform's own
  deployment log.
- ``kafka_publish``: publish one of the fixed ``POISON_TEMPLATES`` to the
  auction-events topic, the way a buggy or foreign producer would.
- ``kafka_replay``: rewind a consumer group's offsets by some minutes (worker
  stopped and restarted around it), the way an operator replays a topic.

A scenario may also ask for ``setup.history_auctions``: old auctions written
before traffic starts, so tables are big enough for a missing index to matter.

There is deliberately no "run a command" action, and no SQL or payload text
ever comes from a scenario file: only names that select fixed code here.
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


# Schema migrations a deploy may ship. Names look like real migration files;
# the SQL is fixed here. "down" is what a rollback runs.
MIGRATIONS: Dict[str, Dict[str, str]] = {
    "0004_auction_request_id_collation": {
        # Rebuilds request_id for a collation change and forgets the unique
        # constraint, which was also the index behind the idempotency lookup.
        "up": "ALTER TABLE auction DROP CONSTRAINT IF EXISTS auction_request_id_key",
        "down": "ALTER TABLE auction ADD CONSTRAINT auction_request_id_key UNIQUE (request_id)",
    },
    "0004_bid_created_at_index": {
        "up": "CREATE INDEX IF NOT EXISTS idx_bid_created_at ON bid(created_at)",
        "down": "DROP INDEX IF EXISTS idx_bid_created_at",
    },
    "0005_campaign_bid_floor_check": {
        "up": "ALTER TABLE campaign ADD CONSTRAINT ck_campaign_bid_floor_nonneg CHECK (bid_floor >= 0) NOT VALID",
        "down": "ALTER TABLE campaign DROP CONSTRAINT IF EXISTS ck_campaign_bid_floor_nonneg",
    },
}

# Messages a poison-message scenario can publish to auction-events.
POISON_TEMPLATES: Dict[str, bytes] = {
    # Truncated JSON: fails in the consumer's deserializer, before any retry
    # or dead-letter logic runs.
    "truncated_json": b'{"event_id": "evt_legacy", "event_type": "AUCTION_COMPLETED", "auction_id": ',
    # Valid JSON from an older producer with no timestamp: the analytics
    # handler raises, retries with backoff, then dead-letters it.
    "missing_timestamp": (
        b'{"event_id": "evt_legacy_%d", "event_type": "AUCTION_COMPLETED", '
        b'"auction_id": "legacy-%d", "status": "COMPLETED", "latency_ms": 90}'
    ),
}

REPLAYABLE_GROUPS = frozenset({"analytics-consumer", "audit-consumer", "budget-consumer"})
MAX_HISTORY_AUCTIONS = 5_000_000


@dataclass
class DeployStep:
    at: float
    version: str
    env: Dict[str, str]
    migrations: List[str] = field(default_factory=list)
    action: str = field(default="deploy", init=False)


@dataclass
class KafkaPublishStep:
    at: float
    template: str
    count: int = 1
    action: str = field(default="kafka_publish", init=False)


@dataclass
class KafkaReplayStep:
    at: float
    group: str
    minutes: float
    action: str = field(default="kafka_replay", init=False)


@dataclass
class DspConfigStep:
    at: float
    dsps: List[str]
    set: Dict[str, Any]
    action: str = field(default="dsp_config", init=False)


Step = Union[DeployStep, DspConfigStep, KafkaPublishStep, KafkaReplayStep]


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
        migrations = [str(m) for m in data.get("migrations") or []]
        unknown = sorted(set(migrations) - set(MIGRATIONS))
        if unknown:
            raise FaultError(f"{where}: unknown migrations: {unknown}")
        if not env and not migrations:
            raise FaultError(f"{where}: a deploy must change settings or ship a migration")
        return DeployStep(at=at, version=version, env=env, migrations=migrations)
    if action == "kafka_publish":
        template = str(data.get("template") or "")
        if template not in POISON_TEMPLATES:
            raise FaultError(f"{where}: template must be one of {sorted(POISON_TEMPLATES)}")
        count = int(data.get("count", 1))
        if not 1 <= count <= 50:
            raise FaultError(f"{where}: count must be 1..50")
        return KafkaPublishStep(at=at, template=template, count=count)
    if action == "kafka_replay":
        group = str(data.get("group") or "")
        if group not in REPLAYABLE_GROUPS:
            raise FaultError(f"{where}: group must be one of {sorted(REPLAYABLE_GROUPS)}")
        minutes = float(data.get("minutes", 0))
        if not 0 < minutes <= 30:
            raise FaultError(f"{where}: minutes must be in (0, 30]")
        return KafkaReplayStep(at=at, group=group, minutes=minutes)
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
            "migrations": list(step.migrations),
        }
        self.overrides.update(step.env)
        self.version = step.version
        return record

    def compose_override(self) -> Dict[str, Any]:
        env = dict(self.overrides)
        env["APP_VERSION"] = self.version
        return {"services": {svc: {"environment": env} for svc in ("backend", "worker")}}
