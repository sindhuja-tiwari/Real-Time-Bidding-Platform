"""Command line entry point: ``python -m evidenceops <command>``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from evidenceops import scenario as scenario_mod
from evidenceops.paths import RUNS_DIR


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
            print(
                f"    {status}: success rate {result['baseline_success_rate']:.3f} -> "
                f"{result['incident_success_rate']:.3f}  ({result['run_dir']})",
                flush=True,
            )
    finally:
        if not args.keep_up:
            stack.down()
    if args.json:
        print(json.dumps(results, indent=2))
    return 0 if all(r["passed"] for r in results) else 1


METHODS = {"fixed_workflow": "evidenceops.baselines.fixed_workflow"}


def _run_dirs(paths: List[str]) -> List[Path]:
    dirs = [Path(p) for p in paths] or sorted(p for p in RUNS_DIR.iterdir() if (p / "observed").is_dir())
    missing = [str(d) for d in dirs if not (d / "observed" / "incident.json").exists()]
    if missing:
        raise SystemExit(f"not run directories: {missing}")
    return dirs


def _cmd_investigate(args: argparse.Namespace) -> int:
    import importlib

    from evidenceops import investigation

    module = importlib.import_module(METHODS[args.method])
    for run_dir in _run_dirs(args.runs):
        report = module.investigate(run_dir)
        path = investigation.save(report, run_dir)
        top = "abstained: " + report.abstain_reason if report.abstained else report.hypotheses[0].category
        print(f"{run_dir.name}: {top}  ({path})")
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    from evidenceops import investigation

    rows = []
    for run_dir in _run_dirs(args.runs):
        truth = json.loads((run_dir / "ground_truth" / "ground_truth.json").read_text())
        for method in args.methods or sorted(METHODS):
            path = run_dir / "investigations" / f"{method}.json"
            if path.exists():
                rows.append(investigation.grade(json.loads(path.read_text()), truth))
    for r in rows:
        mark = "abstain" if r["abstained"] else ("OK " if r["top1_correct"] else "MISS")
        print(f"{r['method']:16} {r['scenario_id']:34} {mark:8} truth={r['truth']:24} predicted={r['predicted']}  top3={r['top3']}")
    by_method: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_method.setdefault(r["method"], []).append(r)
    summary = {m: investigation.aggregate(rs) for m, rs in by_method.items()}
    print(json.dumps(summary, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps({"runs": rows, "summary": summary}, indent=2) + "\n")
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
    inv.add_argument("--method", choices=sorted(METHODS), default="fixed_workflow")
    inv.set_defaults(func=_cmd_investigate)

    ev = sub.add_parser("evaluate", help="grade saved investigations against ground truth")
    ev.add_argument("runs", nargs="*", help="run directories (default: all under evidenceops/runs)")
    ev.add_argument("--methods", nargs="*", help="methods to grade (default: all found)")
    ev.add_argument("--out", help="also write rows and summary to this JSON file")
    ev.set_defaults(func=_cmd_evaluate)

    args = parser.parse_args(argv)
    return args.func(args)
