#!/usr/bin/env python
"""Run a sweep, or rebuild the report from a saved run.

    python main.py run                          # stub model, no API key, no cost
    python main.py run --model claude-opus-5    # a real sweep
    python main.py run --model claude-haiku-4-5 --variant full --limit 5
    python main.py report                       # rebuild the report from results/

Results are written as JSON and committed. The report is a pure function of that
JSON, so regenerating it never re-runs the model.
"""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from evals.providers import PRICING, build_provider
from evals.questions import answer_key, load_questions
from evals.report import build_report
from evals.runner import run_sweep
from evals.schema import PromptVariant
from evals.warehouse import FIXTURE_DIR, connect

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"
LATEST_RUN = RESULTS_DIR / "latest-run.json"
REPORT_PATH = ROOT / "REPORT.md"


def cmd_run(args: argparse.Namespace) -> int:
    questions = load_questions()
    if args.difficulty:
        questions = [q for q in questions if q.difficulty == args.difficulty]
    if args.limit:
        questions = questions[: args.limit]
    if not questions:
        print("No questions selected.", file=sys.stderr)
        return 1

    variants = [PromptVariant(v) for v in (args.variant or [v.value for v in PromptVariant])]
    provider = build_provider(args.model, answer_key(load_questions()), effort=args.effort)

    print(
        f"Running {len(questions)} question(s) x {len(variants)} variant(s) "
        f"on {args.model}"
    )
    con = connect()
    try:
        result = run_sweep(
            con, questions, provider, variants,
            timeout=args.timeout, max_retries=args.retries,
        )
    finally:
        con.close()

    run = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": FIXTURE_DIR.name,
        "question_count": len(questions),
        "models": sorted({a.model for a in result.attempts}),
        "variants": [v.value for v in variants],
        "effort": args.effort,
        "attempts": [asdict(a) for a in result.attempts],
    }

    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_RUN.write_text(json.dumps(run, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(build_report(run), encoding="utf-8")
    print(f"Wrote {LATEST_RUN.relative_to(ROOT)} and {REPORT_PATH.relative_to(ROOT)}")
    return 0


def cmd_report(_: argparse.Namespace) -> int:
    if not LATEST_RUN.exists():
        print(f"No run found at {LATEST_RUN}. Run a sweep first.", file=sys.stderr)
        return 1
    run = json.loads(LATEST_RUN.read_text(encoding="utf-8"))
    REPORT_PATH.write_text(build_report(run), encoding="utf-8")
    print(f"Wrote {REPORT_PATH.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a sweep")
    run.add_argument("--model", default="stub",
                     help=f"'stub' (default, offline) or one of: {', '.join(sorted(PRICING))}")
    run.add_argument("--variant", action="append", choices=[v.value for v in PromptVariant],
                     help="prompt variant; repeatable, defaults to all")
    run.add_argument("--effort", default="high",
                     choices=["low", "medium", "high", "xhigh", "max"])
    run.add_argument("--difficulty", choices=["easy", "medium", "hard"])
    run.add_argument("--limit", type=int, help="only the first N questions")
    run.add_argument("--retries", type=int, default=1,
                     help="retries after a retryable database error (default 1)")
    run.add_argument("--timeout", type=float, default=15.0)
    run.add_argument("--dry-run", action="store_true",
                     help="run the sweep but write nothing — used by CI to smoke-test "
                          "the pipeline without overwriting the committed results")
    run.set_defaults(func=cmd_run)

    report = sub.add_parser("report", help="rebuild REPORT.md from the saved run")
    report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
