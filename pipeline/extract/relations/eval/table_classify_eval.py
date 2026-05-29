"""Evaluate table_type_guess against golden_tables.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.extract.text.table_classify import guess_table_type
from pipeline.db import connect

EVAL_PATH = Path(__file__).resolve().parent / "golden_tables.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate table classification against golden cases")
    parser.add_argument("--report-id", type=int, default=1)
    args = parser.parse_args()

    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    report_cases = [c for c in cases if c.get("report_id", args.report_id) == args.report_id]

    passed = 0
    failed: list[str] = []

    with connect() as conn, conn.cursor() as cur:
        for case in report_cases:
            table_seq = case["table_seq"]
            expect = case.get("expect_type")
            cur.execute(
                """
                SELECT headers, rows, section_key, table_title
                FROM structured_tables
                WHERE report_id = %s AND table_seq = %s
                """,
                (args.report_id, table_seq),
            )
            row = cur.fetchone()
            if not row:
                failed.append(f"seq={table_seq}: table not found")
                continue

            headers, rows_json, section_key, table_title = row
            got = guess_table_type(headers, rows_json, section_key, table_title)
            if got == expect:
                passed += 1
            else:
                failed.append(f"seq={table_seq}: got={got!r} expect={expect!r} title={table_title!r}")

    result = {
        "report_id": args.report_id,
        "passed": passed,
        "total": len(report_cases),
        "failed": failed,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
