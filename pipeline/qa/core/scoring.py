"""Evidence strength, confidence fusion, and dynamic evidence budget."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..config import MAX_EVIDENCE, MAX_EVIDENCE_CAP
from ..schemas import AnswerConfidence, ConfidenceLevel, EvidenceItem, NormalizedQuery

ROLE_KEYWORDS = (
    "监事会主席",
    "董事长",
    "副董事长",
    "总经理",
    "副总经理",
    "财务总监",
    "董事会秘书",
    "总裁",
    "首席执行官",
    "职工代表监事",
    "独立董事",
    "董事",
    "监事",
)

WITHHELD_MARKERS = ("年报未披露", "未披露", "无法确定", "无法回答")
QUALIFIER_MARKERS = ("但", "然而", "不过", "未明确", "未能", "可能", "尚无法", "已离任", "离任", "不确定")
COMPREHENSIVE_QUERY = re.compile(
    r"概况|整体|综合|哪些方面|分别|以及|并.*(分析|说明|介绍)|介绍.*公司|基本情况|怎么样|如何|怎样"
)

LEVEL_ORDER: dict[ConfidenceLevel, int] = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}

MIN_EVIDENCE = 4
ComplexityTier = Literal["simple", "moderate", "complex"]

_SUBQUESTION_MARKERS = re.compile(r"分别|以及|和|与|及")
_MULTI_ASPECT = re.compile(r"哪些方面|整体|概况|综合|介绍.*公司|基本情况|基本信息|公司信息")


@dataclass
class EvidenceStrength:
    score: float
    signals: list[str]
    direct_support: bool = False
    source_types: int = 0


@dataclass
class AnswerGenerationResult:
    answer: str
    confidence_level: ConfidenceLevel
    confidence_score: float
    reason: str = ""


@dataclass
class EvidenceBudget:
    max_items: int
    tier: ComplexityTier
    score: int
    signals: list[str]


@dataclass
class RetrievalLimits:
    vector_top_k: int = 0
    sql_top_k: int = 0
    kg_top_k: int = 0


def score_to_level(score: float) -> ConfidenceLevel:
    if score >= 0.78:
        return "high"
    if score >= 0.52:
        return "medium"
    if score >= 0.28:
        return "low"
    return "none"


def is_comprehensive_query(query: str, intent: str) -> bool:
    if intent == "hybrid":
        return True
    return bool(COMPREHENSIVE_QUERY.search(query or ""))


def extract_role_keywords(text: str) -> list[str]:
    matched = [kw for kw in ROLE_KEYWORDS if kw in text]
    matched.sort(key=len, reverse=True)
    return matched


def is_withheld_answer(answer: str) -> bool:
    text = (answer or "").strip()
    if not text:
        return True
    if "已知线索" in text or "相关线索" in text:
        return True
    first_line = text.splitlines()[0].strip()
    if any(marker in first_line for marker in WITHHELD_MARKERS):
        return True
    if any(marker in text for marker in WITHHELD_MARKERS) and len(text) <= 64:
        return True
    return False


def answer_has_qualifiers(answer: str) -> bool:
    return any(marker in (answer or "") for marker in QUALIFIER_MARKERS)


def _title_from_evidence(item: EvidenceItem) -> str:
    if item.source_type != "kg_relation":
        return ""
    attrs = item.metadata.get("attrs") or {}
    return str(attrs.get("title") or "")


def _content_mentions_query_terms(query: str, item: EvidenceItem) -> bool:
    content = item.content or ""
    for kw in extract_role_keywords(query):
        if kw in content or kw in _title_from_evidence(item):
            return True
    address_markers = ("注册地址", "注册地", "住所", "办公地址")
    if any(m in query for m in address_markers):
        return any(m in content for m in address_markers)
    return False


def compute_evidence_strength(
    normalized: NormalizedQuery,
    evidence: list[EvidenceItem],
) -> EvidenceStrength:
    if not evidence:
        return EvidenceStrength(score=0.0, signals=["无可用证据"], direct_support=False, source_types=0)

    query = normalized.canonical_question or ""
    source_types = len({item.source_type for item in evidence})
    max_score = max(item.score for item in evidence)
    avg_score = sum(item.score for item in evidence) / len(evidence)
    signals = [f"最高证据分 {max_score:.2f}"]
    score = max_score * 0.65 + avg_score * 0.35
    direct_support = False

    signals.append(f"证据 {len(evidence)} 条")
    if source_types >= 2:
        score = min(1.0, score + 0.08 * (source_types - 1))
        signals.append(f"证据来源 {source_types} 类")

    relevant_hits = sum(1 for item in evidence if _content_mentions_query_terms(query, item))
    if relevant_hits:
        direct_support = True
        ratio = relevant_hits / len(evidence)
        score = min(1.0, score + 0.12 + ratio * 0.18)
        signals.append(f"与问题相关的证据 {relevant_hits}/{len(evidence)} 条")

    query_roles = extract_role_keywords(query)
    matched_titles: list[str] = []
    if normalized.intent == "relational" and query_roles:
        for item in evidence:
            title = _title_from_evidence(item)
            if title and any(role in title or title in role for role in query_roles):
                matched_titles.append(title)
        if matched_titles:
            direct_support = True
            score = min(1.0, score + 0.18)
            signals.append(f"职务匹配: {', '.join(sorted(set(matched_titles)))}")
        elif any(item.source_type == "kg_relation" for item in evidence):
            score = min(score, 0.58)
            signals.append("关系证据存在但未直接匹配所问职务")

    if is_comprehensive_query(query, normalized.intent):
        if source_types < 2:
            score = min(score, 0.68)
            signals.append("综合性问题但证据来源较单一")
        else:
            score = min(score, 0.82)
            signals.append("综合性问题，需多源交叉验证")

    return EvidenceStrength(
        score=min(score, 1.0),
        signals=signals,
        direct_support=direct_support,
        source_types=source_types,
    )


def _min_level(a: ConfidenceLevel, b: ConfidenceLevel) -> ConfidenceLevel:
    return a if LEVEL_ORDER[a] <= LEVEL_ORDER[b] else b


def _max_level(a: ConfidenceLevel, b: ConfidenceLevel) -> ConfidenceLevel:
    return a if LEVEL_ORDER[a] >= LEVEL_ORDER[b] else b


def _blend_scores(
    llm_score: float,
    evidence_score: float,
    *,
    comprehensive: bool,
) -> float:
    evidence_weight = 0.58 if comprehensive else 0.48
    blended = (1 - evidence_weight) * llm_score + evidence_weight * evidence_score
    return min(llm_score, blended + 0.06)


def fuse_confidence(
    normalized: NormalizedQuery,
    evidence: list[EvidenceItem],
    generated: AnswerGenerationResult,
    evidence_strength: EvidenceStrength,
) -> AnswerConfidence:
    llm_score = max(0.0, min(1.0, generated.confidence_score))
    evidence_score = evidence_strength.score
    query = normalized.canonical_question or ""
    comprehensive = is_comprehensive_query(query, normalized.intent)

    if not evidence:
        final_score = llm_score
        level = score_to_level(final_score)
        level = _min_level(level, generated.confidence_level)
        reason = generated.reason.strip() or "；".join(evidence_strength.signals)
        return AnswerConfidence(level=level, score=round(final_score, 2), reason=reason)

    capped_score = _blend_scores(llm_score, evidence_score, comprehensive=comprehensive)
    withheld = is_withheld_answer(generated.answer)

    if withheld or generated.confidence_level == "none":
        if evidence_strength.direct_support:
            final_score = max(capped_score, min(0.62, evidence_score * 0.9))
            level = _max_level(score_to_level(final_score), "medium")
        else:
            final_score = max(capped_score, min(0.48, 0.28 + evidence_score * 0.32))
            level = _max_level(score_to_level(final_score), "low")

        reason_parts: list[str] = []
        if generated.reason.strip():
            reason_parts.append(generated.reason.strip())
        if withheld:
            reason_parts.append(f"已检索 {len(evidence)} 条证据，但未形成可直接作答的结论")
        if evidence_strength.signals:
            reason_parts.append("；".join(evidence_strength.signals))
        reason = "。".join(reason_parts)
        return AnswerConfidence(level=level, score=round(final_score, 2), reason=reason)

    final_score = capped_score
    level = score_to_level(final_score)
    level = _min_level(level, generated.confidence_level)

    if answer_has_qualifiers(generated.answer):
        final_score = min(final_score, 0.72)
        level = _min_level(level, "medium")

    if comprehensive:
        if evidence_strength.source_types < 2:
            final_score = min(final_score, 0.68)
            level = _min_level(level, "medium")
        elif not evidence_strength.direct_support:
            final_score = min(final_score, 0.75)
            level = _min_level(level, "medium")

    query_roles = extract_role_keywords(query)
    if normalized.intent == "relational" and query_roles:
        has_title_match = any(
            _title_from_evidence(item)
            and any(role in _title_from_evidence(item) or _title_from_evidence(item) in role for role in query_roles)
            for item in evidence
        )
        if not has_title_match and evidence:
            final_score = min(final_score, 0.65)
            level = _min_level(level, "medium")

    if level == "high" and final_score < 0.78:
        level = "medium"

    reason = generated.reason.strip()
    if final_score < llm_score - 0.05:
        cap_note = "系统根据证据强度与问题类型做了置信度校准。"
        reason = f"{reason} {cap_note}".strip() if reason else cap_note
    if not reason and evidence_strength.signals:
        reason = "；".join(evidence_strength.signals)

    return AnswerConfidence(level=level, score=round(final_score, 2), reason=reason)


def _complexity_score(normalized: NormalizedQuery, question: str) -> tuple[int, list[str]]:
    q = (question or normalized.canonical_question or "").strip()
    score = 0
    signals: list[str] = []

    sub_q = len(_SUBQUESTION_MARKERS.findall(q))
    if sub_q:
        delta = min(sub_q, 3)
        score += delta
        signals.append(f"连接词/多子问 x{delta}")

    item_names = [name for name in normalized.sql_targets.item_names if name and name.strip()]
    if len(item_names) >= 2:
        delta = min(len(item_names) - 1, 3)
        score += delta
        signals.append(f"多指标 x{len(item_names)}")

    section_keys = [key for key in normalized.section_keys if key]
    if len(section_keys) >= 3:
        score += 1
        signals.append(f"多章节 x{len(section_keys)}")

    entities = [entity for entity in normalized.entities if entity and len(entity.strip()) >= 2]
    if len(entities) >= 2:
        score += 1
        signals.append(f"多实体 x{len(entities)}")

    if is_comprehensive_query(q, normalized.intent):
        score += 2
        signals.append("综合性表述")

    if _MULTI_ASPECT.search(q):
        score += 1
        signals.append("多维度问题")

    route_count = sum(
        [
            normalized.intent in {"numeric", "hybrid"},
            normalized.intent in {"narrative", "hybrid"},
            normalized.intent in {"relational", "hybrid"},
        ]
    )
    if normalized.intent == "hybrid":
        score += 1
        signals.append("hybrid 多路检索")
    elif route_count == 1 and normalized.intent == "relational":
        score += max(0, len(normalized.sql_targets.item_names) // 2)

    return score, signals


def _tier_from_score(score: int) -> ComplexityTier:
    if score <= 1:
        return "simple"
    if score <= 4:
        return "moderate"
    return "complex"


def compute_evidence_budget(
    normalized: NormalizedQuery,
    question: str,
    *,
    base: int | None = None,
    cap: int | None = None,
) -> EvidenceBudget:
    base = base if base is not None else MAX_EVIDENCE
    cap = cap if cap is not None else MAX_EVIDENCE_CAP
    score, signals = _complexity_score(normalized, question)
    tier = _tier_from_score(score)
    intent = normalized.intent

    if intent == "numeric":
        max_items = base
    elif intent == "narrative":
        if tier == "complex":
            max_items = base + 4
        elif tier == "moderate":
            max_items = base + 3
        else:
            max_items = base + (1 if score >= 2 else 0)
    elif intent == "relational":
        max_items = base + min(score, 2)
    elif intent == "hybrid":
        if tier == "simple":
            max_items = base + 1
        elif tier == "moderate":
            max_items = base + 3 + min(score - 2, 2)
        else:
            max_items = base + 6 + min(score - 5, 2)
    else:
        max_items = base + min(score, 4)

    max_items = max(MIN_EVIDENCE, min(max_items, cap))
    signals = [f"复杂度 {tier} (score={score})", *signals, f"证据预算 {max_items} 条"]
    return EvidenceBudget(max_items=max_items, tier=tier, score=score, signals=signals)


def allocate_retrieval_limits(budget: EvidenceBudget, route) -> RetrievalLimits:
    """Split fetch budget across active retrieval channels."""
    channels: list[tuple[str, float]] = []
    if route.use_sql:
        channels.append(("sql", 1.0))
    if route.use_vector:
        channels.append(("vector", 2.0))
    if route.use_kg:
        channels.append(("kg", 1.0))

    if not channels:
        return RetrievalLimits()

    if len(channels) == 1:
        name = channels[0][0]
        limit = budget.max_items
        if name == "vector":
            return RetrievalLimits(vector_top_k=limit)
        if name == "sql":
            return RetrievalLimits(sql_top_k=limit)
        return RetrievalLimits(kg_top_k=limit)

    total_weight = sum(weight for _, weight in channels)
    raw: dict[str, int] = {}
    for name, weight in channels:
        raw[name] = max(2, round(budget.max_items * weight / total_weight))

    while sum(raw.values()) < budget.max_items:
        for name, _ in channels:
            raw[name] += 1
            if sum(raw.values()) >= budget.max_items:
                break

    return RetrievalLimits(
        vector_top_k=raw.get("vector", 0),
        sql_top_k=raw.get("sql", 0),
        kg_top_k=raw.get("kg", 0),
    )
