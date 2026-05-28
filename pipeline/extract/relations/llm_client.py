"""OpenAI-compatible chat client for extract-layer LLM tasks."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import pipeline.env  # noqa: F401
from openai import OpenAI


def llm_model() -> str:
    return os.getenv("RE_LLM_MODEL") or os.getenv("LLM_MODEL") or os.getenv("QA_LLM_MODEL") or "gpt-4o-mini"


def get_client() -> OpenAI | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        return None
    return OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))


def _extract_json(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"[\[{][\s\S]*[\]}]", text)
        if not match:
            raise ValueError("LLM did not return valid JSON")
        return json.loads(match.group(0))


def chat_json(system_prompt: str, user_prompt: str, *, model: str | None = None, timeout: float = 90.0) -> Any:
    client = get_client()
    if client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured in project-root .env")

    response = client.chat.completions.create(
        model=model or llm_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        timeout=timeout,
    )
    content = response.choices[0].message.content or ""
    return _extract_json(content)
