# pipeline/ingest/extract.py
"""表格分类（table_type_guess）与 financial_facts 抽取。"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .item_aliases import revenue_row_tokens

# ---------------------------------------------------------------------------
# 表格分类
# ---------------------------------------------------------------------------




def _blob(headers: list[str], rows: list[list[str]]) -> str:
    parts = [str(h) for h in headers]
    for row in rows[:40]:
        if row:
            parts.append(str(row[0]))
    return "|".join(parts)


def _headers_text(headers: list[str]) -> str:
    return "|".join(str(h) for h in headers)


def _has_year_columns(hdr: str) -> bool:
    return bool(re.search(r"20\d{2}", hdr))


def _has_year_end_columns(hdr: str) -> bool:
    years = re.findall(r"(20\d{2})", hdr)
    return len(years) >= 2 and "末" in hdr


def _has_annual_period(hdr: str) -> bool:
    if any(k in hdr for k in ("本期发生额", "本期金额", "上期发生额", "上期金额")):
        return True
    return bool(re.search(r"20\d{2}\s*年度", hdr))


def _has_revenue_row(text: str) -> bool:
    return any(token in text for token in revenue_row_tokens())


def guess_table_type(
    headers: list[str],
    rows: list[list[str]],
    section_key: str | None,
    table_title: str | None = None,
) -> str | None:
    text = _blob(headers, rows)
    hdr = _headers_text(headers)
    title = table_title or ""

    rules: list[tuple[int, str, callable]] = [
        (10, "key_financials_summary", lambda: _is_key_financials_summary(section_key, text, hdr)),
        (12, "quarterly_financials", lambda: _is_quarterly_financials(section_key, text, hdr)),
        (13, "rd_investment_summary", lambda: _is_rd_investment_summary(text, hdr)),
        (14, "rd_personnel_summary", lambda: _is_rd_personnel_summary(text, hdr)),
        (15, "company_profile_kv", lambda: "股票简称" in hdr and "股票代码" in hdr),
        (16, "top10_shareholders", lambda: _is_top10_shareholders(section_key, text, hdr)),
        (17, "subsidiaries", lambda: _is_subsidiaries(section_key, text, hdr)),
        (18, "related_party_transactions", lambda: _is_related_parties(section_key, text, hdr)),
        (19, "bond_financials", lambda: section_key == "bond_financials"),
        (20, "balance_sheet", lambda: _is_balance_sheet(section_key, text, hdr)),
        (21, "income_statement", lambda: _is_income_statement(section_key, text, hdr)),
        (22, "cashflow_statement", lambda: _is_cashflow_statement(section_key, text, hdr)),
        (30, "glossary_terms", lambda: section_key == "glossary" and "释义项" in hdr),
    ]

    matched: list[tuple[int, str]] = []
    for priority, table_type, predicate in rules:
        if predicate():
            matched.append((priority, table_type))
    if not matched:
        return None
    return sorted(matched)[0][1]


def _is_key_financials_summary(section_key: str | None, text: str, hdr: str) -> bool:
    if not (_has_revenue_row(text) and _has_year_columns(hdr)):
        return False
    if section_key == "key_financials":
        return True
    annual_kpi_hdr = bool(re.search(r"20\d{2}年", hdr)) and "增减" in hdr
    annual_kpi_rows = ("资产总额" in text or "资产总计" in text or "归属于上市公司股东的净资产" in text)
    return annual_kpi_hdr and annual_kpi_rows


def _is_quarterly_financials(section_key: str | None, text: str, hdr: str) -> bool:
    if not ("第一季度" in hdr and "第四季度" in hdr):
        return False
    if re.search(r"20\d{2}年", hdr) and "增减" in hdr:
        return False
    return section_key in {"quarterly_financials", "company_profile", "key_financials", None}


def _is_rd_investment_summary(text: str, hdr: str) -> bool:
    return "研发投入金额" in text and ("研发投入占营业总收入比例" in text or "研发投入占营业收入比例" in text)


def _is_rd_personnel_summary(text: str, hdr: str) -> bool:
    return "研发人员数量" in text and ("变动比例" in hdr or "占比" in text)


def _is_top10_shareholders(section_key: str | None, text: str, hdr: str) -> bool:
    if section_key not in {"top10_shareholders", "shareholder_section", None}:
        return False
    return ("股东名称" in text or "股东姓名" in text) and (
        "持股比例" in text or "持股数量" in text or "报告期末持股数量" in text
    )


def _is_subsidiaries(section_key: str | None, text: str, hdr: str) -> bool:
    if section_key == "subsidiaries":
        return "子公司" in text or "参股公司" in text
    return False


def _is_related_parties(section_key: str | None, text: str, hdr: str) -> bool:
    if section_key not in {"related_parties", "significant_matters", None}:
        return False
    return "关联方" in text and ("关联交易" in text or "关联关系" in text)


def _is_balance_sheet(section_key: str | None, text: str, hdr: str) -> bool:
    if section_key != "financial_statements":
        return False
    if "占总资产比例" in hdr or "比重增减" in hdr:
        return False
    has_period = ("期末余额" in hdr and "期初余额" in hdr) or _has_year_end_columns(hdr)
    return has_period and ("资产总计" in text or "流动资产：" in text or "负债和所有者权益" in text)


def _is_income_statement(section_key: str | None, text: str, hdr: str) -> bool:
    if section_key != "financial_statements":
        return False
    has_period = _has_annual_period(hdr)
    return has_period and (
        "一、营业总收入" in text
        or (_has_revenue_row(text) and "营业成本" in text and "净利润" in text)
    )


def _is_cashflow_statement(section_key: str | None, text: str, hdr: str) -> bool:
    if section_key != "financial_statements":
        return False
    has_period = _has_annual_period(hdr)
    return has_period and "经营活动产生的现金流量净额" in text

# ---------------------------------------------------------------------------
# 财务事实抽取
# ---------------------------------------------------------------------------

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

BALANCE_SHEET_ITEMS = [
    "货币资金",
    "资产总计",
    "负债合计",
    "归属于上市公司股东的净资产",
    "商誉",
]

INCOME_ITEMS = [
    "一、营业总收入",
    "营业总收入",
    "营业成本",
    "归属于上市公司股东的净利润",
    "基本每股收益",
    "稀释每股收益",
]

CASHFLOW_ITEMS = [
    "经营活动产生的现金流量净额",
    "投资活动产生的现金流量净额",
    "筹资活动产生的现金流量净额",
]

RD_INVESTMENT_ITEMS = [
    "研发投入金额",
    "研发支出资本化的金额",
]

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

QUARTER_HEADER_MAP = {
    "第一季度": "Q1",
    "第二季度": "Q2",
    "第三季度": "Q3",
    "第四季度": "Q4",
}

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
    """Return (col_idx, period_label, period_kind, is_yoy_col)."""
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


def _resolve_period_label(label: str, kind: str, report_year: int | None) -> str:
    if re.fullmatch(r"20\d{2}", label):
        return label
    if re.fullmatch(r"20\d{2}Q[1-4]", label):
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
    table_id: int,
    headers: list,
    rows: list,
    page_num: int | None,
    stmt_type: str,
    report_year: int | None,
    target_items: list[str],
    *,
    use_quarter_columns: bool = False,
    extract_all_rows: bool = False,
) -> list[dict]:
    facts: list[dict] = []
    period_cols = (
        _quarter_columns(headers, report_year)
        if use_quarter_columns
        else _period_columns(headers, stmt_type)
    )
    if not period_cols:
        return facts

    for row in rows:
        item_name = _row_item_name(row)
        if not item_name:
            continue
        if extract_all_rows:
            if _should_skip_item(item_name):
                continue
        elif not _item_matches(item_name, target_items):
            continue

        allow_ratio = _is_ratio_item(item_name)
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

            period_label = _resolve_period_label(period_raw, period_kind, report_year)
            fact_item_name = item_name
            if is_yoy_col and not item_name.endswith("同比增减"):
                fact_item_name = f"{item_name}同比增减"

            facts.append(
                {
                    "table_id": table_id,
                    "stmt_type": stmt_type,
                    "item_name": fact_item_name,
                    "period_label": period_label,
                    "period_kind": period_kind,
                    "amount": amount,
                    "is_ratio": is_ratio,
                    "unit": _infer_unit(fact_item_name, is_ratio),
                    "page_num": page_num,
                }
            )
    return facts


def upsert_facts(cur, report_id: int, facts: list[dict]) -> int:
    inserted = 0
    for fact in facts:
        cur.execute(
            """
            INSERT INTO financial_facts (
                report_id, table_id, stmt_type, item_name, period_label,
                period_kind, amount, unit, is_ratio, page_num
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (report_id, stmt_type, item_name, period_label) DO UPDATE
            SET amount = EXCLUDED.amount,
                unit = EXCLUDED.unit,
                is_ratio = EXCLUDED.is_ratio,
                page_num = EXCLUDED.page_num,
                table_id = EXCLUDED.table_id,
                period_kind = EXCLUDED.period_kind
            """,
            (
                report_id,
                fact["table_id"],
                fact["stmt_type"],
                fact["item_name"],
                fact["period_label"],
                fact["period_kind"],
                fact["amount"],
                fact.get("unit", "元"),
                fact["is_ratio"],
                fact["page_num"],
            ),
        )
        inserted += 1
    return inserted


def insert_all_financial_facts(cur, report_id: int, report_year: int | None) -> int:
    total = 0
    total += _insert_by_table_type(
        cur, report_id, report_year, "key_financials_summary", "kpi", KPI_ITEMS
    )
    total += _insert_quarterly_facts(cur, report_id, report_year)
    total += _insert_by_table_type(
        cur,
        report_id,
        report_year,
        "balance_sheet",
        "balance",
        [],
        extract_all_rows=True,
    )
    total += _insert_by_table_type(
        cur,
        report_id,
        report_year,
        "income_statement",
        "income",
        [],
        extract_all_rows=True,
    )
    total += _insert_by_table_type(
        cur,
        report_id,
        report_year,
        "cashflow_statement",
        "cashflow",
        [],
        extract_all_rows=True,
    )
    total += _insert_rd_investment_facts(cur, report_id, report_year)
    total += _insert_rd_personnel_facts(cur, report_id, report_year)
    return total


def _insert_rd_investment_facts(cur, report_id: int, report_year: int | None) -> int:
    cur.execute(
        """
        SELECT id, headers, rows, page_num
        FROM structured_tables
        WHERE report_id = %s AND table_type_guess = 'rd_investment_summary'
        ORDER BY table_seq
        """,
        (report_id,),
    )
    rows = cur.fetchall()
    targets = RD_INVESTMENT_ITEMS + RD_INVESTMENT_RATIO_ITEMS
    all_facts: list[dict] = []
    for table_id, headers, table_rows, page_num in rows:
        all_facts.extend(
            extract_facts_from_table(
                table_id,
                headers,
                table_rows,
                page_num,
                "operational",
                report_year,
                targets,
            )
        )
    return upsert_facts(cur, report_id, all_facts)


def _insert_rd_personnel_facts(cur, report_id: int, report_year: int | None) -> int:
    cur.execute(
        """
        SELECT id, headers, rows, page_num
        FROM structured_tables
        WHERE report_id = %s AND table_type_guess = 'rd_personnel_summary'
        ORDER BY table_seq
        """,
        (report_id,),
    )
    rows = cur.fetchall()
    all_facts: list[dict] = []
    for table_id, headers, table_rows, page_num in rows:
        all_facts.extend(
            extract_facts_from_table(
                table_id,
                headers,
                table_rows,
                page_num,
                "operational",
                report_year,
                RD_PERSONNEL_ITEMS,
            )
        )
    return upsert_facts(cur, report_id, all_facts)


def _insert_quarterly_facts(cur, report_id: int, report_year: int | None) -> int:
    cur.execute(
        """
        SELECT id, headers, rows, page_num
        FROM structured_tables
        WHERE report_id = %s AND table_type_guess = 'quarterly_financials'
        ORDER BY table_seq
        """,
        (report_id,),
    )
    rows = cur.fetchall()
    all_facts: list[dict] = []
    for table_id, headers, table_rows, page_num in rows:
        all_facts.extend(
            extract_facts_from_table(
                table_id,
                headers,
                table_rows,
                page_num,
                "kpi",
                report_year,
                QUARTERLY_ITEMS,
                use_quarter_columns=True,
            )
        )
    return upsert_facts(cur, report_id, all_facts)


def _insert_by_table_type(
    cur,
    report_id: int,
    report_year: int | None,
    table_type: str,
    stmt_type: str,
    target_items: list[str],
    *,
    extract_all_rows: bool = False,
) -> int:
    cur.execute(
        """
        SELECT id, headers, rows, page_num
        FROM structured_tables
        WHERE report_id = %s AND table_type_guess = %s
        ORDER BY table_seq
        """,
        (report_id, table_type),
    )
    rows = cur.fetchall()
    if not rows:
        return 0

    all_facts: list[dict] = []
    for table_id, headers, table_rows, page_num in rows:
        all_facts.extend(
            extract_facts_from_table(
                table_id,
                headers,
                table_rows,
                page_num,
                stmt_type,
                report_year,
                target_items,
                extract_all_rows=extract_all_rows,
            )
        )
    return upsert_facts(cur, report_id, all_facts)
