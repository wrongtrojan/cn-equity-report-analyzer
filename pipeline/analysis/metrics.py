"""Load metric series and derived margins."""

from __future__ import annotations

from decimal import Decimal

from pipeline.analysis.config.settings import load_rules
from pipeline.analysis.contracts import MetricPoint, MetricSeries
from pipeline.analysis.readers import fetch_financial_facts, fetch_prior_year_facts, fetch_report_context


from pipeline.item_aliases import normalize_item_name


def _normalize_item_key(name: str) -> str:
    return normalize_item_name(name)


def _group_series(facts: list[MetricPoint], watchlist: set[str] | None = None) -> list[MetricSeries]:
    by_item: dict[str, list[MetricPoint]] = {}
    yoy_by_base: dict[str, MetricPoint] = {}

    for fact in facts:
        name = fact.item_name
        if name.endswith("同比增减"):
            base = _normalize_item_key(name[: -len("同比增减")])
            yoy_by_base[base] = fact
            continue
        norm = _normalize_item_key(name)
        if watchlist and norm not in watchlist and not any(w in norm for w in watchlist):
            continue
        by_item.setdefault(norm, []).append(fact)

    series_list: list[MetricSeries] = []
    for item_name, points in sorted(by_item.items()):
        series = MetricSeries(item_name=item_name, points=sorted(points, key=lambda p: p.period_label))
        series.yoy_ratio = yoy_by_base.get(item_name)
        series_list.append(series)
    return series_list


def _annual_point(points: list[MetricPoint], year_label: str) -> MetricPoint | None:
    candidates = [p for p in points if p.period_label == year_label and not p.is_ratio]
    year_kind = [p for p in candidates if p.period_kind == "year"]
    if year_kind:
        return year_kind[0]
    return candidates[0] if candidates else None


def _attach_computed_yoy(series_list: list[MetricSeries], report_year: int | None) -> None:
    if not report_year:
        return
    year_label = str(report_year)
    prior_label = str(report_year - 1)
    for series in series_list:
        if series.yoy_ratio is not None:
            continue
        current = _annual_point(series.points, year_label)
        prior = _annual_point(series.points, prior_label) or series.prior_year_value
        if current is None or prior is None or prior.amount == 0:
            continue
        yoy_pct = (current.amount - prior.amount) / abs(prior.amount) * Decimal(100)
        series.yoy_ratio = MetricPoint(
            item_name=f"{series.item_name}同比增减",
            period_label=year_label,
            period_kind="year",
            amount=yoy_pct,
            unit="%",
            is_ratio=True,
            stmt_type=current.stmt_type,
            derived=True,
        )
        if series.prior_year_value is None:
            series.prior_year_value = prior


def _find_amount(facts: list[MetricPoint], names: list[str], period_label: str) -> Decimal | None:
    for fact in facts:
        if fact.period_label != period_label or fact.is_ratio:
            continue
        norm = _normalize_item_key(fact.item_name)
        if fact.item_name in names or norm in names:
            return fact.amount
    return None


def build_derived_series(income_facts: list[MetricPoint], report_year: int | None) -> list[MetricSeries]:
    if not report_year:
        return []
    period_label = str(report_year)
    revenue = _find_amount(income_facts, ["营业总收入", "营业收入"], period_label)
    cost = _find_amount(income_facts, ["营业成本"], period_label)
    net_profit = _find_amount(income_facts, ["归属于上市公司股东的净利润", "净利润"], period_label)

    derived: list[MetricSeries] = []
    if revenue and revenue != 0 and cost is not None:
        margin = (revenue - cost) / revenue * Decimal(100)
        derived.append(
            MetricSeries(
                item_name="毛利率",
                points=[
                    MetricPoint(
                        item_name="毛利率",
                        period_label=period_label,
                        period_kind="year",
                        amount=margin,
                        unit="%",
                        is_ratio=True,
                        stmt_type="income",
                        derived=True,
                    )
                ],
            )
        )
    if revenue and revenue != 0 and net_profit is not None:
        nm = net_profit / revenue * Decimal(100)
        derived.append(
            MetricSeries(
                item_name="净利率",
                points=[
                    MetricPoint(
                        item_name="净利率",
                        period_label=period_label,
                        period_kind="year",
                        amount=nm,
                        unit="%",
                        is_ratio=True,
                        stmt_type="income",
                        derived=True,
                    )
                ],
            )
        )
    return derived


def load_all_series(report_id: int) -> tuple[dict, list[MetricSeries]]:
    ctx = fetch_report_context(report_id)
    rules = load_rules()
    kpi_watch = set(rules.get("watchlist", {}).get("kpi", []))
    income_watch = set(rules.get("watchlist", {}).get("income", []))

    kpi_facts = fetch_financial_facts(report_id, ["kpi"])
    income_facts = fetch_financial_facts(report_id, ["income"])

    series = _group_series(kpi_facts, kpi_watch)
    series.extend(_group_series(income_facts, income_watch))

    prior = fetch_prior_year_facts(ctx["company_id"], ctx["report_year"] or 0, ["kpi", "income"])
    prior_map = {(_normalize_item_key(p.item_name), p.period_label): p for p in prior if not p.is_ratio}

    report_year = str(ctx["report_year"]) if ctx["report_year"] else ""
    for s in series:
        for pt in s.points:
            if pt.is_ratio:
                continue
            key = (s.item_name, str(int(report_year) - 1) if report_year.isdigit() else "")
            prior_pt = prior_map.get(key)
            if prior_pt:
                s.prior_year_value = prior_pt
                break

    _attach_computed_yoy(series, int(report_year) if report_year.isdigit() else None)
    series.extend(build_derived_series(income_facts, ctx.get("report_year")))
    return ctx, series
