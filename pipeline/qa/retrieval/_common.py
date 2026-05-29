"""Evidence retrieval: merge, SQL, vector, and KG channels."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable

from pipeline.db import connect, to_pgvector
from pipeline.item_aliases import expand_item_names
from sentence_transformers import SentenceTransformer

from ..config import MAX_EVIDENCE, QUERY_EMBED_MODEL, SQL_TOP_K, VECTOR_TOP_K
from ..core.scoring import extract_role_keywords
from ..core.normalize import fact_rank_score
from ..schemas import EvidenceItem, NormalizedQuery


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
