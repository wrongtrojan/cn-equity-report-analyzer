"""MD&A chunk retrieval, ranking, and optional LLM classification."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from openai import OpenAI
from sentence_transformers import SentenceTransformer

from pipeline.db import connect, to_pgvector
from pipeline.item_aliases import expand_item_names

from pipeline.analysis.config.settings import (
    ANALYSIS_LLM_MODEL,
    EMBED_MODEL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    load_rules,
)
from pipeline.analysis.contracts import FlagExplanation, MetricFlag
from pipeline.analysis.readers import search_text_chunks_keyword

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
CAUSAL_MARKERS = ("由于", "主要系", "原因", "是因为", "得益于", "受")


@lru_cache(maxsize=1)
def _embedder() -> SentenceTransformer:
    return SentenceTransformer(EMBED_MODEL)


def _retrieve_chunks(
    report_id: int,
    query_text: str,
    section_keys: list[str],
    top_k: int,
) -> list[dict]:
    if not query_text.strip():
        return []

    try:
        vec = _embedder().encode(query_text, normalize_embeddings=True)
        vec_str = to_pgvector(vec.tolist())
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT tc.id, tc.section_key, tc.page_num, tc.content,
                       (tc.embedding <=> %s::vector) AS dist
                FROM text_chunks tc
                WHERE tc.report_id = %s
                  AND tc.section_key = ANY(%s)
                  AND tc.embedding IS NOT NULL
                ORDER BY dist
                LIMIT %s
                """,
                (vec_str, report_id, section_keys, top_k * 2),
            )
            rows = cur.fetchall()
        if rows:
            return [
                {
                    "chunk_id": row[0],
                    "section_key": row[1],
                    "page_num": row[2],
                    "content": row[3],
                    "score": max(0.0, 1.0 - float(row[4])),
                }
                for row in rows[:top_k]
            ]
    except Exception:
        pass

    keywords = expand_item_names([query_text.split()[0]]) if query_text else [query_text]
    return search_text_chunks_keyword(report_id, keywords, section_keys, limit=top_k)


def _rank_chunks(item_name: str, chunks: list[dict]) -> list[dict]:
    aliases = expand_item_names([item_name])
    ranked: list[tuple[float, dict]] = []
    for chunk in chunks:
        text = chunk.get("content") or ""
        score = float(chunk.get("score") or 0.0)
        if any(alias in text for alias in aliases):
            score += 0.30
        if re.search(r"[\d.]+%", text):
            score += 0.20
        if any(m in text for m in CAUSAL_MARKERS):
            score += 0.15
        ranked.append((score, {**chunk, "score": min(score, 1.0)}))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in ranked]


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
    return {"explanation_type": "indirect", "reason": "LLM 未返回有效 JSON"}


def _classify_explanation(flag_summary: str, chunk_text: str) -> dict:
    if not OPENAI_API_KEY or not chunk_text.strip():
        return {"explanation_type": "indirect", "reason": "基于关键词匹配"}

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    prompt = env.get_template("explain_flag.j2").render(
        flag_summary=flag_summary,
        chunk_text=chunk_text[:1500],
    )
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    resp = client.chat.completions.create(
        model=ANALYSIS_LLM_MODEL,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "你是财报分析助手，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        timeout=30,
    )
    raw = resp.choices[0].message.content or "{}"
    data = _extract_json(raw)
    expl_type = data.get("explanation_type", "indirect")
    if expl_type not in {"direct", "indirect", "none"}:
        expl_type = "indirect"
    return {"explanation_type": expl_type, "reason": str(data.get("reason") or "")}


def explain_flags(
    report_id: int,
    flags: list[MetricFlag],
    *,
    skip_llm: bool = False,
) -> None:
    explainer_cfg = load_rules().get("explainer", {})
    section_keys = explainer_cfg.get("section_keys", ["mda", "key_financials"])
    top_k = int(explainer_cfg.get("top_k", 5))
    min_relevance = float(explainer_cfg.get("min_relevance", 0.35))

    for flag in flags:
        query = f"{flag.item_name} {flag.period_label} 变动 原因"
        chunks = _retrieve_chunks(report_id, query, section_keys=section_keys, top_k=top_k)
        ranked = _rank_chunks(flag.item_name, chunks)
        explanations: list[FlagExplanation] = []

        for chunk in ranked[:3]:
            score = float(chunk.get("score") or 0.0)
            if score < min_relevance:
                continue
            expl_type = "indirect"
            reason = "文本与指标相关"
            if not skip_llm:
                cls = _classify_explanation(flag.summary, chunk.get("content") or "")
                expl_type = cls.get("explanation_type", expl_type)
                reason = cls.get("reason", reason)
            elif any(m in (chunk.get("content") or "") for m in CAUSAL_MARKERS):
                expl_type = "direct"
                reason = "文本包含变动原因表述"

            explanations.append(
                FlagExplanation(
                    chunk_id=chunk.get("chunk_id"),
                    snippet=(chunk.get("content") or "")[:500],
                    section_key=chunk.get("section_key"),
                    page_num=chunk.get("page_num"),
                    relevance_score=score,
                    explanation_type=expl_type,
                    reason=reason,
                )
            )

        if not explanations:
            explanations.append(
                FlagExplanation(
                    chunk_id=None,
                    snippet="",
                    section_key=None,
                    page_num=None,
                    relevance_score=0.0,
                    explanation_type="none",
                    reason="年报 MD&A 未找到对该指标的明确解释",
                )
            )
        flag.explanations = explanations
