"""Run operating analysis and persist to DB."""

from __future__ import annotations

import argparse
import sys

import pipeline.env  # noqa: F401

from pipeline.analysis.pipeline import run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run operating condition analysis")
    parser.add_argument("--report-id", type=int, required=True)
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM explanation classification")
    args = parser.parse_args()

    try:
        run_id, result = run_pipeline(args.report_id, skip_llm=args.skip_llm)
    except Exception as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1

    print(f"run_id={run_id}")
    print(f"flags={result.stats.flag_count} explained={result.stats.explained_count}/{result.stats.flag_count}")
    print(f"benchmark_source={result.benchmark_source}")
    print("View: python -m report.cli --report-id {id} --mode analysis --serve".format(id=args.report_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
