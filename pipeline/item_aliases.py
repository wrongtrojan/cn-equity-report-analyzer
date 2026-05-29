"""Canonical financial item aliases shared by extract, ingest, and QA."""

from __future__ import annotations

# canonical -> 匹配用别名（子串出现在 item_name 或 query 中即可）
ITEM_ALIASES: dict[str, list[str]] = {
    "revenue": ["营业总收入", "营业收入", "一、营业总收入"],
    "net_profit": ["归属于上市公司股东的净利润", "净利润"],
    "deducted_net_profit": ["归属于上市公司股东的扣除非经常性损益的净利润", "扣非净利润"],
    "operating_cashflow": ["经营活动产生的现金流量净额"],
    "basic_eps": ["基本每股收益", "（一）基本每股收益"],
    "diluted_eps": ["稀释每股收益", "（二）稀释每股收益"],
    "roe": ["加权平均净资产收益率"],
    "total_assets": ["资产总额", "资产总计"],
    "net_assets": ["归属于上市公司股东的净资产"],
    "rd_expense": ["研发投入金额", "研发投入"],
    "rd_ratio": ["研发投入占营业总收入比例", "研发投入占营业收入比例"],
    "rd_headcount": ["研发人员数量"],
    "rd_headcount_ratio": ["研发人员数量占比"],
}


def normalize_item_name(name: str) -> str:
    """Strip unit suffixes and list prefixes from financial item names."""
    text = (name or "").strip()
    for suffix in (
        "（元）",
        "（元)",
        "（元/股）",
        "(元)",
        "(元/股)",
        "同比增减",
    ):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    if len(text) > 2 and text[1] == "、" and text[0] in "一二三四五六七八九十":
        text = text[2:]
    return text.strip()


def expand_item_names(names: list[str]) -> list[str]:
    """将 canonical/口语名展开为 DB ILIKE 可用的别名列表（去重保序）。"""
    out: list[str] = []
    for name in names:
        n = (name or "").strip()
        if not n:
            continue
        out.append(n)
        for aliases in ITEM_ALIASES.values():
            if n in aliases:
                out.extend(aliases)
                break
        else:
            for aliases in ITEM_ALIASES.values():
                if any(a in n or n in a for a in aliases):
                    out.extend(aliases)
                    break
    dedup: list[str] = []
    for x in out:
        if x and x not in dedup:
            dedup.append(x)
    return dedup


def revenue_row_tokens() -> list[str]:
    return list(ITEM_ALIASES["revenue"])
