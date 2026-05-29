"""Domain contracts for operating analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

Severity = Literal["high", "medium", "low"]
ExplanationType = Literal["direct", "indirect", "none"]
FlagCategory = Literal["profitability", "growth", "cashflow", "cost", "industry", "other"]
FlagDirection = Literal["up", "down", "mixed"]
SnapshotStatus = Literal["normal", "watch", "flag"]


@dataclass
class MetricPoint:
    item_name: str
    period_label: str
    period_kind: str
    amount: Decimal
    unit: str
    is_ratio: bool
    stmt_type: str
    fact_id: int | None = None
    derived: bool = False


@dataclass
class MetricSeries:
    item_name: str
    points: list[MetricPoint] = field(default_factory=list)
    yoy_ratio: MetricPoint | None = None
    prior_year_value: MetricPoint | None = None


@dataclass
class BenchmarkSnapshot:
    industry: str
    item_name: str
    period_label: str
    p25: Decimal | None
    p50: Decimal | None
    p75: Decimal | None
    source: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricSnapshot:
    item_name: str
    period_label: str
    current_value: Decimal | None
    prior_value: Decimal | None
    yoy_pct: Decimal | None
    unit: str
    is_ratio: bool
    derived: bool
    industry_p25: Decimal | None = None
    industry_p50: Decimal | None = None
    industry_p75: Decimal | None = None
    status: SnapshotStatus = "normal"


@dataclass
class MetricFlag:
    flag_id: str
    rule_id: str
    severity: Severity
    category: FlagCategory
    item_name: str
    period_label: str
    metric_value: Decimal | None
    benchmark_value: Decimal | None
    delta: Decimal | None
    direction: FlagDirection | None
    summary: str
    confidence: float
    evidence_fact_ids: list[int] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    explanations: list[FlagExplanation] = field(default_factory=list)


@dataclass
class FlagExplanation:
    chunk_id: int | None
    snippet: str
    section_key: str | None
    page_num: int | None
    relevance_score: float
    explanation_type: ExplanationType
    reason: str


@dataclass
class AnalysisRunStats:
    flag_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    explained_count: int = 0
    unexplained_count: int = 0
    industry_compare_available: bool = False
    snapshot_count: int = 0


@dataclass
class OperatingAnalysisResult:
    report_id: int
    run_id: int | None
    company_name: str
    stock_code: str
    report_year: int | None
    industry: str | None
    generated_at: datetime | None
    summary: str
    highlights: list[MetricFlag] = field(default_factory=list)
    flags_by_category: dict[str, list[MetricFlag]] = field(default_factory=dict)
    stats: AnalysisRunStats = field(default_factory=AnalysisRunStats)
    benchmark_source: str | None = None
    benchmark_disclaimer: str = ""
    snapshots: list[MetricSnapshot] = field(default_factory=list)
