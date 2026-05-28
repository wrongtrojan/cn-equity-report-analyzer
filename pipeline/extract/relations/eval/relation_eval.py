"""Validate extracted relations against golden_relations.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.ingest.db import connect

EVAL_PATH = Path(__file__).resolve().parent / "golden_relations.json"


def _check_must_exist(cur, report_id: int, case: dict) -> bool:
    cur.execute(
        """
        SELECT COUNT(*)
        FROM kg_relations r
        JOIN kg_entities se ON se.id = r.subject_entity_id
        JOIN kg_entities oe ON oe.id = r.object_entity_id
        WHERE r.report_id = %s
          AND r.relation_type = %s
          AND se.name ILIKE %s
          AND oe.name ILIKE %s
        """,
        (
            report_id,
            case["relation_type"],
            case["subject"],
            f"%{case['object_contains']}%",
        ),
    )
    return cur.fetchone()[0] > 0


def _check_must_have_attrs(cur, report_id: int, case: dict) -> bool:
    cur.execute(
        """
        SELECT r.attrs
        FROM kg_relations r
        JOIN kg_entities se ON se.id = r.subject_entity_id
        WHERE r.report_id = %s
          AND r.relation_type = %s
          AND se.name ILIKE %s
        """,
        (report_id, case["relation_type"], case["subject"]),
    )
    rows = cur.fetchall()
    if not rows:
        return False
    required = case.get("attrs_contains", [])
    for (attrs,) in rows:
        if not isinstance(attrs, dict):
            continue
        if all(key in attrs and attrs[key] for key in required):
            return True
    return False


def _check_must_not_exist(cur, report_id: int, case: dict) -> tuple[bool, str | None]:
    forbidden = case.get("forbidden_subjects", [])
    relation_type = case.get("relation_type")
    title_contains = case.get("forbidden_evidence_title_contains")

    if forbidden:
        cur.execute(
            """
            SELECT se.name
            FROM kg_relations r
            JOIN kg_entities se ON se.id = r.subject_entity_id
            WHERE r.report_id = %s AND se.name = ANY(%s)
            """,
            (report_id, forbidden),
        )
        hit = cur.fetchone()
        if hit:
            return False, f"forbidden subject present: {hit[0]}"

    if relation_type and title_contains:
        cur.execute(
            """
            SELECT se.name, e.attrs
            FROM kg_relations r
            JOIN kg_entities se ON se.id = r.subject_entity_id
            LEFT JOIN kg_relation_evidence e ON e.relation_id = r.id
            WHERE r.report_id = %s
              AND r.relation_type = %s
              AND COALESCE(e.attrs->>'table_title', '') LIKE %s
            LIMIT 1
            """,
            (report_id, relation_type, f"%{title_contains}%"),
        )
        hit = cur.fetchone()
        if hit:
            return False, f"{relation_type} from forbidden table title: {hit}"

    return True, None


def _check_count_range(cur, report_id: int, case: dict) -> tuple[bool, str | None]:
    cur.execute(
        """
        SELECT COUNT(*)
        FROM kg_relations
        WHERE report_id = %s AND relation_type = %s
        """,
        (report_id, case["relation_type"]),
    )
    count = cur.fetchone()[0]
    min_count = case.get("min", 0)
    max_count = case.get("max", 10**9)
    if min_count <= count <= max_count:
        return True, None
    return False, f"{case['relation_type']} count={count}, expected {min_count}-{max_count}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate kg_relations against golden cases")
    parser.add_argument("--report-id", type=int, default=1)
    args = parser.parse_args()

    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    passed = 0
    failed: list[str] = []

    with connect() as conn, conn.cursor() as cur:
        for case in cases:
            if case.get("report_id", args.report_id) != args.report_id:
                continue
            case_type = case.get("type", "must_exist")
            ok = False
            detail = ""

            if case_type == "must_exist":
                ok = _check_must_exist(cur, args.report_id, case)
                if not ok:
                    detail = f"{case['relation_type']}: {case['subject']} -> {case['object_contains']}"
            elif case_type == "must_have_attrs":
                ok = _check_must_have_attrs(cur, args.report_id, case)
                if not ok:
                    detail = f"{case['relation_type']}: {case['subject']} missing attrs {case.get('attrs_contains')}"
            elif case_type == "must_not_exist":
                ok, detail = _check_must_not_exist(cur, args.report_id, case)
                if detail is None:
                    detail = "negative case violated"
            elif case_type == "count_range":
                ok, detail = _check_count_range(cur, args.report_id, case)
                if detail is None:
                    detail = "count out of range"
            else:
                detail = f"unknown case type: {case_type}"
                ok = False

            if ok:
                passed += 1
            else:
                failed.append(f"[{case_type}] {detail}")

    result = {
        "report_id": args.report_id,
        "passed": passed,
        "total": len([c for c in cases if c.get("report_id", args.report_id) == args.report_id]),
        "failed": failed,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
