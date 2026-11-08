"""Run generation, judging, and CSV export in one command."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Limit the number of cases.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Discard existing answers and judgments before running.",
    )
    parser.add_argument(
        "--skip-generation",
        action="store_true",
        help="Reuse existing answers and only run judging/export.",
    )
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help="Reuse existing judgments and only run export.",
    )
    return parser.parse_args()


def run_script(name: str, *args: str) -> None:
    command = [sys.executable, str(SCRIPT_DIR / name), *args]
    print(f"\n$ {' '.join(command)}", flush=True)
    subprocess.run(command, check=True, cwd=SCRIPT_DIR.parent)


def main() -> int:
    args = parse_args()
    common: list[str] = []
    if args.limit is not None:
        common.extend(["--limit", str(args.limit)])

    if not args.skip_generation:
        generation_args = list(common)
        if args.force:
            generation_args.append("--force")
        run_script("run_rag_eval.py", *generation_args)

    if not args.skip_judge:
        judge_args = list(common)
        if args.force:
            judge_args.append("--force")
        run_script("judge_answers.py", *judge_args)

    run_script("export_csv.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
