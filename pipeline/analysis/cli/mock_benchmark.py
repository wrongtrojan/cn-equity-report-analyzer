"""Generate mock industry benchmarks."""

from __future__ import annotations

import argparse
import sys

import pipeline.env  # noqa: F401

from pipeline.analysis.benchmarks import MockBenchmarkProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate mock industry benchmarks")
    parser.add_argument("--report-id", type=int, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    provider = MockBenchmarkProvider(seed=args.seed)
    try:
        count = provider.generate_for_report(args.report_id)
    except Exception as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    print(f"upserted {count} mock benchmark rows (source=mock, seed={args.seed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
