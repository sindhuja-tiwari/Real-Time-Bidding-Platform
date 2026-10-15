"""Thin, fixed-argument wrapper around Docker Compose for the harness.

Every docker invocation the harness can make is a method here with a fixed
argv (no shell, no string interpolation into commands). Database reads go
through ``export_query`` with a name from ``READ_QUERIES``, run as a
read-only transaction.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from evidenceops.paths import (
    BASE_COMPOSE_FILE,
    ENV_EXAMPLE_FILE,
    ENV_FILE,
    OVERLAY_COMPOSE_FILE,
    REPO_ROOT,
    TELEMETRY_DIR,
)

PROJECT_NAME = "rtb-evidenceops"
PLATFORM_SERVICES = ["postgres", "redis", "kafka", "dsp-simulator", "otel-collector", "backend", "worker"]
# Budget-driven NO_BIDs would otherwise appear partway through a long run
# and contaminate every scenario; budget exhaustion gets its own scenario.
SEED_CAMPAIGN_BUDGET = 1_000_000
LOG_SERVICES = ["backend", "worker", "dsp-simulator", "postgres", "kafka", "redis"]

BACKEND_URL = os.getenv("EVIDENCEOPS_BACKEND_URL", "http://localhost:8000")
DSP_SIM_URL = os.getenv("EVIDENCEOPS_DSP_SIM_URL", "http://localhost:9000")

# Exported per run for investigators. Each runs inside a READ ONLY
# transaction (see export_query).
READ_QUERIES: Dict[str, str] = {
    # Only this run's auctions: missing-index scenarios add millions of old rows.
    "auctions": (
        "SELECT id, request_id, status, duration_ms, started_at, completed_at, winning_bid_id "
        "FROM auction WHERE started_at > now() - interval '1 hour' ORDER BY started_at"
    ),
    "bids": (
        "SELECT b.id, b.auction_id, d.name AS dsp_name, b.campaign_id, b.amount, "
        "b.response_time_ms, b.status, b.created_at "
        "FROM bid b JOIN dsp d ON d.id = b.dsp_id ORDER BY b.created_at"
    ),
    "dsps": "SELECT id, name, endpoint, timeout_ms, status FROM dsp ORDER BY name",
    "campaigns": (
        "SELECT id, name, status, daily_budget, remaining_budget, bid_floor FROM campaign ORDER BY name"
    ),
    "indexes": "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1, 2",
}

# Sampled repeatedly during a run (point-in-time views are useless after it).
SAMPLED_QUERIES: Dict[str, str] = {
    "pg_stat_activity": (
        "SELECT state, wait_event_type, wait_event, count(*) AS connections "
        "FROM pg_stat_activity WHERE datname = 'rtb' AND pid <> pg_backend_pid() "
        "GROUP BY 1, 2, 3 ORDER BY 4 DESC"
    ),
    # Statements running right now, with how long each has been running.
    "active_queries": (
        "SELECT round(extract(epoch FROM now() - query_start) * 1000) AS running_ms, "
        "regexp_replace(left(query, 400), '\\s+', ' ', 'g') AS query "
        "FROM pg_stat_activity WHERE datname = 'rtb' AND state = 'active' AND pid <> pg_backend_pid()"
    ),
    # Cumulative scan counters per table; differences between samples give scan rates.
    "table_scans": (
        "SELECT relname, seq_scan, seq_tup_read, coalesce(idx_scan, 0) AS idx_scan, n_live_tup "
        "FROM pg_stat_user_tables ORDER BY relname"
    ),
    # Finished auctions vs auctions counted by the analytics rollup.
    "analytics_consistency": (
        "SELECT (SELECT count(*) FROM auction WHERE status IN ('COMPLETED', 'NO_BID') "
        "AND started_at > now() - interval '1 hour') AS finished_auctions, "
        "(SELECT coalesce(sum(total_auctions), 0) FROM auction_minute_rollup) AS rolled_up"
    ),
}

KAFKA_BIN = "/opt/kafka/bin"
KAFKA_TOPIC = "auction-events"
WORKER_GROUPS = ["analytics-consumer", "audit-consumer", "budget-consumer"]


class StackError(RuntimeError):
    pass


class Stack:
    def __init__(self, extra_compose_files: Optional[List[Path]] = None):
        # EVIDENCEOPS_EXTRA_COMPOSE lets a machine layer its own overrides
        # (e.g. prebuilt images) without editing the harness.
        extra = [Path(p) for p in os.getenv("EVIDENCEOPS_EXTRA_COMPOSE", "").split(os.pathsep) if p]
        self.compose_files = [BASE_COMPOSE_FILE, OVERLAY_COMPOSE_FILE, *extra, *(extra_compose_files or [])]
        self.deploy_override: Optional[Path] = None

    # ------------------------------------------------------------ plumbing

    def _argv(self, *args: str) -> List[str]:
        files = list(self.compose_files)
        if self.deploy_override is not None:
            files.append(self.deploy_override)
        argv = ["docker", "compose", "-p", PROJECT_NAME]
        for f in files:
            argv += ["-f", str(f)]
        return argv + list(args)

    def _run(
        self, *args: str, timeout: float = 600, check: bool = True, input_text: Optional[str] = None
    ) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            self._argv(*args), cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout, input=input_text
        )
        if check and proc.returncode != 0:
            raise StackError(f"docker compose {' '.join(args)} failed:\n{proc.stderr[-2000:]}")
        return proc

    # ------------------------------------------------------------ lifecycle

    @staticmethod
    def ensure_env_file() -> None:
        if not ENV_FILE.exists():
            shutil.copy(ENV_EXAMPLE_FILE, ENV_FILE)

    def reset(self) -> None:
        """Tear down (including volumes) and start a fresh platform."""
        self.ensure_env_file()
        self.deploy_override = None
        self._run("down", "-v", "--remove-orphans", timeout=300)
        shutil.rmtree(TELEMETRY_DIR, ignore_errors=True)
        TELEMETRY_DIR.mkdir(parents=True)
        self._run("up", "-d", "--build", *PLATFORM_SERVICES, timeout=1200)
        self.wait_healthy()

    def down(self) -> None:
        self._run("down", "-v", "--remove-orphans", timeout=300, check=False)

    def redeploy(self, override_file: Path) -> None:
        """Recreate backend + worker with the given environment override."""
        self.deploy_override = override_file
        # Short stop timeout: uvicorn otherwise waits out keep-alive publisher
        # connections, turning a deploy into a ~10s outage.
        self._run("up", "-d", "--no-deps", "--force-recreate", "-t", "2", "backend", "worker", timeout=300)

    def wait_healthy(self, timeout: float = 180) -> None:
        deadline = time.monotonic() + timeout
        urls = [f"{BACKEND_URL}/health", f"{DSP_SIM_URL}/health"]
        while time.monotonic() < deadline:
            try:
                if all(httpx.get(u, timeout=2).status_code == 200 for u in urls):
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
        raise StackError(f"platform not healthy after {timeout}s ({urls})")

    def seed(self) -> str:
        """Seed demo data; returns the ad_slot_id auctions should target."""
        proc = self._run(
            "exec", "-T", "-e", f"SEED_CAMPAIGN_BUDGET={SEED_CAMPAIGN_BUDGET}",
            "backend", "python", "-m", "app.seed",
            timeout=120,
        )
        match = re.search(r"ad_slot_id = ([0-9a-f-]{36})", proc.stdout)
        if not match:
            raise StackError(f"could not find ad_slot_id in seed output:\n{proc.stdout}")
        return match.group(1)

    # ------------------------------------------------------------ evidence

    def collect_traces(self, dest: Path, settle_seconds: float = 4.0) -> None:
        """Copy the collector's trace file once in-flight batches have landed."""
        time.sleep(settle_seconds)
        source = TELEMETRY_DIR / "traces.jsonl"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            shutil.copy(source, dest)
        else:
            dest.write_text("")

    def logs(self, service: str) -> str:
        if service not in LOG_SERVICES:
            raise StackError(f"logs not collected for '{service}'")
        return self._run("logs", "--no-color", "--timestamps", service, timeout=120).stdout

    def export_query(self, name: str) -> str:
        """Run a named, read-only query and return CSV."""
        sql = {**READ_QUERIES, **SAMPLED_QUERIES}[name]
        copy = f"COPY ({sql}) TO STDOUT WITH CSV HEADER"
        proc = self._run(
            "exec", "-T", "-e", "PGOPTIONS=-c default_transaction_read_only=on",
            "postgres", "psql", "-U", "rtb", "-d", "rtb", "-v", "ON_ERROR_STOP=1", "-c", copy,
            timeout=120,
        )
        return proc.stdout


    # ------------------------------------------------------------ fault actions
    # Each takes only values chosen from allowlists in faults.py.

    def write_sql(self, sql: str, timeout: float = 600) -> None:
        """Run fixed SQL from faults.py (migrations, history seeding)."""
        self._run(
            "exec", "-T", "postgres", "psql", "-U", "rtb", "-d", "rtb", "-v", "ON_ERROR_STOP=1", "-c", sql,
            timeout=timeout,
        )

    def seed_history(self, auctions: int) -> None:
        """Write old, completed auctions so the auction table is production-sized."""
        self.write_sql(
            "INSERT INTO auction (request_id, ad_slot_id, started_at, completed_at, duration_ms, status) "
            "SELECT 'hist-' || g, (SELECT id FROM ad_slot ORDER BY id LIMIT 1), "
            "now() - interval '30 days' + g * interval '1 second', "
            "now() - interval '30 days' + g * interval '1 second' + interval '110 milliseconds', 110, 'COMPLETED' "
            f"FROM generate_series(1, {int(auctions)}) g",
            timeout=1800,
        )
        self.write_sql("VACUUM ANALYZE auction", timeout=1800)

    def kafka_produce(self, lines: List[str]) -> None:
        self._run(
            "exec", "-T", "kafka", f"{KAFKA_BIN}/kafka-console-producer.sh",
            "--bootstrap-server", "localhost:9092", "--topic", KAFKA_TOPIC,
            timeout=120, input_text="\n".join(lines) + "\n",
        )

    def _reset_offsets(self, group: str, *how: str, wait_seconds: float = 60) -> None:
        """Reset a stopped group's offsets, waiting for its old members to time out.

        A worker that crashed rather than shut down leaves its members in the
        group until the session times out, and Kafka refuses resets until then.
        """
        deadline = time.monotonic() + wait_seconds
        while True:
            proc = self._run(
                "exec", "-T", "kafka", f"{KAFKA_BIN}/kafka-consumer-groups.sh",
                "--bootstrap-server", "localhost:9092", "--group", group, "--topic", KAFKA_TOPIC,
                "--reset-offsets", *how, "--execute",
                timeout=120, check=False,
            )
            output = proc.stdout + proc.stderr
            if proc.returncode == 0 and "Error" not in output:
                return
            if time.monotonic() > deadline:
                raise StackError(f"could not reset offsets for {group}:\n{output[-1000:]}")
            time.sleep(3)

    def kafka_rewind(self, group: str, to_datetime: str) -> None:
        """Stop the worker, move a group's offsets back to a time, start it again."""
        self._run("stop", "-t", "5", "worker", timeout=120)
        try:
            self._reset_offsets(group, "--to-datetime", to_datetime)
        finally:
            self._run("start", "worker", timeout=120)

    def kafka_skip_one(self, groups: List[str]) -> None:
        """Remediation: move each group one message past where it is stuck."""
        self._run("stop", "-t", "5", "worker", timeout=120)
        try:
            for group in groups:
                self._reset_offsets(group, "--shift-by", "1")
        finally:
            self._run("start", "worker", timeout=120)

    def kafka_lag(self) -> str:
        """Consumer group offsets and lag, as kafka-consumer-groups prints them."""
        return self._run(
            "exec", "-T", "kafka", f"{KAFKA_BIN}/kafka-consumer-groups.sh",
            "--bootstrap-server", "localhost:9092", "--describe", "--all-groups",
            timeout=60, check=False,
        ).stdout


def csv_rows(text: str) -> List[Dict[str, str]]:
    import csv
    import io

    return list(csv.DictReader(io.StringIO(text)))


def dsp_configs() -> Dict[str, dict]:
    resp = httpx.get(f"{DSP_SIM_URL}/admin/dsps", timeout=5)
    resp.raise_for_status()
    return resp.json()


def set_dsp_config(name: str, config: dict) -> None:
    resp = httpx.post(f"{DSP_SIM_URL}/admin/dsps/{name}", json=config, timeout=5)
    resp.raise_for_status()


def scrape_metrics() -> str:
    resp = httpx.get(f"{BACKEND_URL}/metrics", timeout=5)
    resp.raise_for_status()
    return resp.text
