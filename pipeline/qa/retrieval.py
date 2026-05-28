# pipeline/qa/retrieval.py
"""证据检索：SQL 事实、向量切块、KG 占位与证据合并。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable

from pipeline.ingest.db import connect, to_pgvector
from pipeline.ingest.item_aliases import expand_item_names
from sentence_transformers import SentenceTransformer

from .config import MAX_EVIDENCE, QUERY_EMBED_MODEL, SQL_TOP_K, VECTOR_TOP_K
from .normalize import fact_rank_score
from .schemas import EvidenceItem, NormalizedQuery


def _first_non_empty(values: Iterable[str]) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


SOURCE_PRIORITY = {
    "financial_fact": 0,
    "structured_table": 1,
    "kg_relation": 2,
    "text_chunk": 3,
}


def _evidence_key(item: EvidenceItem) -> str:
    data = f"{item.source_type}|{item.section_key}|{item.page_num}|{item.content[:160]}"
    return hashlib.sha1(data.encode("utf-8")).hexdigest()


def merge_evidence(*evidence_groups: list[EvidenceItem], max_items: int = MAX_EVIDENCE) -> list[EvidenceItem]:
    merged: list[EvidenceItem] = []
    seen: set[str] = set()

    for group in evidence_groups:
        for item in group:
            key = _evidence_key(item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

    merged.sort(
        key=lambda x: (
            SOURCE_PRIORITY.get(x.source_type, 99),
            -float(x.score),
            x.page_num if x.page_num is not None else 10**9,
        )
    )
    return merged[:max_items]


class SQLRetriever:
    def __init__(self, top_k: int = SQL_TOP_K) -> None:
        self.top_k = top_k

    def retrieve(self, report_id: int, normalized: NormalizedQuery) -> list[EvidenceItem]:
        items: list[EvidenceItem] = []
        items.extend(self._retrieve_financial_facts(report_id, normalized))
        if normalized.intent in ("relational", "hybrid"):
            items.extend(self._retrieve_structured_tables(report_id, normalized))
        return items

    def _retrieve_financial_facts(
        self, report_id: int, normalized: NormalizedQuery
    ) -> list[EvidenceItem]:
        item_names = normalized.sql_targets.item_names or normalized.entities
        if not item_names:
            return []

        item_names = expand_item_names(list(item_names))
        prefer_ratio = bool(re.search(r"比例|占比|%", normalized.canonical_question))

        period_labels = normalized.sql_targets.period_labels
        period_kinds = normalized.sql_targets.period_kinds
        stmt_types = normalized.sql_targets.stmt_types
        granularity = normalized.sql_targets.period_granularity

        params: list = [report_id]
        filters = ["ff.report_id = %s", "(" + " OR ".join(["ff.item_name ILIKE %s"] * len(item_names)) + ")"]
        params.extend(f"%{x}%" for x in item_names)

        if period_kinds:
            filters.append("ff.period_kind = ANY(%s)")
            params.append(period_kinds)
        if stmt_types:
            filters.append("ff.stmt_type = ANY(%s)")
            params.append(stmt_types)
        if prefer_ratio:
            filters.append("ff.is_ratio = true")

        sql = f"""
            SELECT ff.item_name, ff.period_label, ff.amount, ff.unit, ff.page_num,
                   ff.stmt_type, ff.period_kind, ff.is_ratio, st.table_type_guess, st.section_key
            FROM financial_facts ff
            LEFT JOIN structured_tables st ON st.id = ff.table_id
            WHERE {" AND ".join(filters)}
            LIMIT %s
        """
        params.append(self.top_k * 10)

        with connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        if prefer_ratio and not rows:
            return self._retrieve_financial_facts_fallback(report_id, normalized, item_names)

        candidates: list[EvidenceItem] = []
        for (
            item_name,
            period_label,
            amount,
            unit,
            page_num,
            stmt_type,
            period_kind,
            is_ratio,
            table_type,
            section_key,
        ) in rows:
            if period_labels and period_label not in period_labels:
                continue
            if granularity == "annual" and period_kind == "quarter":
                continue
            if granularity == "quarterly" and period_kind != "quarter":
                continue

            score = fact_rank_score(stmt_type, period_kind, table_type, granularity)
            if is_ratio:
                score += 0.2
            period_hint = period_label
            if period_kind == "quarter":
                period_hint = f"{period_label}(季度)"
            elif period_kind == "point_in_time":
                period_hint = f"{period_label}(时点)"

            display_unit = unit or ("%" if is_ratio else "元")
            if is_ratio and display_unit != "%":
                display_unit = "%"
            text = f"[{stmt_type}/{period_kind}] {period_hint} {item_name} = {amount} {display_unit}"
            candidates.append(
                EvidenceItem(
                    source_type="financial_fact",
                    content=text,
                    section_key=section_key or table_type or "key_financials",
                    page_num=page_num,
                    score=score,
                    metadata={
                        "item_name": item_name,
                        "period_label": period_label,
                        "period_kind": period_kind,
                        "stmt_type": stmt_type,
                        "table_type_guess": table_type,
                        "is_ratio": is_ratio,
                    },
                )
            )

        candidates.sort(key=lambda x: (-x.score, x.metadata.get("period_label", ""), x.metadata.get("item_name", "")))
        return candidates[: self.top_k]

    def _retrieve_financial_facts_fallback(
        self,
        report_id: int,
        normalized: NormalizedQuery,
        item_names: list[str],
    ) -> list[EvidenceItem]:
        """比例问句未命中 is_ratio 时，去掉该过滤重试一次。"""
        granularity = normalized.sql_targets.period_granularity
        period_labels = normalized.sql_targets.period_labels
        period_kinds = normalized.sql_targets.period_kinds
        stmt_types = normalized.sql_targets.stmt_types
        params: list = [report_id]
        filters = ["ff.report_id = %s", "(" + " OR ".join(["ff.item_name ILIKE %s"] * len(item_names)) + ")"]
        params.extend(f"%{x}%" for x in item_names)
        if period_kinds:
            filters.append("ff.period_kind = ANY(%s)")
            params.append(period_kinds)
        if stmt_types:
            filters.append("ff.stmt_type = ANY(%s)")
            params.append(stmt_types)
        sql = f"""
            SELECT ff.item_name, ff.period_label, ff.amount, ff.unit, ff.page_num,
                   ff.stmt_type, ff.period_kind, ff.is_ratio, st.table_type_guess, st.section_key
            FROM financial_facts ff
            LEFT JOIN structured_tables st ON st.id = ff.table_id
            WHERE {" AND ".join(filters)}
            LIMIT %s
        """
        params.append(self.top_k * 10)
        with connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        candidates: list[EvidenceItem] = []
        for (
            item_name,
            period_label,
            amount,
            unit,
            page_num,
            stmt_type,
            period_kind,
            is_ratio,
            table_type,
            section_key,
        ) in rows:
            if period_labels and period_label not in period_labels:
                continue
            if granularity == "annual" and period_kind == "quarter":
                continue
            if granularity == "quarterly" and period_kind != "quarter":
                continue
            score = fact_rank_score(stmt_type, period_kind, table_type, granularity)
            if is_ratio:
                score += 0.25
            display_unit = unit or ("%" if is_ratio else "元")
            text = f"[{stmt_type}/{period_kind}] {period_label} {item_name} = {amount} {display_unit}"
            candidates.append(
                EvidenceItem(
                    source_type="financial_fact",
                    content=text,
                    section_key=section_key or table_type or "key_financials",
                    page_num=page_num,
                    score=score,
                    metadata={"item_name": item_name, "is_ratio": is_ratio},
                )
            )
        candidates.sort(key=lambda x: -x.score)
        return candidates[: self.top_k]

    def _retrieve_structured_tables(
        self, report_id: int, normalized: NormalizedQuery
    ) -> list[EvidenceItem]:
        evidence: list[EvidenceItem] = []
        granularity = normalized.sql_targets.period_granularity
        section_keys = list(normalized.section_keys) or [
            "top10_shareholders",
            "subsidiaries",
            "directors_supervisors",
            "company_profile",
        ]
        if granularity == "annual" and "quarterly_financials" in section_keys:
            section_keys = [k for k in section_keys if k != "quarterly_financials"]

        entities = normalized.entities or [normalized.canonical_question]

        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_seq, section_key, page_num, table_title, rows, table_type_guess
                FROM structured_tables
                WHERE report_id = %s
                  AND section_key = ANY(%s)
                ORDER BY table_seq ASC
                LIMIT %s
                """,
                (report_id, section_keys, self.top_k * 5),
            )
            rows = cur.fetchall()

        for table_seq, section_key, page_num, table_title, rows_json, table_type in rows:
            if granularity == "annual" and table_type == "quarterly_financials":
                continue
            rows_text = json.dumps(rows_json, ensure_ascii=False) if rows_json is not None else ""
            if entities and not any(entity in rows_text for entity in entities):
                continue
            sample = _first_non_empty(
                [json.dumps(rows_json[:2], ensure_ascii=False) if isinstance(rows_json, list) else rows_text]
            )
            score = 0.8
            if table_type == "key_financials_summary":
                score = 0.95
            elif table_type == "quarterly_financials":
                score = 0.5
            evidence.append(
                EvidenceItem(
                    source_type="structured_table",
                    content=f"表#{table_seq} {table_title or ''} {sample or ''}".strip(),
                    section_key=section_key,
                    page_num=page_num,
                    score=score,
                    metadata={"table_seq": table_seq, "table_type_guess": table_type},
                )
            )
            if len(evidence) >= self.top_k:
                break

        return evidence


class VectorRetriever:
    _model: SentenceTransformer | None = None

    def __init__(self, top_k: int = VECTOR_TOP_K) -> None:
        self.top_k = top_k

    @classmethod
    def model(cls) -> SentenceTransformer:
        if cls._model is None:
            cls._model = SentenceTransformer(QUERY_EMBED_MODEL)
        return cls._model

    def retrieve(
        self,
        report_id: int,
        query_text: str,
        *,
        section_keys: list[str] | None = None,
    ) -> list[EvidenceItem]:
        if not query_text.strip():
            return []

        vec = self.model().encode(query_text, normalize_embeddings=True)
        vec_str = to_pgvector(vec.tolist())
        fetch_limit = self.top_k * 4 if section_keys else self.top_k
        preferred = {k for k in (section_keys or []) if k}

        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT section_key, page_num, chunk_index, content, (embedding <=> %s::vector) AS dist
                FROM text_chunks
                WHERE report_id = %s
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec_str, report_id, vec_str, fetch_limit),
            )
            rows = cur.fetchall()

        evidence: list[EvidenceItem] = []
        for section_key, page_num, chunk_index, content, dist in rows:
            score = max(0.0, 1.0 - float(dist))
            if preferred and section_key in preferred:
                score = min(1.0, score * 1.15)
            evidence.append(
                EvidenceItem(
                    source_type="text_chunk",
                    content=content,
                    section_key=section_key,
                    page_num=page_num,
                    score=score,
                    metadata={"chunk_index": chunk_index, "distance": float(dist)},
                )
            )

        evidence.sort(key=lambda x: (-x.score, x.metadata.get("chunk_index", 0)))
        return evidence[: self.top_k]


class KGRetriever:
    """Phase2 placeholder retriever."""

    def retrieve(self, report_id: int, normalized: NormalizedQuery) -> list[EvidenceItem]:
        _ = (report_id, normalized)
        return []
