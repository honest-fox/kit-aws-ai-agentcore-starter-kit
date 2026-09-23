"""Command-line entry point. Wires config, transport, judge and runner.

Exit codes: 0 pass, 1 gate failed, 2 configuration or validation error.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

from . import config as cfg
from .datasets import load_all, validate
from .graders.judge import BedrockJudge, NullJudge
from .invoke import RuntimeTransport
from .report import render_json, render_markdown, summarise
from .runner import run_all

ROOT = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="eval.sh", description="Evaluate a deployed Kit agent.")
    p.add_argument("--validate", action="store_true",
                   help="Check datasets offline and exit. No AWS calls.")
    p.add_argument("--no-judge", action="store_true",
                   help="Deterministic assertions only.")
    p.add_argument("--suite", help="Run only this suite (dataset file stem).")
    p.add_argument("--case", help="Run only this case id.")
    p.add_argument("--dry-run", action="store_true",
                   help="List the cases that would run, then exit.")
    p.add_argument("--stack", default=None, help="CloudFormation stack name.")
    p.add_argument("--region", default=None, help="AWS region.")
    p.add_argument("--threshold", type=float, default=None,
                   help="Deterministic pass rate required to exit 0.")
    return p


def gate(results, threshold: float) -> int:
    s = summarise(results)
    if s["pass_rate"] is None:
        print("FAILED: every case errored - no quality signal at all.", file=sys.stderr)
        return 1
    if s["pass_rate"] < threshold:
        print(f"FAILED: pass rate {s['pass_rate']:.1%} < threshold {threshold:.1%}",
              file=sys.stderr)
        return 1
    print(f"PASSED: pass rate {s['pass_rate']:.1%} >= threshold {threshold:.1%}")
    return 0


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    # load_all raises on a structurally broken file - a mapping where a list
    # belongs, unparseable YAML - before validate() ever sees it. Letting
    # that propagate exits 1, which the contract above reserves for "the
    # quality gate failed": CI would blame the agent for the author's YAML.
    try:
        cases = load_all(ROOT / "datasets")
    except Exception as exc:  # noqa: BLE001
        print(f"dataset error: {exc}", file=sys.stderr)
        return 2

    errors = validate(cases)
    if errors:
        for e in errors:
            print(f"dataset error: {e}", file=sys.stderr)
        return 2

    if args.suite:
        cases = [c for c in cases if c.suite == args.suite]
    if args.case:
        cases = [c for c in cases if c.id == args.case]

    # Checked BEFORE --validate and --dry-run return, not only on the live
    # path. A mistyped --suite in a CI job would otherwise print
    # "OK: 0 cases valid" and exit 0 - green having checked nothing, which
    # is the one failure mode an offline gate exists to prevent.
    if not cases:
        print("No cases matched the filters.", file=sys.stderr)
        return 2

    if args.validate:
        print(f"OK: {len(cases)} cases valid")
        return 0
    if args.dry_run:
        for c in cases:
            print(f"{c.suite}/{c.id} ({len(c.turns)} turn(s))")
        return 0

    # Imported late so --validate and --dry-run need no AWS dependency.
    import boto3
    from botocore.config import Config

    region = args.region or cfg.region()
    stack = args.stack or cfg.stack_name()
    threshold = args.threshold if args.threshold is not None else cfg.threshold()

    try:
        target = cfg.resolve_target(
            stack, region, boto3.client("cloudformation", region_name=region))
    except Exception as exc:  # noqa: BLE001
        print(f"Could not resolve deployment: {exc}", file=sys.stderr)
        return 2

    # botocore's default 60s read timeout is shorter than a Kit turn that
    # uses the code interpreter or browser: the connection drops mid-stream
    # and surfaces as a spurious ERROR. docs/kit-evaluation.ipynb has the
    # same gap.
    transport = RuntimeTransport(
        target.runtime_arn,
        boto3.client(
            "bedrock-agentcore", region_name=region,
            config=Config(read_timeout=300, connect_timeout=15,
                          retries={"max_attempts": 2, "mode": "standard"})),
    )

    if args.no_judge:
        judge = NullJudge()
        judge_model = None
    else:
        judge_model = cfg.judge_model_id(region)
        judge = BedrockJudge(
            judge_model,
            boto3.client("bedrock-runtime", region_name=region,
                         config=Config(read_timeout=120, connect_timeout=15)))

    run_id = uuid.uuid4().hex[:8]
    print(f"Running {len(cases)} cases against {stack} in {region} (run {run_id})")

    def progress(result):
        print(f"  [{result.status:5}] {result.suite}/{result.case_id}")

    results = run_all(cases, transport, judge, run_id, on_result=progress)

    meta = {
        "model_id": target.runtime_arn.rsplit("/", 1)[-1],
        "judge_model_id": judge_model,
        "region": region,
        "stack": stack,
        "git_sha": _git_sha(),
        "run_id": run_id,
        "judge_attempted": sum(r.judge_attempted for r in results),
        "judge_scored": sum(r.judge_scored for r in results),
    }

    results_dir = ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / "scorecard.md").write_text(render_markdown(results, meta))
    (results_dir / "latest.json").write_text(
        json.dumps(render_json(results, meta), indent=2, default=str))
    print(f"Scorecard written to {results_dir / 'scorecard.md'}")

    return gate(results, threshold)


if __name__ == "__main__":
    sys.exit(main())
