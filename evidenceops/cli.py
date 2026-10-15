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


def _fixed_workflow(run_dir: Path, args: argparse.Namespace):
    from evidenceops.baselines import fixed_workflow

    return fixed_workflow.investigate(run_dir)


def _backend(args: argparse.Namespace):
    """The model behind agent and log_only, built once per command."""
    if getattr(args, "_backend", None) is None:
        if args.provider == "anthropic":
            from evidenceops.agent import claude

            args._backend = claude.ClaudeModel(model=args.model or claude.DEFAULT_MODEL, effort=args.effort)
        else:
            from evidenceops.agent.openai_compat import OpenAICompatModel

            args._backend = OpenAICompatModel(args.provider, model=args.model)
    return args._backend


def _suffix(args: argparse.Namespace) -> str:
    return "" if args.provider == "anthropic" else f"_{args.provider}"


def _agent(run_dir: Path, args: argparse.Namespace):
    from evidenceops.agent import loop

    return loop.investigate(run_dir, _backend(args), method="agent" + _suffix(args), max_tool_calls=args.max_tool_calls)


def _agent_offline(run_dir: Path, args: argparse.Namespace):
    from evidenceops.agent import loop, offline

    return loop.investigate(run_dir, offline.OfflinePolicy(), method="agent_offline", max_tool_calls=args.max_tool_calls)


def _log_only(run_dir: Path, args: argparse.Namespace):
    from evidenceops.baselines import log_only

    return log_only.investigate(run_dir, _backend(args), method="log_only" + _suffix(args))


# Methods marked True call a model API and need a key for --provider.
METHODS = {
    "fixed_workflow": (_fixed_workflow, False),
    "agent_offline": (_agent_offline, False),
    "agent": (_agent, True),
    "log_only": (_log_only, True),
}


def _run_dirs(paths: List[str]) -> List[Path]:
    dirs = [Path(p) for p in paths] or sorted(p for p in RUNS_DIR.iterdir() if (p / "observed").is_dir())
    missing = [str(d) for d in dirs if not (d / "observed" / "incident.json").exists()]
    if missing:
        raise SystemExit(f"not run directories: {missing}")
    return dirs


def _cmd_investigate(args: argparse.Namespace) -> int:
    from evidenceops import investigation

    run = METHODS[args.method][0]
    for run_dir in _run_dirs(args.runs):
        report = run(run_dir, args)
        path = investigation.save(report, run_dir)
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
        else:
            print(f"  - set timeout_ms={c['value']} on {', '.join(c['dsps'])}")


def _cmd_remediate(args: argparse.Namespace) -> int:
    from evidenceops import remediation

    for run_dir in _run_dirs(args.runs):
        if not args.approve:
            proposal = remediation.propose(run_dir, args.method)
            _show(proposal)
            print(f"  awaiting approval: rerun with --approve 'Your Name' to test it in a disposable sandbox")
            continue
        from evidenceops.sandbox import run_experiment

        proposal = remediation.approve(run_dir, args.method, args.approve)
        _show(proposal)
        print(f"  approved by {proposal['approved_by']}; rebuilding a disposable platform to test it", flush=True)
        result = run_experiment(run_dir, proposal, time_scale=0.5 if args.quick else 1.0)
        print(
            f"  {result['verdict'].upper()}: baseline {result['baseline_success_rate']:.3f}, "
            f"incident {result['incident_success_rate']:.3f}, after remediation {result['recovered_success_rate']:.3f}",
            flush=True,
        )
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    from evidenceops import investigation

    rows = []
    for run_dir in _run_dirs(args.runs):
        truth = json.loads((run_dir / "ground_truth" / "ground_truth.json").read_text())
        found = sorted(p for p in (run_dir / "investigations").glob("*.json") if not p.name.endswith(".transcript.json"))
        for path in found:
            if not args.methods or path.stem in args.methods:
                row = investigation.grade(json.loads(path.read_text()), truth)
                result = run_dir / "remediation" / f"{path.stem}.result.json"
                if result.exists():
                    row["remediation_verdict"] = json.loads(result.read_text())["verdict"]
                rows.append(row)
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

    args = parser.parse_args(argv)
    return args.func(args)
