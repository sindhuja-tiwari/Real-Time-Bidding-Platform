"""Command line entry point: ``python -m evidenceops <command>``."""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from evidenceops import scenario as scenario_mod


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

    args = parser.parse_args(argv)
    return args.func(args)
