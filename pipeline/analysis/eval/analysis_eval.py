"""Evaluate analysis results against golden cases (DB-backed)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pipeline.env  # noqa: F401

from pipeline.db import connect

EVAL_PATH = Path(__file__).resolve().parent / "golden_analysis.json"


def _latest_run_id(cur, report_id: int) -> int | None:
    cur.execute(
        """
        SELECT id FROM analysis_runs
        WHERE report_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (report_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate analysis_runs against golden cases")
    parser.add_argument("--report-id", type=int, default=1)
    args = parser.parse_args()

    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    failed: list[str] = []
    passed = 0

    with connect() as conn, conn.cursor() as cur:
        run_id = _latest_run_id(cur, args.report_id)
        if not run_id:
            print(json.dumps({"passed": 0, "total": len(cases), "failed": ["no analysis_runs"]}, ensure_ascii=False, indent=2))
            return 1

        for case in cases:
            if case.get("report_id", args.report_id) != args.report_id:
                continue
            case_type = case.get("type")
            ok = False
            detail = ""

            if case_type == "run_exists":
                ok = run_id is not None
                detail = "no run"
            elif case_type == "must_flag":
                cur.execute(
                    """
                    SELECT COUNT(*) FROM metric_flags
                    WHERE run_id = %s AND item_name = %s AND rule_id = %s
                    """,
                    (run_id, case["item_name"], case["rule_id"]),
                )
                ok = cur.fetchone()[0] > 0
                detail = f"{case['item_name']}/{case['rule_id']}"
            elif case_type == "must_explain":
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM flag_explanations fe
                    JOIN metric_flags mf ON mf.id = fe.flag_id
                    WHERE mf.run_id = %s
                      AND mf.item_name ILIKE %s
                      AND fe.explanation_type IN ('direct', 'indirect')
                    """,
                    (run_id, f"%{case['item_contains']}%"),
                )
                ok = cur.fetchone()[0] >= int(case.get("min_explanations", 1))
                detail = case["item_contains"]
            elif case_type == "min_snapshots":
                cur.execute(
                    "SELECT COUNT(*) FROM metric_snapshots WHERE run_id = %s",
                    (run_id,),
                )
                count = cur.fetchone()[0]
                ok = count >= int(case.get("min_count", 1))
                detail = f"snapshots={count} (min {case.get('min_count', 1)})"
            else:
                detail = f"unknown type {case_type}"
                ok = False

            if ok:
                passed += 1
            else:
                failed.append(f"[{case_type}] {detail}")

    total = len([c for c in cases if c.get("report_id", args.report_id) == args.report_id])
    print(json.dumps({"report_id": args.report_id, "run_id": run_id, "passed": passed, "total": total, "failed": failed}, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
