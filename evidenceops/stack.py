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
)

PROJECT_NAME = "rtb-evidenceops"
PLATFORM_SERVICES = ["postgres", "redis", "kafka", "dsp-simulator", "backend", "worker"]
# Budget-driven NO_BIDs would otherwise appear partway through a long run
# and contaminate every scenario; budget exhaustion gets its own scenario.
SEED_CAMPAIGN_BUDGET = 1_000_000
LOG_SERVICES = ["backend", "worker", "dsp-simulator", "postgres", "kafka", "redis"]

BACKEND_URL = os.getenv("EVIDENCEOPS_BACKEND_URL", "http://localhost:8000")
DSP_SIM_URL = os.getenv("EVIDENCEOPS_DSP_SIM_URL", "http://localhost:9000")

# Exported per run for investigators. Each runs inside a READ ONLY
# transaction (see export_query).
READ_QUERIES: Dict[str, str] = {
    "auctions": (
        "SELECT id, request_id, status, duration_ms, started_at, completed_at, winning_bid_id "
        "FROM auction ORDER BY started_at"
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
}

# Sampled repeatedly during a run (point-in-time views are useless after it).
SAMPLED_QUERIES: Dict[str, str] = {
    "pg_stat_activity": (
        "SELECT state, wait_event_type, wait_event, count(*) AS connections "
        "FROM pg_stat_activity WHERE datname = 'rtb' AND pid <> pg_backend_pid() "
        "GROUP BY 1, 2, 3 ORDER BY 4 DESC"
    ),
}


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

    def _run(self, *args: str, timeout: float = 600, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            self._argv(*args), cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout
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
