from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class Section:
    seq_no: int
    title_raw: str
    heading_level: int
    section_key: str | None
    content_md: str


@dataclass
class ParsedTable:
    table_seq: int
    html_raw: str
    headers: list[str]
    rows: list[list[str]]
    section_key: str | None
    table_title: str | None
    page_num: int | None
    header_hash: str
    table_type_guess: str | None = None


@dataclass
class ExtractedFact:
    table_seq: int
    stmt_type: str
    item_name: str
    period_label: str
    period_kind: str
    amount: Decimal
    unit: str
    is_ratio: bool
    page_num: int | None
    section_key: str | None = None
    table_type_guess: str | None = None


@dataclass
class ExtractedEntity:
    entity_key: str
    name: str
    entity_type: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class RelationEvidence:
    evidence_type: str
    section_key: str | None = None
    page_num: int | None = None
    table_seq: int | None = None
    snippet: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedRelation:
    relation_type: str
    subject_key: str
    subject_name: str
    subject_type: str
    object_key: str
    object_name: str
    object_type: str
    attrs: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    source: str = "rule"
    source_key: str = ""
    evidence: list[RelationEvidence] = field(default_factory=list)


@dataclass
class ExtractResult:
    sections: list[Section]
    tables: list[ParsedTable]
    financial_facts: list[ExtractedFact]
    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)
    relation_candidates: list[dict[str, Any]] = field(default_factory=list)
