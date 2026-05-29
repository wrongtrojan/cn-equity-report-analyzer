# pipeline/qa/llm.py
"""LLM 客户端：查询标准化与答案生成。"""

from __future__ import annotations

import json
import re
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from openai import OpenAI

from ..config import (
    ANSWER_TIMEOUT_SEC,
    NORMALIZE_TIMEOUT_SEC,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    QA_LLM_MODEL,
    TEMPLATE_DIR,
)
from .scoring import AnswerGenerationResult, is_comprehensive_query
from ..schemas import NormalizedQuery


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("LLM did not return valid JSON")
    return json.loads(match.group(0))


class LLMClient:
    def __init__(self) -> None:
        self.client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
        self.model = QA_LLM_MODEL
        self.jinja = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def _render(self, template_name: str, **kwargs: Any) -> str:
        template = self.jinja.get_template(template_name)
        return template.render(**kwargs)

    def normalize_query(
        self,
        query: str,
        report_id: int,
        company_name: str,
        report_year: int | None,
        recent_turn_summaries: list[str],
    ) -> NormalizedQuery:
        prompt = self._render(
            "query_normalize.j2",
            query=query,
            report_id=report_id,
            company_name=company_name,
            report_year=report_year,
            recent_turn_summaries=recent_turn_summaries,
        )

        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "你是财报问答系统的查询标准化器，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            timeout=NORMALIZE_TIMEOUT_SEC,
        )
        raw = resp.choices[0].message.content or "{}"
        data = _extract_json(raw)
        return NormalizedQuery.model_validate(data)

    def answer_question(
        self,
        canonical_question: str,
        evidence_bundle: list[dict[str, Any]],
        recent_turn_summaries: list[str],
        *,
        intent: str = "hybrid",
    ) -> AnswerGenerationResult:
        evidence_json = json.dumps(evidence_bundle, ensure_ascii=False, indent=2)
        comprehensive = is_comprehensive_query(canonical_question, intent)
        prompt = self._render(
            "answer_generate.j2",
            canonical_question=canonical_question,
            evidence_json=evidence_json,
            recent_turn_summaries=recent_turn_summaries,
            intent=intent,
            is_comprehensive=comprehensive,
        )

        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0.25 if comprehensive else 0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "你是财报问答助手，必须基于证据回答，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            timeout=ANSWER_TIMEOUT_SEC,
        )
        raw = resp.choices[0].message.content or "{}"
        data = _extract_json(raw)
        answer = _strip_answer_wrappers(str(data.get("answer") or "").strip())
        level = str(data.get("confidence_level") or "none")
        if level not in {"high", "medium", "low", "none"}:
            level = "none"
        try:
            score = float(data.get("confidence_score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))
        reason = str(data.get("reason") or "").strip()
        return AnswerGenerationResult(
            answer=answer,
            confidence_level=level,  # type: ignore[arg-type]
            confidence_score=score,
            reason=reason,
        )


def _strip_answer_wrappers(text: str) -> str:
    """Remove legacy headings if the model still echoes them."""
    lines = text.splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped in {"回答：", "回答:", "引用来源：", "引用来源:"}:
            continue
        if stripped.startswith("引用来源"):
            break
        cleaned.append(line)
    return "\n".join(cleaned).strip()
