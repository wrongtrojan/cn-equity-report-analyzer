"""Overview page payload: company profile + KPI snapshots."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pipeline.analysis import load_latest_analysis
from pipeline.analysis.readers import fetch_financial_facts, fetch_report_context

from report.providers.company_profile import fetch_company_profile
from report.providers.formatters import format_snapshot_row, yoy_direction


def _format_value(value, unit: str = "", is_ratio: bool = False) -> str:
    from report.providers.formatters import format_value

    return format_value(value, unit, is_ratio)


def _format_yoy(yoy) -> str:
    from report.providers.formatters import format_yoy

    return format_yoy(yoy)


def _snapshots_from_analysis(report_id: int) -> tuple[list[dict], list[dict], bool]:
    result = load_latest_analysis(report_id)
    if not result or not result.snapshots:
        return [], [], False

    core_rows = []
    derived_rows = []
    for s in result.snapshots:
        row = format_snapshot_row(s)
        overview_row = {
            "item_name": row["item_name"],
            "current_value": row["current_value"],
            "prior_value": row["prior_value"],
            "yoy_pct": row["yoy_pct"],
            "yoy_direction": row["yoy_direction"],
            "status": row["status"],
            "status_label": row["status_label"],
            "derived": row["derived"],
        }
        if s.derived:
            derived_rows.append(overview_row)
        else:
            core_rows.append(overview_row)
    return core_rows, derived_rows, True


def _snapshots_fallback(report_id: int) -> list[dict]:
    ctx = fetch_report_context(report_id)
    year = str(ctx.get("report_year") or "")
    facts = fetch_financial_facts(report_id, ["kpi"])
    prior = {}
    if ctx.get("company_id") and ctx.get("report_year"):
        from pipeline.analysis.readers import fetch_prior_year_facts

        for p in fetch_prior_year_facts(ctx["company_id"], ctx["report_year"], ["kpi"]):
            if not p.is_ratio and p.period_label == str(int(ctx["report_year"]) - 1):
                prior[p.item_name] = p

    seen: set[str] = set()
    rows = []
    for f in facts:
        if f.is_ratio or f.period_label != year:
            continue
        name = f.item_name.replace("（元）", "").replace("（元)", "").replace("（元/股）", "")
        if name in seen:
            continue
        seen.add(name)
        prior_pt = prior.get(f.item_name)
        yoy = None
        if prior_pt and prior_pt.amount:
            yoy = (f.amount - prior_pt.amount) / abs(prior_pt.amount) * Decimal(100)
        rows.append(
            {
                "item_name": name,
                "current_value": _format_value(f.amount, f.unit),
                "prior_value": _format_value(prior_pt.amount if prior_pt else None, f.unit),
                "yoy_pct": _format_yoy(yoy),
                "yoy_direction": yoy_direction(yoy),
                "status": "normal",
                "status_label": "正常",
                "derived": False,
            }
        )
    return rows


def fetch_overview_payload(
    report_id: int,
    *,
    skip_qa: bool = False,
    refresh_qa: bool = False,
    output_dir: Path | None = None,
) -> dict:
    profile = fetch_company_profile(
        report_id,
        skip_qa=skip_qa,
        refresh_qa=refresh_qa,
        output_dir=output_dir,
    )
    core_rows, derived_rows, has_analysis = _snapshots_from_analysis(report_id)
    if not core_rows and not derived_rows:
        core_rows = _snapshots_fallback(report_id)
        derived_rows = []

    return {
        "meta": profile["meta"],
        "profile": profile,
        "kpi_rows": core_rows,
        "derived_kpi_rows": derived_rows,
        "has_analysis": has_analysis,
    }
