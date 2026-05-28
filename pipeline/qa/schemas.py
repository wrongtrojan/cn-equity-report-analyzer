from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

IntentType = Literal["numeric", "narrative", "relational", "hybrid"]


class SQLTargets(BaseModel):
    item_names: list[str] = Field(default_factory=list)
    period_labels: list[str] = Field(default_factory=list)
    period_kinds: list[str] = Field(default_factory=list)
    stmt_types: list[str] = Field(default_factory=list)
    period_granularity: Literal["annual", "quarterly", "point_in_time", "any"] = "any"


class NormalizedQuery(BaseModel):
    intent: IntentType = "hybrid"
    canonical_question: str
    report_year: int | None = None
    entities: list[str] = Field(default_factory=list)
    section_keys: list[str] = Field(default_factory=list)
    sql_targets: SQLTargets = Field(default_factory=SQLTargets)
    vector_query: str
    needs_previous_context: bool = False


class EvidenceItem(BaseModel):
    source_type: Literal["financial_fact", "structured_table", "text_chunk", "kg_relation"]
    content: str
    section_key: str | None = None
    page_num: int | None = None
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class QAResponse(BaseModel):
    answer: str
    citations: list[str] = Field(default_factory=list)
    normalized: NormalizedQuery
    evidence: list[EvidenceItem] = Field(default_factory=list)

