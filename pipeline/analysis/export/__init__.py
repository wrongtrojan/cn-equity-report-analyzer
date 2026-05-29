"""Backward-compatible re-export; prefer pipeline.analysis."""

from pipeline.analysis import load_latest_analysis, run_analysis

__all__ = ["load_latest_analysis", "run_analysis"]
