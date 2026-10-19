"""HTTP API for EvidenceOps: ``python -m evidenceops serve``.

Everything the CLI does is available here, so a web UI can drive
EvidenceOps instead of a terminal. The API runs on the host next to Docker
(recording a run or testing a fix rebuilds the platform with Docker
Compose), on 127.0.0.1:8100 by default.

Safety model, the same as the CLI's:

- Reading runs, reports, grades and evidence is read-only. The evidence
  endpoints run the investigator's own read-only diagnostic tools against
  recorded files; nothing reaches a live system.
- Nothing here executes text from a request. Requests name a scenario, a run,
  an investigation method or a diagnostic tool from fixed lists; remediation
  changes come only from the saved proposal and are re-validated against the
  allowlist before they run.
- A remediation runs only after a person approves it, naming themselves and
  the digest of the exact proposal they reviewed. Testing it is a separate
  call, and it runs in a disposable copy of the platform.
- Set ``EVIDENCEOPS_API_TOKEN`` to require ``Authorization: Bearer <token>``
  on every call that starts work or approves something. The server refuses
  to listen on a non-loopback address without a token.

Long operations (recording a run, investigating, testing a fix) return 202
with a job; poll ``GET /jobs/{id}``. Jobs that use Docker run one at a time.
"""
from __future__ import annotations

import hmac
import os
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from evidenceops import service
from evidenceops.telemetry import TOOLS, EvidenceStore, RunEvidence

TOKEN_ENV = "EVIDENCEOPS_API_TOKEN"
CORS_ENV = "EVIDENCEOPS_API_CORS_ORIGINS"
DEFAULT_CORS = "http://localhost:3000,http://127.0.0.1:3000"
MAX_FINISHED_JOBS = 200


# --------------------------------------------------------------------- jobs


class Job:
    def __init__(self, kind: str, params: Dict[str, Any]):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.params = params
        self.status = "queued"
        self.created_at = _now()
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.result: Any = None
        self.error: Optional[str] = None
        self.progress: List[Any] = []

    def to_json(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in (
            "id", "kind", "params", "status", "created_at", "started_at", "finished_at", "progress", "result", "error"
        )}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobRunner:
    """Docker jobs share one platform stack, so they run one at a time;
    investigations only read files and run alongside them."""

    def __init__(self) -> None:
        self.jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._docker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="evidenceops-docker")
        self._files = ThreadPoolExecutor(max_workers=4, thread_name_prefix="evidenceops-investigate")

    def submit(self, kind: str, params: Dict[str, Any], fn: Callable[[Job], Any], docker: bool) -> Job:
        job = Job(kind, params)
        with self._lock:
            self.jobs[job.id] = job
            self._prune()
        (self._docker if docker else self._files).submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: Callable[[Job], Any]) -> None:
        job.status, job.started_at = "running", _now()
        try:
            job.result = fn(job)
            job.status = "succeeded"
        except (service.NotFound, service.Rejected) as exc:
            job.status, job.error = "failed", str(exc)
        except Exception as exc:  # noqa: BLE001 - reported to the caller, not raised
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        job.finished_at = _now()

    def _prune(self) -> None:
        finished = [j for j in self.jobs.values() if j.status in ("succeeded", "failed")]
        for job in sorted(finished, key=lambda j: j.created_at)[: max(0, len(finished) - MAX_FINISHED_JOBS)]:
            del self.jobs[job.id]

    def get(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"no job '{job_id}'")
        return job


# ------------------------------------------------------------------ bodies


class RunRequest(BaseModel):
    scenario_ids: List[str] = Field(min_length=1, max_length=30)
    quick: bool = False


class InvestigateRequest(BaseModel):
    method: str = "fixed_workflow"
    provider: str = "anthropic"
    model: Optional[str] = Field(default=None, max_length=100)
    effort: str = "high"
    max_tool_calls: int = 20


class ProposeRequest(BaseModel):
    method: str


class ApproveRequest(BaseModel):
    method: str
    approver: str = Field(min_length=1, max_length=100)
    digest: str = Field(min_length=16, max_length=16)


class TestRequest(BaseModel):
    method: str
    quick: bool = False


class ToolRequest(BaseModel):
    args: Dict[str, Any] = Field(default_factory=dict)


class EvaluateRequest(BaseModel):
    run_ids: List[str] = Field(default_factory=list)
    methods: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------- app


def _guard(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        return fn(*args)
    except service.NotFound as exc:
        raise HTTPException(404, str(exc)) from None
    except service.Rejected as exc:
        raise HTTPException(409, str(exc)) from None


def create_app(token: Optional[str] = None, cors_origins: Optional[List[str]] = None) -> FastAPI:
    token = token if token is not None else os.environ.get(TOKEN_ENV, "")
    origins = cors_origins if cors_origins is not None else [
        o.strip() for o in os.environ.get(CORS_ENV, DEFAULT_CORS).split(",") if o.strip()
    ]
    app = FastAPI(title="EvidenceOps", version="1.0.0",
                  description="Reproduce incidents, investigate them, and test approved fixes in a sandbox.")
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"])
    jobs = JobRunner()
    app.state.jobs = jobs

    def authorized(authorization: str = Header(default="")) -> None:
        if token and not hmac.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(401, "missing or wrong bearer token")

    act = [Depends(authorized)]

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok", "auth_required": bool(token)}

    # scenarios and runs ------------------------------------------------

    @app.get("/scenarios")
    def list_scenarios() -> List[Dict[str, Any]]:
        return service.scenarios()

    @app.post("/runs", status_code=202, dependencies=act)
    def start_run(body: RunRequest) -> Dict[str, Any]:
        for scenario_id in body.scenario_ids:
            _guard(service.find_scenario, scenario_id)

        def work(job: Job) -> Any:
            return service.record_run(
                body.scenario_ids, quick=body.quick,
                on_result=lambda r: job.progress.append({"run_id": r["run_id"], "reproduced": r["passed"]}),
            )

        return jobs.submit("run", body.model_dump(), work, docker=True).to_json()

    @app.get("/runs")
    def list_runs() -> List[Dict[str, Any]]:
        return [service.run_summary(d) for d in service.all_run_dirs()]

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> Dict[str, Any]:
        return service.run_detail(_guard(service.run_dir, run_id))

    @app.get("/runs/{run_id}/grading")
    def get_grading(run_id: str) -> Dict[str, Any]:
        return _guard(service.grading, _guard(service.run_dir, run_id))

    # evidence (read-only diagnostic tools) -----------------------------

    @app.get("/tools")
    def list_tools() -> Dict[str, Any]:
        return {name: spec["params"] for name, spec in TOOLS.items()}

    @app.post("/runs/{run_id}/tools/{tool}")
    def call_tool(run_id: str, tool: str, body: ToolRequest) -> Dict[str, Any]:
        directory = _guard(service.run_dir, run_id)
        if tool not in TOOLS:
            raise HTTPException(404, f"no tool '{tool}'")
        unknown = set(body.args) - set(TOOLS[tool]["params"])
        if unknown:
            raise HTTPException(422, f"{tool} does not take {sorted(unknown)}")
        try:
            return EvidenceStore(RunEvidence(directory / "observed")).call(tool, **body.args)
        except (TypeError, ValueError, KeyError) as exc:
            raise HTTPException(422, f"{tool}: {exc}") from None

    # investigations ----------------------------------------------------

    @app.post("/runs/{run_id}/investigations", status_code=202, dependencies=act)
    def start_investigation(run_id: str, body: InvestigateRequest) -> Dict[str, Any]:
        directory = _guard(service.run_dir, run_id)
        investigator = _guard(lambda: service.Investigator(
            body.method, body.provider, body.model, body.effort, body.max_tool_calls
        ))

        def work(job: Job) -> Any:
            report, _ = investigator(directory)
            return {"run_id": run_id, "method": report.method, "report": report.to_json()}

        return jobs.submit("investigate", {"run_id": run_id, **body.model_dump()}, work, docker=False).to_json()

    @app.get("/runs/{run_id}/investigations/{method}")
    def get_investigation(run_id: str, method: str) -> Dict[str, Any]:
        return _guard(service.report, _guard(service.run_dir, run_id), method)

    # remediation -------------------------------------------------------

    @app.post("/runs/{run_id}/remediation/propose", dependencies=act)
    def propose(run_id: str, body: ProposeRequest) -> Dict[str, Any]:
        return _guard(service.propose, _guard(service.run_dir, run_id), body.method)

    @app.get("/runs/{run_id}/remediation/{method}")
    def get_proposal(run_id: str, method: str) -> Dict[str, Any]:
        directory = _guard(service.run_dir, run_id)
        found = _guard(service.proposal, directory, method)
        try:
            found["result"] = service.remediation_result(directory, method)
        except service.NotFound:
            found["result"] = None
        return found

    @app.post("/runs/{run_id}/remediation/approve", dependencies=act)
    def approve(run_id: str, body: ApproveRequest) -> Dict[str, Any]:
        return _guard(service.approve, _guard(service.run_dir, run_id), body.method, body.approver, body.digest)

    @app.post("/runs/{run_id}/remediation/test", status_code=202, dependencies=act)
    def test(run_id: str, body: TestRequest) -> Dict[str, Any]:
        directory = _guard(service.run_dir, run_id)
        if _guard(service.proposal, directory, body.method).get("status") != "approved":
            raise HTTPException(409, "the proposal has not been approved")
        work = lambda job: service.test_remediation(directory, body.method, body.quick)  # noqa: E731
        return jobs.submit("remediation_test", {"run_id": run_id, **body.model_dump()}, work, docker=True).to_json()

    # evaluation and jobs -----------------------------------------------

    @app.post("/evaluate")
    def evaluate(body: EvaluateRequest) -> Dict[str, Any]:
        dirs = [_guard(service.run_dir, r) for r in body.run_ids] or service.all_run_dirs()
        return service.evaluate(dirs, body.methods or None)

    @app.get("/jobs")
    def list_jobs() -> List[Dict[str, Any]]:
        return [j.to_json() for j in sorted(jobs.jobs.values(), key=lambda j: j.created_at, reverse=True)]

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> Dict[str, Any]:
        return jobs.get(job_id).to_json()

    return app


def serve(host: str = "127.0.0.1", port: int = 8100) -> None:
    import ipaddress

    import uvicorn

    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if not loopback and not os.environ.get(TOKEN_ENV):
        raise SystemExit(f"refusing to listen on {host} without {TOKEN_ENV} set")
    uvicorn.run(create_app(), host=host, port=port)
