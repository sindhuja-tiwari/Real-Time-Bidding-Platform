"""Command line entry point: ``python -m evidenceops <command>``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from evidenceops import scenario as scenario_mod
from evidenceops.paths import RUNS_DIR
from evidenceops.service import METHODS


def _cmd_list(_: argparse.Namespace) -> int:
    for s in scenario_mod.load_all():
        flag = " (ambiguous)" if s.ambiguous else ""
        print(f"{s.id:32} {s.ground_truth.category:28} {s.title}{flag}")
    return 0


def _cmd_validate(_: argparse.Namespace) -> int:
    scenarios = scenario_mod.load_all()
    print(f"{len(scenarios)} scenarios valid")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from evidenceops.runner import run_scenario
    from evidenceops.stack import Stack

    targets = scenario_mod.load_all() if args.all else [scenario_mod.find(i) for i in args.ids]
    if not targets:
        print("name at least one scenario id, or pass --all", file=sys.stderr)
        return 2
    stack = Stack()
    results = []
    try:
        for s in targets:
            print(f"==> {s.id}: {s.title}", flush=True)
            result = run_scenario(s, stack, time_scale=0.5 if args.quick else 1.0)
            results.append(result)
            status = "REPRODUCED" if result["passed"] else "NOT REPRODUCED"
            if result.get("alert", "auction_success_rate") == "auction_success_rate":
                measured = f"success rate {result['baseline_success_rate']:.3f} -> {result['incident_success_rate']:.3f}"
            else:
                measured = f"analytics drift {result['baseline_analytics_drift']} -> {result['incident_analytics_drift']} auctions"
            print(f"    {status}: {measured}  ({result['run_dir']})", flush=True)
    finally:
        if not args.keep_up:
            stack.down()
    if args.json:
        print(json.dumps(results, indent=2))
    return 0 if all(r["passed"] for r in results) else 1


def _investigator(args: argparse.Namespace):
    from evidenceops import service

    try:
        return service.Investigator(args.method, args.provider, args.model, args.effort, args.max_tool_calls)
    except service.Rejected as exc:
        raise SystemExit(str(exc)) from None


def _run_dirs(paths: List[str]) -> List[Path]:
    dirs = [Path(p) for p in paths] or sorted(p for p in RUNS_DIR.iterdir() if (p / "observed").is_dir())
    missing = [str(d) for d in dirs if not (d / "observed" / "incident.json").exists()]
    if missing:
        raise SystemExit(f"not run directories: {missing}")
    return dirs


def _cmd_investigate(args: argparse.Namespace) -> int:
    investigate = _investigator(args)
    for run_dir in _run_dirs(args.runs):
        report, path = investigate(run_dir)
        top = "abstained: " + report.abstain_reason if report.abstained else report.hypotheses[0].category
        cost = f", ${report.cost_usd:.4f}" if report.cost_usd else ""
        print(f"{run_dir.name}: {top}  [{report.tool_calls} tool calls{cost}]  ({path})", flush=True)
    return 0


def _show(proposal: Dict[str, Any]) -> None:
    print(f"{proposal['run_id']} [{proposal['method']}] {proposal['purpose']} for {proposal.get('hypothesis')}"
          f" (from the {proposal['source']}; digest {proposal['digest']})")
    print(f"  why: {proposal['rationale']}")
    for c in proposal["resolved_changes"]:
        if c["kind"] == "deploy_setting":
            note = " (rollback)" if c.get("rolled_back") else ""
            print(f"  - set {c['setting']}={c['value']}{note}")
        elif c["kind"] == "dsp_timeout_ms":
            print(f"  - set timeout_ms={c['value']} on {', '.join(c['dsps'])}")
        elif c["kind"] == "rollback_migration":
            print(f"  - roll back migration {c['migration']}")
        elif c["kind"] == "skip_stuck_message":
            print(f"  - move {', '.join(c['groups'])} one message past their committed offset")


def _cmd_remediate(args: argparse.Namespace) -> int:
    from evidenceops import remediation

    for run_dir in _run_dirs(args.runs):
        if not args.approve:
            try:
                proposal = remediation.propose(run_dir, args.method)
            except SystemExit as exc:
                print(exc)
                continue
            _show(proposal)
            print(f"  awaiting approval: rerun with --approve 'Your Name' to test it in a disposable sandbox")
            continue
        from evidenceops.sandbox import run_experiment

        proposal = remediation.approve(run_dir, args.method, args.approve)
        _show(proposal)
        print(f"  approved by {proposal['approved_by']}; rebuilding a disposable platform to test it", flush=True)
        result = run_experiment(run_dir, proposal, time_scale=0.5 if args.quick else 1.0)
        print(
            f"  {result['verdict'].upper()}: " + (
                f"baseline {result['baseline_success_rate']:.3f}, incident {result['incident_success_rate']:.3f}, "
                f"after remediation {result['recovered_success_rate']:.3f}"
                if "recovered_success_rate" in result else
                f"analytics drift {result['incident_analytics_drift']} during the incident, "
                f"{result['recovered_analytics_drift']} after remediation ({result['recovery_target']})"
            ),
            flush=True,
        )
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    from evidenceops import service

    evaluation = service.evaluate(_run_dirs(args.runs), args.methods)
    for r in evaluation["runs"]:
        mark = "abstain" if r["abstained"] else ("OK " if r["top1_correct"] else "MISS")
        print(f"{r['method']:16} {r['scenario_id']:34} {mark:8} truth={r['truth']:24} predicted={r['predicted']}  top3={r['top3']}")
    print(json.dumps(evaluation["summary"], indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(evaluation, indent=2) + "\n")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from evidenceops.api import serve

    serve(args.host, args.port)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="evidenceops")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list scenarios").set_defaults(func=_cmd_list)
    sub.add_parser("validate", help="statically validate every scenario file").set_defaults(func=_cmd_validate)

    run = sub.add_parser("run", help="reset the platform, inject a scenario, and record the run")
    run.add_argument("ids", nargs="*", help="scenario ids (see 'list')")
    run.add_argument("--all", action="store_true", help="run every scenario")
    run.add_argument("--quick", action="store_true", help="halve traffic phase durations")
    run.add_argument("--keep-up", action="store_true", help="leave the stack running afterwards")
    run.add_argument("--json", action="store_true", help="print verification results as JSON")
    run.set_defaults(func=_cmd_run)

    inv = sub.add_parser("investigate", help="run an investigation method on recorded runs")
    inv.add_argument("runs", nargs="*", help="run directories (default: all under evidenceops/runs)")
    inv.add_argument("--method", choices=list(METHODS), default="fixed_workflow")
    inv.add_argument("--provider", default="anthropic", choices=["anthropic", "gemini", "groq"],
                     help="model API for agent and log_only (gemini and groq have free tiers)")
    inv.add_argument("--model", help="model name (default depends on --provider)")
    inv.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"], help="Claude only")
    inv.add_argument("--max-tool-calls", type=int, default=20, help="tool budget for agent methods")
    inv.set_defaults(func=_cmd_investigate)

    rem = sub.add_parser("remediate", help="propose a remediation from an investigation; test it once approved")
    rem.add_argument("runs", nargs="*", help="run directories (default: all under evidenceops/runs)")
    rem.add_argument("--method", default="fixed_workflow", help="whose investigation to remediate from")
    rem.add_argument("--approve", metavar="NAME", help="approve the saved proposal and run it in a sandbox")
    rem.add_argument("--quick", action="store_true", help="halve the sandbox's traffic phases")
    rem.set_defaults(func=_cmd_remediate)

    ev = sub.add_parser("evaluate", help="grade saved investigations against ground truth")
    ev.add_argument("runs", nargs="*", help="run directories (default: all under evidenceops/runs)")
    ev.add_argument("--methods", nargs="*", help="methods to grade (default: all found)")
    ev.add_argument("--out", help="also write rows and summary to this JSON file")
    ev.set_defaults(func=_cmd_evaluate)

    srv = sub.add_parser("serve", help="serve the HTTP API a web UI can drive (see evidenceops/api.py)")
    srv.add_argument("--host", default="127.0.0.1", help="non-loopback needs EVIDENCEOPS_API_TOKEN")
    srv.add_argument("--port", type=int, default=8100)
    srv.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)
