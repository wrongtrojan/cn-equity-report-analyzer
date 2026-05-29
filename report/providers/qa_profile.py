"""Fetch company intro and main business via QA pipeline."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pipeline.qa.core.engine import QAPipeline

REPORT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPORT_DIR / "output"

CACHE_VERSION = 1
INTRO_QUESTION = (
    "请简要介绍公司基本情况、上市背景与战略定位。"
    "不要列举具体主营业务条目或业务清单（主营业务将单独呈现）。"
)
BUSINESS_QUESTION = "公司主要业务有哪些"


def _split_business_tags(text: str | None) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[、，,；;\n]", text)
    tags = [p.strip().rstrip("等。") for p in parts if p.strip()]
    cleaned: list[str] = []
    for tag in tags:
        tag = re.sub(r"^[\d\.、\s]+", "", tag).strip()
        if len(tag) >= 2 and tag not in cleaned:
            cleaned.append(tag)
    return cleaned


def resolve_report_root(report_id: int, output_dir: Path | None = None) -> Path:
    if output_dir is None:
        return OUTPUT_DIR / f"report_{report_id}"
    if output_dir.name in {"overview", "graph", "analysis"}:
        return output_dir.parent
    return output_dir


def _cache_path(report_id: int, output_dir: Path | None = None) -> Path:
    return resolve_report_root(report_id, output_dir) / "qa_profile_cache.json"


def _cache_is_valid(data: dict) -> bool:
    return (
        data.get("version") == CACHE_VERSION
        and data.get("intro_question") == INTRO_QUESTION
        and data.get("business_question") == BUSINESS_QUESTION
    )


def load_qa_profile_cache(report_id: int, *, output_dir: Path | None = None) -> dict | None:
    path = _cache_path(report_id, output_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not _cache_is_valid(data):
        return None
    return {
        "intro": data.get("intro"),
        "main_business": data.get("main_business"),
        "main_business_tags": data.get("main_business_tags") or [],
        "profile_source": data.get("profile_source") or "qa",
        "intro_citations": data.get("intro_citations") or [],
        "business_citations": data.get("business_citations") or [],
        "from_cache": True,
    }


def save_qa_profile_cache(report_id: int, payload: dict, *, output_dir: Path | None = None) -> None:
    path = _cache_path(report_id, output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": CACHE_VERSION,
        "intro_question": INTRO_QUESTION,
        "business_question": BUSINESS_QUESTION,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "intro": payload.get("intro"),
        "main_business": payload.get("main_business"),
        "main_business_tags": payload.get("main_business_tags") or [],
        "profile_source": payload.get("profile_source") or "qa",
        "intro_citations": payload.get("intro_citations") or [],
        "business_citations": payload.get("business_citations") or [],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_qa_profile(
    report_id: int,
    *,
    force: bool = False,
    output_dir: Path | None = None,
) -> dict:
    """Run fixed QA questions; return intro/business fields or empty on failure."""
    out = {
        "intro": None,
        "main_business": None,
        "main_business_tags": [],
        "profile_source": "regex",
        "intro_citations": [],
        "business_citations": [],
    }
    if not force:
        cached = load_qa_profile_cache(report_id, output_dir=output_dir)
        if cached:
            return cached

    try:
        pipeline = QAPipeline()
        session = pipeline.load_session(report_id)

        intro_resp = pipeline.ask(session, INTRO_QUESTION)
        intro_answer = (intro_resp.answer or "").strip()
        if intro_answer:
            out["intro"] = intro_answer
            out["intro_citations"] = intro_resp.citations or []
            out["profile_source"] = "qa"

        business_resp = pipeline.ask(session, BUSINESS_QUESTION)
        business_answer = (business_resp.answer or "").strip()
        if business_answer:
            out["main_business"] = business_answer
            out["main_business_tags"] = _split_business_tags(business_answer)
            out["business_citations"] = business_resp.citations or []
            out["profile_source"] = "qa"
    except Exception:
        pass

    if out.get("intro") or out.get("main_business"):
        save_qa_profile_cache(report_id, out, output_dir=output_dir)
    return out
