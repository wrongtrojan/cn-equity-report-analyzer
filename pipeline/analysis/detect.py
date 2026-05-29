"""Rule-based anomaly detection on metric series."""

from __future__ import annotations

import hashlib
from decimal import Decimal

from pipeline.analysis.config.settings import load_rules
from pipeline.analysis.contracts import FlagCategory, MetricFlag, MetricSeries, Severity

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}


def _flag_id(rule_id: str, item_name: str, period_label: str) -> str:
    raw = f"{rule_id}|{item_name}|{period_label}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _category_for(item_name: str, rule_id: str) -> FlagCategory:
    if rule_id.startswith("industry"):
        return "industry"
    if "现金流" in item_name or "cash" in rule_id:
        return "cashflow"
    if "成本" in item_name or "费用" in item_name:
        return "cost"
    if "收入" in item_name or "营收" in item_name:
        return "growth"
    if "利润" in item_name or "利率" in item_name or "收益率" in item_name:
        return "profitability"
    return "other"


def detect_anomalies(series_list: list[MetricSeries], report_year: int | None) -> list[MetricFlag]:
    rules = load_rules().get("rules", {})
    flags: dict[tuple[str, str], MetricFlag] = {}
    year_label = str(report_year) if report_year else ""

    for series in series_list:
        yoy = series.yoy_ratio
        if yoy is None:
            continue
        yoy_val = float(yoy.amount)
        base_point = next((p for p in series.points if p.period_label == year_label and not p.is_ratio), None)
        base_amount = float(base_point.amount) if base_point else 0.0

        spike_rule = rules.get("yoy_spike", {})
        plunge_rule = rules.get("yoy_plunge", {})
        min_base = float(spike_rule.get("min_base_amount", 0))

        candidates: list[tuple[str, Severity, str]] = []
        if base_amount >= min_base and yoy_val >= float(spike_rule.get("threshold", 50)):
            candidates.append(
                (
                    "yoy_spike",
                    spike_rule.get("severity", "medium"),
                    f"{series.item_name} {year_label} 同比增减 {yoy_val:.2f}%，增幅较大。",
                )
            )
        if base_amount >= min_base and yoy_val <= float(plunge_rule.get("threshold", -30)):
            candidates.append(
                (
                    "yoy_plunge",
                    plunge_rule.get("severity", "high"),
                    f"{series.item_name} {year_label} 同比增减 {yoy_val:.2f}%，降幅显著。",
                )
            )

        if series.prior_year_value and base_point:
            prior = float(series.prior_year_value.amount)
            current = float(base_point.amount)
            if prior * current < 0:
                candidates.append(
                    (
                        "yoy_sign_flip",
                        rules.get("yoy_sign_flip", {}).get("severity", "medium"),
                        f"{series.item_name} 本期与上期符号发生转变。",
                    )
                )

        for rule_id, severity, summary in candidates:
            key = (series.item_name, year_label)
            direction = "up" if yoy_val > 0 else "down" if yoy_val < 0 else "mixed"
            fact_ids = [p.fact_id for p in [yoy, base_point] if p and p.fact_id]
            new_flag = MetricFlag(
                flag_id=_flag_id(rule_id, series.item_name, year_label),
                rule_id=rule_id,
                severity=severity,
                category=_category_for(series.item_name, rule_id),
                item_name=series.item_name,
                period_label=year_label,
                metric_value=Decimal(str(yoy_val)),
                benchmark_value=None,
                delta=None,
                direction=direction,
                summary=summary,
                confidence=0.9,
                evidence_fact_ids=[fid for fid in fact_ids if fid],
            )
            existing = flags.get(key)
            if existing is None or SEVERITY_ORDER[new_flag.severity] > SEVERITY_ORDER[existing.severity]:
                flags[key] = new_flag
            elif existing.rule_id != new_flag.rule_id:
                existing.summary = f"{existing.summary}；{new_flag.summary}"

    profit_series = next((s for s in series_list if "净利润" in s.item_name), None)
    cash_series = next((s for s in series_list if "经营活动产生的现金流量净额" in s.item_name), None)
    if profit_series and cash_series and profit_series.yoy_ratio and cash_series.yoy_ratio:
        py = float(profit_series.yoy_ratio.amount)
        cy = float(cash_series.yoy_ratio.amount)
        div_rule = rules.get("cash_profit_divergence", {})
        if py > float(div_rule.get("profit_yoy_min", 20)) and cy < float(div_rule.get("cashflow_yoy_max", 0)):
            key = ("cash_profit_divergence", year_label)
            flags[key] = MetricFlag(
                flag_id=_flag_id("cash_profit_divergence", "净利润/经营现金流", year_label),
                rule_id="cash_profit_divergence",
                severity=div_rule.get("severity", "medium"),
                category="cashflow",
                item_name="净利润 vs 经营现金流",
                period_label=year_label,
                metric_value=Decimal(str(py)),
                benchmark_value=Decimal(str(cy)),
                delta=Decimal(str(py - cy)),
                direction="mixed",
                summary=f"净利润同比 {py:.2f}%，而经营现金流同比 {cy:.2f}%，存在背离。",
                confidence=0.88,
                evidence_fact_ids=[
                    fid
                    for fid in [
                        profit_series.yoy_ratio.fact_id if profit_series.yoy_ratio else None,
                        cash_series.yoy_ratio.fact_id if cash_series.yoy_ratio else None,
                    ]
                    if fid
                ],
            )

    return list(flags.values())


def detect_industry_from_series(
    series_list: list[MetricSeries],
    *,
    industry: str | None,
    get_benchmark,
    report_year: int | None,
) -> list[MetricFlag]:
    if not industry:
        return []
    rules = load_rules().get("rules", {})
    year_label = str(report_year) if report_year else ""
    industry_flags: list[MetricFlag] = []

    for series in series_list:
        point = next((p for p in series.points if p.period_label == year_label and not p.is_ratio), None)
        if point is None or point.amount is None:
            continue
        bench = get_benchmark(industry, series.item_name, year_label)
        if bench is None or bench.p50 is None:
            continue
        company_val = point.amount
        p25, p50, p75 = bench.p25, bench.p50, bench.p75
        if p75 is not None and company_val > p75:
            rule_id = "industry_outlier_high"
            industry_flags.append(
                MetricFlag(
                    flag_id=_flag_id(rule_id, series.item_name, year_label),
                    rule_id=rule_id,
                    severity=rules.get(rule_id, {}).get("severity", "medium"),
                    category="industry",
                    item_name=series.item_name,
                    period_label=year_label,
                    metric_value=company_val,
                    benchmark_value=p50,
                    delta=company_val - p50 if p50 else None,
                    direction="up",
                    summary=f"{series.item_name} 高于行业 p75（基准来源：{bench.source}）。",
                    confidence=0.75,
                    evidence_fact_ids=[point.fact_id] if point.fact_id else [],
                    meta={"industry_source": bench.source},
                )
            )
        elif p25 is not None and company_val < p25:
            rule_id = "industry_outlier_low"
            industry_flags.append(
                MetricFlag(
                    flag_id=_flag_id(rule_id, series.item_name, year_label),
                    rule_id=rule_id,
                    severity=rules.get(rule_id, {}).get("severity", "medium"),
                    category="industry",
                    item_name=series.item_name,
                    period_label=year_label,
                    metric_value=company_val,
                    benchmark_value=p50,
                    delta=company_val - p50 if p50 else None,
                    direction="down",
                    summary=f"{series.item_name} 低于行业 p25（基准来源：{bench.source}）。",
                    confidence=0.75,
                    evidence_fact_ids=[point.fact_id] if point.fact_id else [],
                    meta={"industry_source": bench.source},
                )
            )
    return industry_flags
