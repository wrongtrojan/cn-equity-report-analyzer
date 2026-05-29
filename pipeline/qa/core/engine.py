from __future__ import annotations

import re
from dataclasses import dataclass, field

from pipeline.db import connect

from ..config import MAX_SESSION_TURNS
from ..retrieval import KGRetriever, SQLRetriever, VectorRetriever, merge_evidence
from ..schemas import NormalizedQuery, QAResponse, SQLTargets
from .llm import LLMClient
from .normalize import (
    _resolve_period_labels,
    default_period_kinds,
    default_stmt_types,
    enrich_normalized,
    infer_granularity,
)
from .scoring import allocate_retrieval_limits, compute_evidence_budget, compute_evidence_strength, fuse_confidence


@dataclass
class Turn:
    question: str
    normalized: NormalizedQuery
    answer: str
    citations: list[str]

    def summary(self) -> str:
        return f"Q: {self.question} | Intent: {self.normalized.intent} | A: {self.answer[:80]}"


@dataclass
class QASession:
    report_id: int
    company_name: str
    report_year: int | None
    turns: list[Turn] = field(default_factory=list)
    max_turns: int = MAX_SESSION_TURNS

    def add_turn(self, turn: Turn) -> None:
        self.turns.append(turn)
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns :]

    def recent_summaries(self, n: int = 3) -> list[str]:
        return [t.summary() for t in self.turns[-n:]]

    def clear(self) -> None:
        self.turns.clear()


@dataclass
class ReportSummary:
    report_id: int
    stock_code: str
    stock_name: str
    report_year: int
    report_type: str
    parse_status: str
    title: str | None = None


@dataclass
class RouteDecision:
    use_sql: bool
    use_vector: bool
    use_kg: bool


def decide_route(normalized: NormalizedQuery) -> RouteDecision:
    intent = normalized.intent
    if intent == "numeric":
        return RouteDecision(use_sql=True, use_vector=False, use_kg=False)
    if intent == "narrative":
        return RouteDecision(use_sql=False, use_vector=True, use_kg=False)
    if intent == "relational":
        return RouteDecision(use_sql=True, use_vector=False, use_kg=True)
    return RouteDecision(use_sql=True, use_vector=True, use_kg=True)


def _fallback_normalize(query: str, report_year: int | None) -> NormalizedQuery:
    q = query.strip()
    q_lower = q.lower()
    if any(k in q for k in ["净利润", "收入", "营收", "同比", "金额", "多少"]):
        intent = "numeric"
        entities = [x for x in ["营业总收入", "净利润", "经营活动产生的现金流量净额"] if x in q]
        granularity = infer_granularity(q)
        period_labels = _resolve_period_labels(q, granularity, report_year, [])
        return NormalizedQuery(
            intent=intent,
            canonical_question=q,
            report_year=report_year,
            entities=entities,
            section_keys=(
                ["quarterly_financials"]
                if granularity == "quarterly"
                else ["key_financials", "financial_statements"]
            ),
            sql_targets=SQLTargets(
                item_names=entities,
                period_labels=period_labels,
                period_kinds=default_period_kinds(granularity),
                stmt_types=default_stmt_types(granularity),
                period_granularity=granularity,
            ),
            vector_query=q,
            needs_previous_context=False,
        )
    if any(k in q_lower for k in ["股东", "子公司", "高管", "关联方"]):
        return NormalizedQuery(
            intent="relational",
            canonical_question=q,
            report_year=report_year,
            entities=[q],
            section_keys=["top10_shareholders", "subsidiaries", "directors_supervisors"],
            vector_query=q,
            needs_previous_context=False,
        )
    return NormalizedQuery(
        intent="narrative",
        canonical_question=q,
        report_year=report_year,
        entities=[],
        section_keys=["mda"],
        vector_query=q,
        needs_previous_context=False,
    )


def _citations_from_evidence(evidence: list) -> list[str]:
    citations: list[str] = []
    for e in evidence:
        section = e.section_key or "unknown"
        if e.page_num is not None:
            citations.append(f"[{section} p.{e.page_num}]")
        else:
            citations.append(f"[{section}]")
    dedup: list[str] = []
    for c in citations:
        if c not in dedup:
            dedup.append(c)
    return dedup


class QAPipeline:
    def __init__(self) -> None:
        self.llm = LLMClient()
        self.sql_retriever = SQLRetriever()
        self.vector_retriever = VectorRetriever()
        self.kg_retriever = KGRetriever()

    def load_session(self, report_id: int) -> QASession:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.stock_name, r.report_year
                FROM reports r
                JOIN companies c ON c.id = r.company_id
                WHERE r.id = %s
                """,
                (report_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"report_id not found: {report_id}")
        return QASession(report_id=report_id, company_name=row[0], report_year=row[1])

    def list_reports(self) -> list[ReportSummary]:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.id, c.stock_code, c.stock_name, r.report_year,
                       r.report_type, r.parse_status, r.title
                FROM reports r
                JOIN companies c ON c.id = r.company_id
                ORDER BY r.report_year DESC, r.id DESC
                """
            )
            rows = cur.fetchall()
        return [
            ReportSummary(
                report_id=row[0],
                stock_code=row[1],
                stock_name=row[2],
                report_year=row[3],
                report_type=row[4],
                parse_status=row[5],
                title=row[6],
            )
            for row in rows
        ]

    def ask(self, session: QASession, question: str) -> QAResponse:
        try:
            normalized = self.llm.normalize_query(
                query=question,
                report_id=session.report_id,
                company_name=session.company_name,
                report_year=session.report_year,
                recent_turn_summaries=session.recent_summaries(3),
            )
        except Exception:
            normalized = _fallback_normalize(question, session.report_year)

        normalized = enrich_normalized(normalized, question, session.report_year)

        budget = compute_evidence_budget(normalized, question)
        route = decide_route(normalized)
        limits = allocate_retrieval_limits(budget, route)

        sql_items = (
            self.sql_retriever.retrieve(session.report_id, normalized, top_k=limits.sql_top_k or None)
            if route.use_sql
            else []
        )
        vec_items = (
            self.vector_retriever.retrieve(
                session.report_id,
                normalized.vector_query,
                section_keys=normalized.section_keys
                if normalized.intent in {"narrative", "hybrid"}
                else None,
                top_k=limits.vector_top_k or None,
            )
            if route.use_vector
            else []
        )
        kg_items = (
            self.kg_retriever.retrieve(session.report_id, normalized, top_k=limits.kg_top_k or None)
            if route.use_kg
            else []
        )
        merged = merge_evidence(sql_items, vec_items, kg_items, max_items=budget.max_items)

        evidence_bundle = [e.model_dump() for e in merged]
        evidence_strength = compute_evidence_strength(normalized, merged)
        generated = self.llm.answer_question(
            canonical_question=normalized.canonical_question,
            evidence_bundle=evidence_bundle,
            recent_turn_summaries=session.recent_summaries(3),
            intent=normalized.intent,
        )
        confidence = fuse_confidence(normalized, merged, generated, evidence_strength)
        citations = _citations_from_evidence(merged)

        response = QAResponse(
            answer=generated.answer,
            confidence=confidence,
            citations=citations,
            normalized=normalized,
            evidence=merged,
        )
        session.add_turn(
            Turn(
                question=question,
                normalized=normalized,
                answer=response.answer,
                citations=response.citations,
            )
        )
        return response
