from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
SCENARIO_DIR = PACKAGE_DIR / "scenarios"
RUNS_DIR = PACKAGE_DIR / "runs"
BASE_COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
OVERLAY_COMPOSE_FILE = PACKAGE_DIR / "compose.evidenceops.yml"
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE_FILE = REPO_ROOT / ".env.example"
# Bind-mounted into the OpenTelemetry collector; holds the live trace file.
TELEMETRY_DIR = PACKAGE_DIR / ".telemetry"
