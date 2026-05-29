from __future__ import annotations

import re

from pipeline.db import connect

from ..config import SQL_TOP_K
from ..core.scoring import extract_role_keywords
from ..schemas import EvidenceItem, NormalizedQuery

class KGRetriever:
    def __init__(self, top_k: int = SQL_TOP_K) -> None:
        self.top_k = top_k

    def _load_relation_rows(
        self,
        report_id: int,
        *,
        relation_types: list[str] | None,
        title_patterns: list[str] | None = None,
        entity_patterns: list[str] | None = None,
        limit: int,
    ) -> list[tuple]:
        params: list = [report_id]
        filters = ["r.report_id = %s"]
        if relation_types:
            filters.append("r.relation_type = ANY(%s)")
            params.append(relation_types)

        match_filters: list[str] = []
        if title_patterns:
            title_clause = " OR ".join(["COALESCE(r.attrs->>'title', '') ILIKE %s"] * len(title_patterns))
            match_filters.append(f"({title_clause})")
            params.extend(title_patterns)
        if entity_patterns:
            entity_clause = " OR ".join(
                ["se.name ILIKE %s", "oe.name ILIKE %s"] * len(entity_patterns)
            )
            match_filters.append(f"({entity_clause})")
            for pattern in entity_patterns:
                params.extend([pattern, pattern])
        if match_filters:
            filters.append(f"({' OR '.join(match_filters)})")

        sql = f"""
            SELECT r.id, r.relation_type, r.attrs, r.confidence, r.source,
                   se.name, oe.name, se.entity_type, oe.entity_type
            FROM kg_relations r
            JOIN kg_entities se ON se.id = r.subject_entity_id
            JOIN kg_entities oe ON oe.id = r.object_entity_id
            WHERE {" AND ".join(filters)}
            ORDER BY r.confidence DESC, r.id ASC
            LIMIT %s
        """
        params.append(limit)
        with connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _rows_to_evidence(
        self,
        rows: list[tuple],
        *,
        entities: list[str],
        role_keywords: list[str],
    ) -> list[EvidenceItem]:
        if not rows:
            return []

        relation_ids = [row[0] for row in rows]
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT relation_id, evidence_type, section_key, page_num, snippet, attrs
                FROM kg_relation_evidence
                WHERE relation_id = ANY(%s)
                ORDER BY id
                """,
                (relation_ids,),
            )
            evidence_rows = cur.fetchall()

        evidence_map: dict[int, list[tuple]] = {}
        for row in evidence_rows:
            evidence_map.setdefault(row[0], []).append(row[1:])

        evidence_items: list[EvidenceItem] = []
        for relation_id, relation_type, attrs, confidence, source, subject, object_name, subject_type, object_type in rows:
            ev_rows = evidence_map.get(relation_id, [])
            snippet = ev_rows[0][3] if ev_rows else ""
            section_key = ev_rows[0][1] if ev_rows else None
            page_num = ev_rows[0][2] if ev_rows else None
            attrs = attrs or {}
            attr_text = ", ".join(f"{k}={v}" for k, v in attrs.items() if v)
            content = f"{subject} --[{relation_type}]--> {object_name}"
            if attr_text:
                content = f"{content} ({attr_text})"
            if snippet:
                content = f"{content} | {snippet}"

            score = float(confidence or 0.8)
            if entities and any(entity in subject or entity in object_name for entity in entities):
                score += 0.15
            title = str(attrs.get("title") or "")
            if role_keywords and title and any(role in title or title in role for role in role_keywords):
                score += 0.35

            evidence_items.append(
                EvidenceItem(
                    source_type="kg_relation",
                    content=content,
                    section_key=section_key,
                    page_num=page_num,
                    score=min(score, 1.0),
                    metadata={
                        "relation_id": relation_id,
                        "relation_type": relation_type,
                        "subject": subject,
                        "object": object_name,
                        "subject_type": subject_type,
                        "object_type": object_type,
                        "source": source,
                        "attrs": attrs,
                    },
                )
            )
        return evidence_items

    def retrieve(
        self,
        report_id: int,
        normalized: NormalizedQuery,
        *,
        top_k: int | None = None,
    ) -> list[EvidenceItem]:
        entities = [e.strip() for e in (normalized.entities or []) if e and e.strip()]
        query_text = normalized.canonical_question or ""
        if not entities:
            for token in re.findall(r"[\u4e00-\u9fffA-Za-z·]{2,20}", query_text):
                if len(token) >= 2:
                    entities.append(token)

        relation_types: list[str] | None = None
        role_keywords = extract_role_keywords(query_text)
        title_patterns = [f"%{kw}%" for kw in role_keywords]
        if re.search(r"股东|持股|控股|实际控制", query_text):
            relation_types = ["shareholder_of", "actual_controller_of"]
        elif re.search(r"董事|监事|高管|管理层|董事长|总经理|监事会主席", query_text):
            relation_types = ["executive_of", "director_of"]
        elif re.search(r"子公司|参股|控股公司", query_text):
            relation_types = ["subsidiary_of", "invest_in"]
        elif re.search(r"关联方|关联交易", query_text):
            relation_types = ["related_party_of", "transaction_with"]

        stop_entities = {"公司", "是谁", "多少", "哪些", "什么", "如何", "怎样", "现任", "离任"}
        filtered_entities = [
            e
            for e in entities
            if e not in stop_entities
            and len(e) >= 2
            and not re.search(r"公司|股份|有限|集团", e)
        ]
        entity_patterns = [f"%{entity}%" for entity in filtered_entities]

        seen_ids: set[int] = set()
        merged_rows: list[tuple] = []
        fetch_limit = self.top_k * 3
        if top_k is not None:
            fetch_limit = max(fetch_limit, top_k * 3)

        if role_keywords and relation_types:
            title_rows = self._load_relation_rows(
                report_id,
                relation_types=relation_types,
                title_patterns=title_patterns,
                limit=fetch_limit,
            )
            for row in title_rows:
                if row[0] not in seen_ids:
                    seen_ids.add(row[0])
                    merged_rows.append(row)

        if entity_patterns:
            entity_rows = self._load_relation_rows(
                report_id,
                relation_types=relation_types,
                entity_patterns=entity_patterns,
                limit=fetch_limit,
            )
            for row in entity_rows:
                if row[0] not in seen_ids:
                    seen_ids.add(row[0])
                    merged_rows.append(row)

        if not merged_rows:
            merged_rows = self._load_relation_rows(
                report_id,
                relation_types=relation_types,
                limit=fetch_limit,
            )

        evidence_items = self._rows_to_evidence(
            merged_rows,
            entities=entities,
            role_keywords=role_keywords,
        )
        evidence_items.sort(key=lambda x: -x.score)
        limit = top_k if top_k is not None else self.top_k
        return evidence_items[:limit]
