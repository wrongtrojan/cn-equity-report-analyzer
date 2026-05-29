"""Analysis rules and env-backed settings."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import pipeline.env  # noqa: F401
import yaml

CONFIG_DIR = Path(__file__).resolve().parent

EMBED_MODEL = os.getenv("ANALYSIS_EMBED_MODEL", os.getenv("EMBED_MODEL", "BAAI/bge-m3"))
ANALYSIS_LLM_MODEL = os.getenv("ANALYSIS_LLM_MODEL", os.getenv("LLM_MODEL", "gpt-4o-mini"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")


@lru_cache(maxsize=1)
def load_rules() -> dict[str, Any]:
    path = CONFIG_DIR / "analysis_rules.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
