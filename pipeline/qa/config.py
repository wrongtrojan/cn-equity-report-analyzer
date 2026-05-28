from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from pipeline.ingest.config import DATABASE_URL, EMBED_MODEL

QA_DIR = Path(__file__).resolve().parent
QA_ENV_PATH = QA_DIR / ".env"
if QA_ENV_PATH.exists():
    # Load qa/.env by default; allow shell env override.
    load_dotenv(QA_ENV_PATH, override=False)


def env_str(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise RuntimeError(
            f"Missing required env: {name}. Set it in {QA_ENV_PATH} or export it in shell."
        )
    return value

TEMPLATE_DIR = QA_DIR / "templates"

# LLM config (from pipeline/qa/.env by default)
OPENAI_API_KEY = env_str("OPENAI_API_KEY", required=True)
OPENAI_BASE_URL = env_str("OPENAI_BASE_URL", "https://api.openai.com/v1")
QA_LLM_MODEL = env_str("QA_LLM_MODEL", "gpt-4o-mini")

# Retrieval and session knobs
SQL_TOP_K = int(env_str("QA_SQL_TOP_K", "5") or "5")
VECTOR_TOP_K = int(env_str("QA_VECTOR_TOP_K", "5") or "5")
MAX_EVIDENCE = int(env_str("QA_MAX_EVIDENCE", "8") or "8")
MAX_SESSION_TURNS = int(env_str("QA_MAX_SESSION_TURNS", "5") or "5")

# Shared settings
DB_DSN = DATABASE_URL
QUERY_EMBED_MODEL = env_str("EMBED_MODEL", EMBED_MODEL) or EMBED_MODEL

# Timeouts
NORMALIZE_TIMEOUT_SEC = float(env_str("QA_NORMALIZE_TIMEOUT", "60") or "60")
ANSWER_TIMEOUT_SEC = float(env_str("QA_ANSWER_TIMEOUT", "90") or "90")

