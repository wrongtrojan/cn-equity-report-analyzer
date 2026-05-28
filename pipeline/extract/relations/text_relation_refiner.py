"""Optional text-based relation refiner (AutoRE-lite)."""

from __future__ import annotations

import logging
from typing import Iterable

from pipeline.extract.contracts import ExtractedEntity, ExtractedRelation, RelationEvidence, Section

from .llm_client import chat_json, get_client
from .relation_extract import _entity, _relation_key, normalize_entity_key
from .relation_validate import validate_relation

logger = logging.getLogger(__name__)

RELATION_ROUNDS = (
    "shareholder_of",
    "actual_controller_of",
    "executive_of",
    "director_of",
    "subsidiary_of",
    "related_party_of",
)

SECTION_KEYS = (
    "shareholder_section",
    "top10_shareholders",
    "directors_supervisors",
    "subsidiaries",
    "related_parties",
    "corporate_governance",
    "significant_matters",
)

SYSTEM_PROMPT = """你是年报关系抽取助手。只从给定文本中抽取明确陈述的关系，输出 JSON 数组。
每项格式：
{"subject_name":"","subject_type":"person|organization|subsidiary","object_name":"","relation_type":"","attrs":{}}
不要猜测、不要编造。没有则返回 []。

禁止抽取以下 subject：
- 合计、小计、总计
- 职务名（董事长、监事、职工代表监事、合规总监等）
- 会计科目（坏账准备、账面余额、其他应收款等）
- 表格汇总行或表头文字"""


def _section_text(sections: list[Section], keys: Iterable[str], max_chars: int = 6000) -> str:
    chunks: list[str] = []
    total = 0
    for sec in sections:
        if sec.section_key not in keys:
            continue
        text = sec.content_md.strip()
        if not text:
            continue
        if total + len(text) > max_chars:
            text = text[: max_chars - total]
        chunks.append(f"[{sec.section_key}] {sec.title_raw}\n{text}")
        total += len(text)
        if total >= max_chars:
            break
    return "\n\n".join(chunks)


def _merge_relations(
    registry: dict[str, ExtractedEntity],
    existing: dict[str, ExtractedRelation],
    additions: list[ExtractedRelation],
) -> int:
    added = 0
    for rel in additions:
        if rel.source_key in existing:
            continue
        if not validate_relation(rel):
            continue
        _entity(registry, rel.subject_name, rel.subject_type)
        _entity(registry, rel.object_name, rel.object_type)
        existing[rel.source_key] = rel
        added += 1
    return added


def refine_relations_from_text(
    sections: list[Section],
    company_name: str,
    entities: list[ExtractedEntity],
    relations: list[ExtractedRelation],
) -> tuple[list[ExtractedEntity], list[ExtractedRelation], dict[str, int]]:
    stats = {"api_calls": 0, "added_relations": 0, "skipped": 0}
    if get_client() is None:
        logger.warning("text_relation_refiner skipped: OPENAI_API_KEY not configured")
        stats["skipped"] = 1
        return entities, relations, stats

    registry = {e.entity_key: e for e in entities}
    relation_map = {r.source_key: r for r in relations}
    text = _section_text(sections, SECTION_KEYS)
    if not text.strip():
        return list(registry.values()), list(relation_map.values()), stats

    for relation_type in RELATION_ROUNDS:
        user_prompt = (
            f"公司: {company_name}\n"
            f"本轮只抽取 relation_type={relation_type}\n"
            f"object_name 通常是 {company_name}\n\n"
            f"文本:\n{text}"
        )
        try:
            payload = chat_json(SYSTEM_PROMPT, user_prompt)
            stats["api_calls"] += 1
        except Exception as exc:
            logger.warning("text_relation_refiner round %s failed: %s", relation_type, exc)
            continue

        if not isinstance(payload, list):
            continue

        additions: list[ExtractedRelation] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if item.get("relation_type") != relation_type:
                continue
            subject_name = str(item.get("subject_name", "")).strip()
            object_name = str(item.get("object_name", "")).strip() or company_name
            if not subject_name:
                continue
            subject_type = str(item.get("subject_type", "person"))
            object_type = "company" if object_name == company_name else str(item.get("object_type", "subsidiary"))
            subject_key = normalize_entity_key(subject_name)
            object_key = normalize_entity_key(object_name)
            attrs = item.get("attrs") if isinstance(item.get("attrs"), dict) else {}
            source_key = _relation_key(relation_type, subject_key, object_key, 0, "llm")
            additions.append(
                ExtractedRelation(
                    relation_type=relation_type,
                    subject_key=subject_key,
                    subject_name=subject_name,
                    subject_type=subject_type,
                    object_key=object_key,
                    object_name=object_name,
                    object_type=object_type,
                    attrs=attrs,
                    confidence=0.7,
                    source="llm",
                    source_key=source_key,
                    evidence=[
                        RelationEvidence(
                            evidence_type="section_text",
                            snippet=subject_name,
                            attrs={"relation_type": relation_type},
                        )
                    ],
                )
            )
        stats["added_relations"] += _merge_relations(registry, relation_map, additions)

    return list(registry.values()), list(relation_map.values()), stats
