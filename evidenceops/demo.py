"""End-to-end demo that drives EvidenceOps through its HTTP API, the way a web
UI would: ``python -m evidenceops.demo s03-db-pool-exhaustion``.

Start the API first (``python -m evidenceops serve``). The demo records a
fresh incident, investigates it, shows the evidence behind the top
hypothesis, proposes a fix, and asks you at the terminal whether to approve
it. Only if you type your name does it test the fix in a disposable copy of
the platform. It never approves anything by itself.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Optional

import httpx


class Api:
    def __init__(self, base: str, token: str = ""):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = httpx.Client(base_url=base, headers=headers, timeout=30.0)

    def get(self, path: str) -> Any:
        return self._check(self.http.get(path))

    def post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        return self._check(self.http.post(path, json=body or {}))

    @staticmethod
    def _check(response: httpx.Response) -> Any:
        if response.status_code >= 400:
            raise SystemExit(f"{response.request.method} {response.request.url.path}: "
                             f"{response.status_code} {response.json().get('detail')}")
        return response.json()

    def wait(self, job: Dict[str, Any], label: str) -> Any:
        started, live = time.time(), sys.stdout.isatty()
        while job["status"] in ("queued", "running"):
            if live:
                print(f"\r  {label}: {job['status']} ({time.time() - started:.0f}s)", end="", flush=True)
            time.sleep(3)
            job = self.get(f"/jobs/{job['id']}")
        print(("\r" if live else "") + f"  {label}: {job['status']} after {time.time() - started:.0f}s" + " " * 10)
        if job["status"] != "succeeded":
            raise SystemExit(f"  {label} failed: {job['error']}")
        return job["result"]


def _step(title: str) -> None:
    print(f"\n== {title}")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evidenceops.demo")
    parser.add_argument("scenario", nargs="?", default="s03-db-pool-exhaustion")
    parser.add_argument("--api", default=os.environ.get("EVIDENCEOPS_API_URL", "http://127.0.0.1:8100"))
    parser.add_argument("--run", help="use an already recorded run instead of recording a new one")
    parser.add_argument("--method", default="agent_offline",
                        help="investigation method (agent and log_only need a model API key)")
    parser.add_argument("--provider", default="anthropic", choices=["anthropic", "gemini", "groq"])
    parser.add_argument("--quick", action="store_true", help="halve traffic phases")
    args = parser.parse_args(argv)
    api = Api(args.api, os.environ.get("EVIDENCEOPS_API_TOKEN", ""))

    if args.run:
        run_id = args.run
    else:
        _step(f"1. Reproduce '{args.scenario}' on a fresh platform")
        job = api.post("/runs", {"scenario_ids": [args.scenario], "quick": args.quick})
        [recorded] = api.wait(job, "recording")
        run_id = recorded["run_id"]
        print(f"  run {run_id}: success rate {recorded['baseline_success_rate']:.1%} -> "
              f"{recorded['incident_success_rate']:.1%}" if "incident_success_rate" in recorded else f"  run {run_id}")

    run = api.get(f"/runs/{run_id}")
    _step("2. The incident, as an on-call engineer gets it")
    print(f"  {run['report']}")
    for deploy in run["deployments"]:
        changes = ", ".join(f"{c['setting']} {c['from']}->{c['to']}" for c in deploy.get("config_changes", []))
        print(f"  deploy {deploy['finished_at']} -> {deploy['to_version']}" + (f": {changes}" if changes else ""))

    _step(f"3. Investigate with {args.method}")
    job = api.post(f"/runs/{run_id}/investigations", {"method": args.method, "provider": args.provider})
    report = api.wait(job, "investigating")["report"]
    if report["abstained"]:
        print(f"  abstained: {report['abstain_reason']}")
        return 0
    for rank, h in enumerate(report["hypotheses"][:3], 1):
        print(f"  {rank}. {h['category']} ({h['confidence']:.0%}): {h['statement']}")
    top = report["hypotheses"][0]
    print(f"  {report['tool_calls']} read-only tool calls; evidence for the top hypothesis:")
    for evidence_id in top["supporting"][:4]:
        item = report["evidence"].get(evidence_id, {})
        print(f"   {evidence_id} {item.get('tool')}({json.dumps(item.get('args', {}))})")

    _step("4. Propose a remediation from the allowlist")
    proposal = api.post(f"/runs/{run_id}/remediation/propose", {"method": report["method"]})
    print(f"  {proposal['purpose']}: {proposal['rationale']}")
    for change in proposal["resolved_changes"]:
        print(f"   - {json.dumps(change)}")
    print(f"  digest {proposal['digest']}")

    _step("5. Approval (a person, not the investigator)")
    if not sys.stdin.isatty():
        print("  stdin is not a terminal, so nothing is approved; stopping here.")
        return 0
    name = input("  Type your name to approve testing this fix in a sandbox (blank to stop): ").strip()
    if not name:
        print("  not approved; stopping.")
        return 0
    api.post(f"/runs/{run_id}/remediation/approve",
             {"method": report["method"], "approver": name, "digest": proposal["digest"]})

    _step("6. Test the fix in a disposable platform")
    job = api.post(f"/runs/{run_id}/remediation/test", {"method": report["method"], "quick": args.quick})
    result = api.wait(job, "sandbox")
    if "recovered_success_rate" in result:
        print(f"  {result['verdict'].upper()}: success rate {result['baseline_success_rate']:.1%} before, "
              f"{result['incident_success_rate']:.1%} during, {result['recovered_success_rate']:.1%} after the fix")
    else:
        print(f"  {result['verdict'].upper()}")

    _step("7. Grade against the answer key")
    graded = api.get(f"/runs/{run_id}/grading")
    print(f"  ground truth: {graded['ground_truth']['category']}")
    for g in graded["grades"]:
        print(f"   {g['method']:16} predicted {g['predicted']}  top-1 {'correct' if g['top1_correct'] else 'wrong'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
