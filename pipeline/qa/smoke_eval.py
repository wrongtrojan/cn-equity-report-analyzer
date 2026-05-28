from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .pipeline import QAPipeline

DEFAULT_GOLDEN = Path(__file__).resolve().parent / "eval" / "golden_questions.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "eval" / "smoke_results.json"

REFERENCE_FIELDS = (
    "category",
    "expected_keywords",
    "expected_any_keywords",
    "forbidden_keywords",
    "expected_granularity",
    "expected_period_labels",
    "min_evidence",
    "notes",
)


def _check_case(case: dict, resp) -> tuple[bool, list[str]]:
    issues: list[str] = []
    answer = resp.answer or ""

    for keyword in case.get("expected_keywords", []):
        if keyword not in answer.replace(",", ""):
            issues.append(f"missing answer keyword: {keyword}")

    any_keywords = case.get("expected_any_keywords", [])
    if any_keywords and not any(k in answer for k in any_keywords):
        issues.append(f"missing any of answer keywords: {any_keywords}")

    for keyword in case.get("forbidden_keywords", []):
        if keyword in answer.replace(",", ""):
            issues.append(f"forbidden answer keyword present: {keyword}")

    expected_granularity = case.get("expected_granularity")
    if expected_granularity:
        actual = resp.normalized.sql_targets.period_granularity
        if actual != expected_granularity:
            issues.append(f"granularity expected={expected_granularity}, actual={actual}")

    expected_period_labels = case.get("expected_period_labels", [])
    if expected_period_labels:
        actual_labels = resp.normalized.sql_targets.period_labels
        for label in expected_period_labels:
            if label not in actual_labels:
                issues.append(f"missing period_label: {label}, actual={actual_labels}")

    min_evidence = case.get("min_evidence")
    if min_evidence is not None and len(resp.evidence) < min_evidence:
        issues.append(f"evidence count {len(resp.evidence)} < min_evidence {min_evidence}")

    return len(issues) == 0, issues


def _build_result(case: dict, resp, *, run_auto_check: bool) -> dict:
    reference = {k: case[k] for k in REFERENCE_FIELDS if k in case}
    result = {
        "id": case["id"],
        "report_id": case["report_id"],
        "query": case["query"],
        "reference": reference,
        "answer": resp.answer,
        "citations": resp.citations,
        "normalized": resp.normalized.model_dump(),
        "evidence": [item.model_dump() for item in resp.evidence],
        "evidence_count": len(resp.evidence),
    }
    if run_auto_check:
        passed, issues = _check_case(case, resp)
        result["auto_check"] = {"passed": passed, "issues": issues}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run QA eval and export full results to JSON")
    parser.add_argument(
        "--golden",
        type=Path,
        default=DEFAULT_GOLDEN,
        help="golden question file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="output JSON for manual review",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="only run cases with matching category prefix/id",
    )
    parser.add_argument(
        "--no-auto-check",
        action="store_true",
        help="skip keyword/granularity auto checks in output",
    )
    args = parser.parse_args()

    cases = json.loads(args.golden.read_text(encoding="utf-8"))
    if args.category:
        cases = [
            c
            for c in cases
            if c.get("category", "").startswith(args.category) or c.get("id", "").startswith(args.category)
        ]

    qa = QAPipeline()
    results: list[dict] = []
    auto_passed = 0

    for i, case in enumerate(cases, start=1):
        print(f"[{i}/{len(cases)}] {case['id']} {case['query']}")
        session = qa.load_session(case["report_id"])
        resp = qa.ask(session, case["query"])
        item = _build_result(case, resp, run_auto_check=not args.no_auto_check)
        results.append(item)
        if item.get("auto_check", {}).get("passed"):
            auto_passed += 1

    payload = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "golden_file": str(args.golden.resolve()),
        "summary": {
            "total": len(results),
            "auto_passed": auto_passed if not args.no_auto_check else None,
            "auto_warn": len(results) - auto_passed if not args.no_auto_check else None,
        },
        "results": results,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nWrote {len(results)} results to {args.output.resolve()}")
    if not args.no_auto_check:
        print(f"Auto-check (仅供参考): {auto_passed}/{len(results)} passed")
    print("请打开 smoke_results.json 人工核对 answer / normalized / evidence。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
