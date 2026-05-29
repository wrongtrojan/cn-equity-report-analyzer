"""Operating analysis package."""

from __future__ import annotations

import pipeline.env  # noqa: F401

from pipeline.analysis.contracts import OperatingAnalysisResult
from pipeline.analysis.pipeline import run_pipeline
from pipeline.analysis.readers import load_latest_analysis

__all__ = ["run_analysis", "load_latest_analysis"]


def run_analysis(report_id: int, *, skip_llm: bool = False) -> OperatingAnalysisResult:
    _, result = run_pipeline(report_id, skip_llm=skip_llm)
    return result
