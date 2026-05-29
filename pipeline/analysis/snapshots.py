"""Build full KPI snapshots for each analysis run."""

from __future__ import annotations

from decimal import Decimal

from pipeline.analysis.contracts import MetricFlag, MetricSeries, MetricSnapshot, SnapshotStatus


def _annual_point(series: MetricSeries, year_label: str):
    candidates = [p for p in series.points if p.period_label == year_label and not p.is_ratio]
    year_kind = [p for p in candidates if p.period_kind == "year"]
    if year_kind:
        return year_kind[0]
    return candidates[0] if candidates else None


def _flag_keys(flags: list[MetricFlag]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for flag in flags:
        keys.add((flag.item_name, flag.period_label or ""))
        if flag.rule_id == "cash_profit_divergence":
            continue
    return keys


def build_snapshots(
    ctx: dict,
    series_list: list[MetricSeries],
    flags: list[MetricFlag],
    *,
    industry: str | None,
    get_benchmark,
) -> list[MetricSnapshot]:
    report_year = ctx.get("report_year")
    if not report_year:
        return []

    year_label = str(report_year)
    flag_keys = _flag_keys(flags)
    seen: set[str] = set()
    snapshots: list[MetricSnapshot] = []

    for series in series_list:
        if series.item_name in seen:
            continue
        point = _annual_point(series, year_label)
        if point is None:
            continue
        seen.add(series.item_name)

        prior = series.prior_year_value or _annual_point(series, str(int(report_year) - 1))
        yoy_pct = series.yoy_ratio.amount if series.yoy_ratio else None

        bench = None
        if industry and get_benchmark and not point.derived:
            bench = get_benchmark(industry, series.item_name, year_label)

        status: SnapshotStatus = "normal"
        if (series.item_name, year_label) in flag_keys:
            status = "flag"
        elif yoy_pct is not None and abs(float(yoy_pct)) >= 15:
            status = "watch"

        snapshots.append(
            MetricSnapshot(
                item_name=series.item_name,
                period_label=year_label,
                current_value=point.amount,
                prior_value=prior.amount if prior else None,
                yoy_pct=Decimal(str(yoy_pct)) if yoy_pct is not None else None,
                unit=point.unit or ("%" if point.is_ratio else ""),
                is_ratio=point.is_ratio,
                derived=point.derived,
                industry_p25=bench.p25 if bench else None,
                industry_p50=bench.p50 if bench else None,
                industry_p75=bench.p75 if bench else None,
                status=status,
            )
        )

    return snapshots
