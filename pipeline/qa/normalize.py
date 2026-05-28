# pipeline/qa/normalize.py
"""查询标准化补全：粒度、期间、科目别名与意图规则。"""

from __future__ import annotations

import re
from typing import Literal

from pipeline.ingest.item_aliases import ITEM_ALIASES, expand_item_names

from .schemas import NormalizedQuery, SQLTargets

PeriodGranularity = Literal["annual", "quarterly", "point_in_time", "any"]

STMT_TYPE_PRIORITY = {
    "kpi": 0,
    "income": 1,
    "cashflow": 2,
    "balance": 3,
    "operational": 4,
    "other": 5,
}

TABLE_TYPE_PRIORITY = {
    "key_financials_summary": 0,
    "income_statement": 1,
    "cashflow_statement": 2,
    "balance_sheet": 3,
    "quarterly_financials": 4,
}

QUARTER_ALIASES = {
    "第一季度": "Q1",
    "一季度": "Q1",
    "q1": "Q1",
    "第二季度": "Q2",
    "二季度": "Q2",
    "q2": "Q2",
    "第三季度": "Q3",
    "三季度": "Q3",
    "q3": "Q3",
    "第四季度": "Q4",
    "四季度": "Q4",
    "q4": "Q4",
}


def infer_granularity(query: str) -> PeriodGranularity:
    q = query.strip()
    if re.search(r"第一|第二|第三|第四|季度|[Qq][1-4]", q):
        return "quarterly"
    if re.search(r"期末|年末|余额|时点", q):
        return "point_in_time"
    if re.search(r"\d{4}\s*年|年度|全年|年报", q):
        return "annual"
    return "annual"


def reconcile_granularity(normalized_granularity: str, query: str) -> PeriodGranularity:
    """查询文本中的粒度信号优先于 LLM 误判。"""
    query_granularity = infer_granularity(query)
    if query_granularity in {"quarterly", "point_in_time"}:
        return query_granularity
    if normalized_granularity and normalized_granularity != "any":
        return normalized_granularity  # type: ignore[return-value]
    return query_granularity


def _extract_item_names(query: str, sql_item_names: list[str], entities: list[str]) -> list[str]:
    names = [x.strip() for x in sql_item_names if x and x.strip()]
    if not names:
        names = [e.strip() for e in entities if e and 0 < len(e.strip()) <= 32]
    if not names:
        for token in [
            "营业总收入",
            "营业收入",
            "净利润",
            "归属于上市公司股东的净利润",
            "资产总计",
            "货币资金",
            "经营活动产生的现金流量净额",
            "研发投入",
            "研发人员",
        ]:
            if token in query:
                names.append(token)
    if re.search(r"比例|占比", query):
        names.extend(ITEM_ALIASES.get("rd_ratio", []))
    if "研发人员" in query and re.search(r"比例|占比|占", query):
        names.extend(ITEM_ALIASES.get("rd_headcount_ratio", []))
    names = expand_item_names(names)
    dedup: list[str] = []
    for name in names:
        if name not in dedup:
            dedup.append(name)
    return dedup


def _resolve_period_labels(
    query: str,
    granularity: PeriodGranularity,
    report_year: int | None,
    incoming: list[str],
) -> list[str]:
    labels = [x.strip() for x in incoming if x and str(x).strip()]
    year = report_year

    if granularity == "quarterly":
        quarter_label = infer_quarter_label(query, year)
        if quarter_label:
            return [quarter_label]
        if year:
            return [f"{year}Q1", f"{year}Q2", f"{year}Q3", f"{year}Q4"]
        return []

    if granularity == "annual":
        year_labels = [p for p in labels if re.fullmatch(r"20\d{2}", str(p))]
        if year_labels:
            return year_labels
        if year and re.search(r"\d{4}", query):
            years = re.findall(r"(20\d{2})", query)
            return years or [str(year)]
        if year:
            return [str(year)]
        return []

    return labels


def infer_quarter_label(query: str, report_year: int | None) -> str | None:
    q = query.lower()
    for alias, label in QUARTER_ALIASES.items():
        if alias.lower() in q:
            if report_year:
                return f"{report_year}{label}"
            return label
    return None


def default_period_kinds(granularity: PeriodGranularity) -> list[str]:
    if granularity == "annual":
        return ["year"]
    if granularity == "quarterly":
        return ["quarter"]
    if granularity == "point_in_time":
        return ["point_in_time"]
    return []


def default_stmt_types(granularity: PeriodGranularity) -> list[str]:
    if granularity == "annual":
        return ["kpi", "income", "cashflow", "balance"]
    if granularity == "quarterly":
        return ["kpi"]
    if granularity == "point_in_time":
        return ["balance", "kpi"]
    return ["kpi", "income", "cashflow", "balance"]


_NUMERIC_HINTS = re.compile(
    r"多少|金额|数值|比例|占比|同比|环比|元/股|每股|是多少|有多少"
)


def apply_intent_rules(
    normalized: NormalizedQuery,
    query: str,
    report_year: int | None,
) -> NormalizedQuery:
    """规则修正 LLM 意图误判（叙述/业绩类）。"""
    q = query.strip()
    if not q:
        return normalized

    vector_query = normalized.vector_query or q
    year = normalized.report_year or report_year

    if re.search(r"业绩|经营情况|表现|财务状况", q) and re.search(
        r"怎么样|如何|怎样|概况|总结|简要|整体", q
    ):
        period_labels = [str(year)] if year else list(normalized.sql_targets.period_labels)
        return normalized.model_copy(
            update={
                "intent": "hybrid",
                "section_keys": ["mda", "key_financials"],
                "vector_query": vector_query,
                "sql_targets": SQLTargets(
                    item_names=["营业总收入", "归属于上市公司股东的净利润"],
                    period_labels=period_labels,
                    period_kinds=["year"],
                    stmt_types=["kpi", "income"],
                    period_granularity="annual",
                ),
            }
        )

    if re.search(r"主要业务|业务是什么|业务有哪些|从事.*业务|介绍一下|请介绍", q):
        if not _NUMERIC_HINTS.search(q):
            return normalized.model_copy(
                update={
                    "intent": "narrative",
                    "section_keys": ["mda", "company_profile"],
                    "vector_query": vector_query,
                }
            )

    if re.search(r"股东|持股|控股|实际控制人|第一大股东|子公司|关联方|董事|监事|高管|董事长", q):
        section_keys = list(normalized.section_keys) or [
            "top10_shareholders",
            "shareholder_section",
            "subsidiaries",
            "directors_supervisors",
            "related_parties",
            "corporate_governance",
        ]
        return normalized.model_copy(
            update={
                "intent": "relational",
                "section_keys": section_keys,
                "vector_query": vector_query,
                "report_year": year,
            }
        )

    return normalized


def default_section_keys(granularity: PeriodGranularity, intent: str) -> list[str]:
    if intent in {"relational", "hybrid"}:
        return [
            "top10_shareholders",
            "subsidiaries",
            "directors_supervisors",
            "company_profile",
        ]
    if granularity == "quarterly":
        return ["quarterly_financials"]
    if granularity == "point_in_time":
        return ["key_financials", "financial_statements"]
    return ["key_financials", "financial_statements"]


def enrich_normalized(
    normalized: NormalizedQuery,
    query: str,
    report_year: int | None,
) -> NormalizedQuery:
    """补全/纠正 LLM 标准化结果，确保粒度与 period_label 一致。"""
    normalized = apply_intent_rules(normalized, query, report_year)
    year = normalized.report_year or report_year

    if normalized.intent == "narrative":
        section_keys = list(normalized.section_keys) or ["mda"]
        return normalized.model_copy(
            update={
                "section_keys": section_keys,
                "vector_query": normalized.vector_query or query,
                "report_year": year,
            }
        )

    sql = normalized.sql_targets
    granularity = reconcile_granularity(sql.period_granularity, query)

    period_kinds = default_period_kinds(granularity)
    stmt_types = list(default_stmt_types(granularity))
    if re.search(r"研发|人员数量", query) and "operational" not in stmt_types:
        stmt_types.append("operational")
    period_labels = _resolve_period_labels(query, granularity, year, list(sql.period_labels))
    item_names = _extract_item_names(query, list(sql.item_names), list(normalized.entities))

    section_keys = list(normalized.section_keys)
    if normalized.intent in {"numeric", "hybrid"}:
        if not section_keys or (
            granularity == "quarterly" and "quarterly_financials" not in section_keys
        ):
            section_keys = default_section_keys(granularity, normalized.intent)
        elif granularity == "annual":
            section_keys = [k for k in section_keys if k != "quarterly_financials"] or default_section_keys(
                granularity, normalized.intent
            )

    updated_sql = SQLTargets(
        item_names=item_names,
        period_labels=period_labels,
        period_kinds=period_kinds,
        stmt_types=stmt_types,
        period_granularity=granularity,
    )
    return normalized.model_copy(
        update={
            "sql_targets": updated_sql,
            "section_keys": section_keys,
            "report_year": year,
        }
    )


def fact_rank_score(
    stmt_type: str,
    period_kind: str,
    table_type: str | None,
    granularity: PeriodGranularity,
) -> float:
    score = 1.0
    score -= STMT_TYPE_PRIORITY.get(stmt_type, 9) * 0.08
    score -= TABLE_TYPE_PRIORITY.get(table_type or "", 9) * 0.05

    if granularity == "annual":
        if period_kind == "year":
            score += 0.35
        elif period_kind == "quarter":
            score -= 1.0
        elif period_kind == "point_in_time":
            score -= 0.2
    elif granularity == "quarterly":
        if period_kind == "quarter":
            score += 0.35
        elif period_kind == "year":
            score -= 0.15
    elif granularity == "point_in_time" and period_kind == "point_in_time":
        score += 0.35

    if table_type == "key_financials_summary":
        score += 0.25
    if table_type == "quarterly_financials" and granularity == "annual":
        score -= 0.5
    return score
