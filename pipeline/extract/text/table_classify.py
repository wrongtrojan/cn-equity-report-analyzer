"""Table type classifier."""

from __future__ import annotations

import re
from typing import Callable

from pipeline.item_aliases import revenue_row_tokens

from .table_semantics import headers_text, table_text_blob


def guess_table_type(
    headers: list[str],
    rows: list[list[str]],
    section_key: str | None,
    table_title: str | None = None,
) -> str | None:
    text = table_text_blob(headers, rows)
    hdr = headers_text(headers)
    title = table_title or ""

    rules: list[tuple[int, str, Callable[[], bool]]] = [
        # Relation-related types (priority 10–23)
        (10, "top10_shareholders", lambda: _is_top10_shareholders(section_key, text, title)),
        (11, "restricted_shares", lambda: _is_restricted_shares(section_key, text, title)),
        (12, "shareholder_count_summary", lambda: _is_shareholder_count_summary(section_key, text, hdr, title)),
        (13, "controller_info", lambda: _is_controller_info(section_key, text, hdr, title)),
        (14, "director_concurrent_jobs", lambda: _is_director_concurrent_jobs(section_key, text, hdr)),
        (15, "director_changes", lambda: _is_director_changes(section_key, text, hdr)),
        (16, "director_compensation", lambda: _is_director_compensation(section_key, text, hdr, title)),
        (17, "director_bio", lambda: _is_director_bio(section_key, text, hdr, title)),
        (18, "director_roster", lambda: _is_director_roster(section_key, text, hdr)),
        (19, "subsidiaries", lambda: _is_subsidiaries(section_key, text, hdr)),
        (20, "related_party_balance", lambda: _is_related_party_balance(section_key, text, hdr, title)),
        (21, "related_party_transactions", lambda: _is_related_party_transactions(section_key, text, hdr, title)),
        (22, "related_party_list", lambda: _is_related_party_list(section_key, text, hdr, title)),
        (23, "related_party_guarantee", lambda: _is_related_party_guarantee(section_key, text, hdr, title)),
        # Financial / other types (priority 30+)
        (30, "key_financials_summary", lambda: _is_key_financials_summary(section_key, text, hdr)),
        (32, "quarterly_financials", lambda: _is_quarterly_financials(section_key, text, hdr)),
        (33, "rd_investment_summary", lambda: _is_rd_investment_summary(text, hdr)),
        (34, "rd_personnel_summary", lambda: _is_rd_personnel_summary(text, hdr)),
        (35, "company_profile_kv", lambda: "股票简称" in hdr and "股票代码" in hdr),
        (36, "bond_financials", lambda: section_key == "bond_financials"),
        (37, "balance_sheet", lambda: _is_balance_sheet(section_key, text, hdr)),
        (38, "income_statement", lambda: _is_income_statement(section_key, text, hdr)),
        (39, "cashflow_statement", lambda: _is_cashflow_statement(section_key, text, hdr)),
        (40, "glossary_terms", lambda: section_key == "glossary" and "释义项" in hdr),
    ]

    matched: list[tuple[int, str]] = []
    for priority, table_type, predicate in rules:
        if predicate():
            matched.append((priority, table_type))
    if not matched:
        return None
    return sorted(matched)[0][1]


def _is_top10_shareholders(section_key: str | None, text: str, title: str) -> bool:
    if section_key not in {"top10_shareholders", "shareholder_section", None}:
        return False
    if "限售" in title or "限售" in text and "持股比例" not in text:
        return False
    return ("股东名称" in text or "股东姓名" in text) and (
        "持股比例" in text or "持股数量" in text or "报告期末持股数量" in text
    )


def _is_restricted_shares(section_key: str | None, text: str, title: str) -> bool:
    if section_key not in {"shareholder_section", "top10_shareholders", None}:
        return False
    if "限售" not in title and "限售" not in text:
        return False
    return "股东名称" in text and "持股比例" not in text


def _is_shareholder_count_summary(section_key: str | None, text: str, hdr: str, title: str) -> bool:
    if section_key not in {"shareholder_section", None}:
        return False
    if "股份变动" in title or "本次变动" in text:
        return True
    return "普通股股东总数" in text or "普通股股东总数" in hdr


def _is_controller_info(section_key: str | None, text: str, hdr: str, title: str) -> bool:
    if section_key not in {"shareholder_section", "top10_shareholders", None}:
        return False
    return (
        "控股股东" in title
        or "实际控制人" in title
        or "控股股东姓名" in text
        or "实际控制人姓名" in text
        or "控股股东姓名" in hdr
    )


def _is_director_concurrent_jobs(section_key: str | None, text: str, hdr: str) -> bool:
    if section_key != "directors_supervisors":
        return False
    return "其他单位名称" in text or "在其他单位担任的职务" in text


def _is_director_changes(section_key: str | None, text: str, hdr: str) -> bool:
    if section_key != "directors_supervisors":
        return False
    if "其他单位名称" in text:
        return False
    has_role_col = "担任的职务" in text or "担任的职务" in hdr
    has_change = any(k in text for k in ("被选举", "聘任", "离任", "任期满离任"))
    return has_role_col and has_change and "姓名" in text


def _is_director_compensation(section_key: str | None, text: str, hdr: str, title: str) -> bool:
    if section_key not in {"directors_supervisors", "related_parties"}:
        return False
    if "薪酬" in title or "报酬" in title:
        return True
    return any(k in text or k in hdr for k in ("税前报酬", "关键管理人员薪酬", "从公司获得的税前报酬"))


def _is_director_bio(section_key: str | None, text: str, hdr: str, title: str) -> bool:
    if section_key != "directors_supervisors":
        return False
    if re.search(r"[\u4e00-\u9fff]{2,4}(女士|先生)：", title):
        return True
    if "适用" in title and "不适用" in title:
        return "姓名" not in hdr
    return False


def _is_director_roster(section_key: str | None, text: str, hdr: str) -> bool:
    if section_key != "directors_supervisors":
        return False
    if "其他单位名称" in text or "税前报酬" in text or "被选举" in text:
        return False
    return "姓名" in text and ("职务" in text or "担任的职务" in text) and (
        "性别" in text or "任职状态" in text
    )


def _is_subsidiaries(section_key: str | None, text: str, hdr: str) -> bool:
    if section_key != "subsidiaries":
        return False
    return "公司名称" in text or "公司名称" in hdr or "子公司" in text or "参股公司" in text


def _is_related_party_balance(section_key: str | None, text: str, hdr: str, title: str) -> bool:
    if section_key not in {"related_parties", "significant_matters", None}:
        return False
    if "应收项目" in title or "应付项目" in title or "使用权资产" in title:
        return True
    return "关联方" in text and any(k in text or k in hdr for k in ("期末余额", "期初余额", "账面余额", "期末账面余额"))


def _is_related_party_transactions(section_key: str | None, text: str, hdr: str, title: str) -> bool:
    if section_key not in {"related_parties", "significant_matters", None}:
        return False
    if "关联担保" in title:
        return False
    if "关联租赁" in title:
        return True
    return "关联方" in text and any(
        k in text or k in hdr for k in ("关联交易内容", "交易内容", "本期发生额", "支付的租金")
    )


def _is_related_party_list(section_key: str | None, text: str, hdr: str, title: str) -> bool:
    if section_key not in {"related_parties", "significant_matters", None}:
        return False
    if "关联交易" in title and "购销" not in title:
        return False
    return any(k in text or k in hdr for k in ("关联方名称", "其他关联方名称", "合营或联营企业名称", "关联关系"))


def _is_related_party_guarantee(section_key: str | None, text: str, hdr: str, title: str) -> bool:
    if section_key not in {"related_parties", "significant_matters", None}:
        return False
    if "关联担保" in title or "重大担保" in title:
        return True
    return "被担保方" in text or ("担保额度" in text and "关联方" in section_key if section_key else False)


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
    return has_period and ("一、营业总收入" in text or (_has_revenue_row(text) and "营业成本" in text and "净利润" in text))


def _is_cashflow_statement(section_key: str | None, text: str, hdr: str) -> bool:
    if section_key != "financial_statements":
        return False
    has_period = _has_annual_period(hdr)
    return has_period and "经营活动产生的现金流量净额" in text
