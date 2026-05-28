"""Pure financial-fact extraction from classified tables."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from pipeline.extract.contracts import ExtractedFact, ParsedTable

KPI_ITEMS = [
    "营业总收入",
    "营业收入",
    "归属于上市公司股东的净利润",
    "归属于上市公司股东的扣除非经常性损益的净利润",
    "经营活动产生的现金流量净额",
    "基本每股收益",
    "稀释每股收益",
    "加权平均净资产收益率",
    "资产总额",
    "资产总计",
    "归属于上市公司股东的净资产",
]

QUARTERLY_ITEMS = [
    "营业总收入",
    "营业收入",
    "归属于上市公司股东的净利润",
    "归属于上市公司股东的扣除非经常性损益的净利润",
    "经营活动产生的现金流量净额",
]

RD_INVESTMENT_ITEMS = ["研发投入金额", "研发支出资本化的金额"]

RD_INVESTMENT_RATIO_ITEMS = [
    "研发投入占营业总收入比例",
    "研发投入占营业收入比例",
    "资本化研发支出占研发投入的比例",
    "资本化研发支出占当期净利润的比重",
]

RD_PERSONNEL_ITEMS = [
    "研发人员数量",
    "研发人员数量占比",
    "本科及以下",
    "硕士",
    "博士",
    "30岁以下",
    "30~40岁",
    "40岁以上",
]

QUARTER_HEADER_MAP = {"第一季度": "Q1", "第二季度": "Q2", "第三季度": "Q3", "第四季度": "Q4"}

_RATIO_ITEM_TOKENS = set(RD_INVESTMENT_RATIO_ITEMS + ["加权平均净资产收益率", "研发人员数量占比"])


def _parse_amount(raw: str) -> Decimal | None:
    text = raw.replace(",", "").replace("，", "").strip()
    if not text or text.endswith("%"):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _parse_ratio(raw: str) -> Decimal | None:
    text = raw.replace(",", "").replace("，", "").strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    if not text or text in {"-", "—"}:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _should_skip_item(item_name: str, *, allow_ratio: bool = False) -> bool:
    if not allow_ratio and "占" in item_name and "比例" in item_name:
        return True
    if item_name.startswith("其中：") or item_name.startswith("减："):
        return True
    if item_name.endswith("：") or item_name.endswith(":"):
        return True
    return False


def _is_ratio_item(item_name: str) -> bool:
    if any(token in item_name for token in _RATIO_ITEM_TOKENS):
        return True
    return "收益率" in item_name and "净资产" in item_name


def _infer_unit(item_name: str, is_ratio: bool) -> str:
    if is_ratio:
        return "%"
    if "人" in item_name and "数量" in item_name:
        return "人"
    if "每股收益" in item_name or "元/股" in item_name:
        return "元/股"
    return "元"


def _period_columns(headers: list, stmt_type: str) -> list[tuple[int, str, str, bool]]:
    cols: list[tuple[int, str, str, bool]] = []
    for i, h in enumerate(headers):
        hs = str(h)
        m = re.search(r"(20\d{2})", hs)
        if not m:
            continue
        year = m.group(1)
        is_yoy = "增减" in hs or "变动比例" in hs
        if "末" in hs or ("余额" in hs and "增减" not in hs):
            cols.append((i, year, "point_in_time", is_yoy))
        elif stmt_type == "kpi" and is_yoy:
            cols.append((i, year, "year", True))
        else:
            cols.append((i, year, "year", is_yoy))
    if cols:
        return cols

    fallback = [
        ("本期发生额", "year", False),
        ("本期金额", "year", False),
        ("上期发生额", "year", False),
        ("上期金额", "year", False),
        ("期末余额", "point_in_time", False),
        ("期初余额", "point_in_time", False),
    ]
    for i, h in enumerate(headers):
        hs = str(h)
        for label, kind, is_yoy in fallback:
            if label in hs:
                cols.append((i, label, kind, is_yoy))
                break
    return cols


def _quarter_columns(headers: list, report_year: int | None) -> list[tuple[int, str, str, bool]]:
    cols: list[tuple[int, str, str, bool]] = []
    for i, h in enumerate(headers):
        hs = str(h)
        for header_label, quarter in QUARTER_HEADER_MAP.items():
            if header_label in hs:
                period_label = f"{report_year}{quarter}" if report_year else quarter
                cols.append((i, period_label, "quarter", False))
                break
    return cols


def _resolve_period_label(label: str, report_year: int | None) -> str:
    if re.fullmatch(r"20\d{2}", label) or re.fullmatch(r"20\d{2}Q[1-4]", label):
        return label
    if report_year is None:
        return label
    if label in {"上期发生额", "上期金额", "期初余额"}:
        return str(report_year - 1)
    if label in {"本期发生额", "本期金额", "期末余额"}:
        return str(report_year)
    return label


def _row_item_name(row: list) -> str:
    return str(row[0]).strip() if row else ""


def _item_matches(item_name: str, targets: list[str]) -> bool:
    allow_ratio = _is_ratio_item(item_name)
    if _should_skip_item(item_name, allow_ratio=allow_ratio):
        return False
    if not targets:
        return True
    for target in sorted(targets, key=len, reverse=True):
        if item_name == target:
            return True
        if item_name.startswith(f"{target}（") or item_name.startswith(f"{target}("):
            return True
        if target in item_name and (
            item_name.startswith("一、")
            or item_name.startswith("二、")
            or item_name.startswith("三、")
        ):
            return True
    return False


def extract_facts_from_table(
    table: ParsedTable,
    stmt_type: str,
    report_year: int | None,
    target_items: list[str],
    *,
    use_quarter_columns: bool = False,
    extract_all_rows: bool = False,
) -> list[ExtractedFact]:
    facts: list[ExtractedFact] = []
    period_cols = _quarter_columns(table.headers, report_year) if use_quarter_columns else _period_columns(table.headers, stmt_type)
    if not period_cols:
        return facts

    for row in table.rows:
        item_name = _row_item_name(row)
        if not item_name:
            continue
        if extract_all_rows:
            if _should_skip_item(item_name):
                continue
        elif not _item_matches(item_name, target_items):
            continue

        for col_idx, period_raw, period_kind, is_yoy_col in period_cols:
            if col_idx >= len(row):
                continue
            raw = str(row[col_idx]).strip()
            if not raw or raw in {"-", "—", ""}:
                continue

            is_ratio = raw.endswith("%") or _is_ratio_item(item_name) or is_yoy_col
            amount = _parse_ratio(raw) if is_ratio else _parse_amount(raw)
            if amount is None:
                continue

            period_label = _resolve_period_label(period_raw, report_year)
            fact_item_name = item_name
            if is_yoy_col and not item_name.endswith("同比增减"):
                fact_item_name = f"{item_name}同比增减"

            facts.append(
                ExtractedFact(
                    table_seq=table.table_seq,
                    stmt_type=stmt_type,
                    item_name=fact_item_name,
                    period_label=period_label,
                    period_kind=period_kind,
                    amount=amount,
                    unit=_infer_unit(fact_item_name, is_ratio),
                    is_ratio=is_ratio,
                    page_num=table.page_num,
                    section_key=table.section_key,
                    table_type_guess=table.table_type_guess,
                )
            )
    return facts


def build_financial_facts(tables: list[ParsedTable], report_year: int | None) -> list[ExtractedFact]:
    grouped: dict[str, list[ParsedTable]] = {}
    for table in tables:
        if table.table_type_guess:
            grouped.setdefault(table.table_type_guess, []).append(table)

    all_facts: list[ExtractedFact] = []
    for table in grouped.get("key_financials_summary", []):
        all_facts.extend(extract_facts_from_table(table, "kpi", report_year, KPI_ITEMS))
    for table in grouped.get("quarterly_financials", []):
        all_facts.extend(
            extract_facts_from_table(
                table,
                "kpi",
                report_year,
                QUARTERLY_ITEMS,
                use_quarter_columns=True,
            )
        )
    for table in grouped.get("balance_sheet", []):
        all_facts.extend(extract_facts_from_table(table, "balance", report_year, [], extract_all_rows=True))
    for table in grouped.get("income_statement", []):
        all_facts.extend(extract_facts_from_table(table, "income", report_year, [], extract_all_rows=True))
    for table in grouped.get("cashflow_statement", []):
        all_facts.extend(extract_facts_from_table(table, "cashflow", report_year, [], extract_all_rows=True))
    for table in grouped.get("rd_investment_summary", []):
        targets = RD_INVESTMENT_ITEMS + RD_INVESTMENT_RATIO_ITEMS
        all_facts.extend(extract_facts_from_table(table, "operational", report_year, targets))
    for table in grouped.get("rd_personnel_summary", []):
        all_facts.extend(extract_facts_from_table(table, "operational", report_year, RD_PERSONNEL_ITEMS))
    return all_facts
