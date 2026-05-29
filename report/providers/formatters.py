"""Shared formatters for report providers."""

from __future__ import annotations

import re
from decimal import Decimal

from pipeline.analysis.contracts import FlagExplanation, MetricFlag, MetricSnapshot

RULE_LABELS = {
    "yoy_spike": "同比异常增长",
    "yoy_plunge": "同比异常下降",
    "yoy_sign_flip": "符号反转",
    "cash_profit_divergence": "利润与现金流背离",
    "industry_outlier_high": "高于行业 p75",
    "industry_outlier_low": "低于行业 p25",
    "margin_shift": "利润率变动",
    "quarter_volatility": "季度波动",
}

EXPL_LABELS = {
    "direct": "直接解释",
    "indirect": "相关背景",
    "none": "未找到解释",
}

DIRECTION_LABELS = {"up": "上升", "down": "下降", "mixed": "背离"}

STATUS_LABELS = {"normal": "正常", "watch": "关注", "flag": "异常"}
SEVERITY_LABELS = {"high": "高", "medium": "中", "low": "低"}

SNAPSHOT_GROUP_ORDER = [
    ("growth", "增长与收入"),
    ("profitability", "盈利与利润率"),
    ("cashflow", "现金流"),
    ("derived", "派生指标"),
    ("other", "其他"),
]

SNAPSHOT_GROUP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "growth": ("收入", "营收", "资产"),
    "profitability": ("利润", "收益率", "利率", "每股"),
    "cashflow": ("现金流",),
    "derived": ("毛利率", "净利率"),
}


def clean_snippet(text: str, max_len: int = 280) -> str:
    if not text:
        return ""
    cleaned = text
    cleaned = re.sub(r"[\uf052□]\s*适用\s*[\uf052□]?\s*不适用", "", cleaned)
    cleaned = re.sub(r"适用\s*□不适用", "", cleaned)
    cleaned = re.sub(r"□适用\s*不适用", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > max_len:
        return cleaned[: max_len - 1].rstrip() + "…"
    return cleaned


def format_value(value, unit: str = "", is_ratio: bool = False) -> str:
    if value is None:
        return "—"
    try:
        num = float(value)
        if is_ratio or unit == "%" or (unit and "%" in unit) or abs(num) < 1000:
            return f"{num:.2f}%"
        return f"{num:,.2f}{unit}"
    except (TypeError, ValueError):
        return str(value)


def format_yoy(yoy) -> str:
    if yoy is None:
        return "—"
    try:
        return f"{float(yoy):+.2f}%"
    except (TypeError, ValueError):
        return "—"


def yoy_direction(yoy) -> str:
    if yoy is None:
        return "flat"
    try:
        val = float(yoy)
        if val > 0.01:
            return "up"
        if val < -0.01:
            return "down"
    except (TypeError, ValueError):
        pass
    return "flat"


def format_industry_range(p25, p75) -> str:
    if p25 is None and p75 is None:
        return "—"
    return f"{format_value(p25)} ~ {format_value(p75)}"


def rule_label(rule_id: str) -> str:
    return RULE_LABELS.get(rule_id, rule_id)


def snapshot_group_key(item_name: str, derived: bool = False) -> str:
    if derived:
        return "derived"
    for key, keywords in SNAPSHOT_GROUP_KEYWORDS.items():
        if key == "derived":
            continue
        if any(kw in item_name for kw in keywords):
            return key
    return "other"


def industry_position(
    current: Decimal | float | None,
    p25: Decimal | float | None,
    p50: Decimal | float | None,
    p75: Decimal | float | None,
    *,
    derived: bool = False,
) -> dict:
    if derived:
        return {
            "position": "na",
            "label": "派生指标不对标",
            "marker_pct": None,
            "range_start_pct": 25,
            "range_end_pct": 75,
        }
    if current is None or p25 is None or p75 is None:
        return {
            "position": "unknown",
            "label": "暂无行业基准（请先 mock_benchmark）",
            "marker_pct": None,
            "range_start_pct": 25,
            "range_end_pct": 75,
        }

    cur = float(current)
    lo = float(p25)
    hi = float(p75)
    span = hi - lo if hi != lo else abs(hi) or 1.0
    marker = max(0.0, min(100.0, (cur - lo) / span * 100.0))

    if cur < lo:
        position = "below_p25"
        label = "低于行业 p25"
    elif cur > hi:
        position = "above_p75"
        label = "高于行业 p75"
    else:
        position = "in_range"
        label = "处于行业 p25–p75 区间"

    if p50 is not None:
        mid = float(p50)
        if cur > mid * 1.05:
            label += "（偏上）"
        elif cur < mid * 0.95:
            label += "（偏下）"

    return {
        "position": position,
        "label": label,
        "marker_pct": round(marker, 1),
        "range_start_pct": 25,
        "range_end_pct": 75,
    }


def format_snapshot_row(snapshot: MetricSnapshot) -> dict:
    pos = industry_position(
        snapshot.current_value,
        snapshot.industry_p25,
        snapshot.industry_p50,
        snapshot.industry_p75,
        derived=snapshot.derived,
    )
    industry_p50 = format_value(snapshot.industry_p50) if snapshot.industry_p50 is not None else "—"
    industry_range = format_industry_range(snapshot.industry_p25, snapshot.industry_p75)
    if snapshot.derived:
        industry_p50 = "—"
        industry_range = "—"
    return {
        "item_name": snapshot.item_name,
        "current_value": format_value(snapshot.current_value, snapshot.unit, snapshot.is_ratio),
        "prior_value": format_value(snapshot.prior_value, snapshot.unit, snapshot.is_ratio),
        "yoy_pct": format_yoy(snapshot.yoy_pct),
        "yoy_direction": yoy_direction(snapshot.yoy_pct),
        "industry_p50": industry_p50,
        "industry_range": industry_range,
        "status": snapshot.status,
        "status_label": STATUS_LABELS.get(snapshot.status, snapshot.status),
        "derived": snapshot.derived,
        "group_key": snapshot_group_key(snapshot.item_name, snapshot.derived),
        "industry_position": pos["position"],
        "industry_label": pos["label"],
        "industry_marker_pct": pos["marker_pct"],
    }


def group_snapshots(snapshots: list[MetricSnapshot]) -> list[dict]:
    buckets: dict[str, list[dict]] = {k: [] for k, _ in SNAPSHOT_GROUP_ORDER}
    for snap in snapshots:
        row = format_snapshot_row(snap)
        buckets[row["group_key"]].append(row)

    groups = []
    for key, label in SNAPSHOT_GROUP_ORDER:
        rows = buckets.get(key) or []
        if rows:
            groups.append({"key": key, "label": label, "rows": rows})
    return groups


def format_flag_metrics(flag: MetricFlag) -> list[dict[str, str]]:
    if flag.rule_id == "cash_profit_divergence":
        return [
            {"label": "净利润 YoY", "value": format_value(flag.metric_value, "%")},
            {"label": "经营现金流 YoY", "value": format_value(flag.benchmark_value, "%")},
            {"label": "背离幅度", "value": format_value(flag.delta, " pp")},
        ]
    if flag.rule_id.startswith("industry_outlier"):
        return [
            {"label": "公司值", "value": format_value(flag.metric_value)},
            {"label": "行业 p50", "value": format_value(flag.benchmark_value)},
            {"label": "与 p50 差值", "value": format_value(flag.delta)},
        ]
    metrics = []
    if flag.metric_value is not None:
        unit = "%" if flag.rule_id.startswith("yoy") else ""
        metrics.append({"label": "指标值", "value": format_value(flag.metric_value, unit)})
    if flag.benchmark_value is not None:
        metrics.append({"label": "对比值", "value": format_value(flag.benchmark_value)})
    if flag.delta is not None:
        metrics.append({"label": "差值", "value": format_value(flag.delta)})
    return metrics


def _expl_sort_key(expl: FlagExplanation) -> tuple[int, float]:
    type_order = {"direct": 0, "indirect": 1, "none": 2}
    return (type_order.get(expl.explanation_type, 9), -float(expl.relevance_score or 0))


def split_explanations(explanations: list[FlagExplanation]) -> tuple[dict | None, list[dict]]:
    candidates = [e for e in explanations if e.explanation_type != "none" or e.snippet]
    if not candidates:
        none_expls = [e for e in explanations if e.explanation_type == "none"]
        if none_expls:
            e = none_expls[0]
            return (
                {
                    "type": "none",
                    "type_label": EXPL_LABELS["none"],
                    "reason": e.reason or "年报 MD&A 未找到对该指标的明确解释",
                    "snippet": "",
                    "citation": "",
                },
                [],
            )
        return None, []

    ranked = sorted(candidates, key=_expl_sort_key)
    primary = ranked[0]
    others = ranked[1:]

    def _to_dict(e: FlagExplanation) -> dict:
        citation = ""
        if e.section_key and e.page_num:
            citation = f"{e.section_key} · 第 {e.page_num} 页"
        elif e.section_key:
            citation = e.section_key
        return {
            "type": e.explanation_type,
            "type_label": EXPL_LABELS.get(e.explanation_type, e.explanation_type),
            "reason": e.reason,
            "snippet": clean_snippet(e.snippet),
            "citation": citation,
        }

    return _to_dict(primary), [_to_dict(e) for e in others]


def format_flag(flag: MetricFlag) -> dict:
    primary, others = split_explanations(flag.explanations)
    has_direct = primary is not None and primary.get("type") == "direct"
    return {
        "severity": flag.severity,
        "severity_label": SEVERITY_LABELS.get(flag.severity, flag.severity),
        "rule_id": flag.rule_id,
        "rule_label": rule_label(flag.rule_id),
        "item_name": flag.item_name,
        "period_label": flag.period_label,
        "summary": flag.summary,
        "direction": flag.direction,
        "direction_label": DIRECTION_LABELS.get(flag.direction or "", "") if flag.direction else "",
        "confidence": round(float(flag.confidence), 2) if flag.confidence else None,
        "metrics": format_flag_metrics(flag),
        "primary_explanation": primary,
        "other_explanations": others,
        "has_direct_explanation": has_direct,
        "is_industry_flag": flag.rule_id.startswith("industry_outlier"),
    }


def format_highlights(flags: list[MetricFlag], limit: int = 3) -> list[dict]:
    severity_order = {"high": 0, "medium": 1, "low": 2}
    sorted_flags = sorted(flags, key=lambda f: (severity_order.get(f.severity, 9), f.item_name))
    out = []
    for flag in sorted_flags[:limit]:
        out.append(
            {
                "severity": flag.severity,
                "severity_label": SEVERITY_LABELS.get(flag.severity, flag.severity),
                "item_name": flag.item_name,
                "summary": flag.summary,
                "rule_label": rule_label(flag.rule_id),
            }
        )
    return out
