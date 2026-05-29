"""Operating analysis payload for HTML templates."""

from __future__ import annotations

from pipeline.analysis import load_latest_analysis
from pipeline.analysis.contracts import OperatingAnalysisResult

from report.providers.formatters import (
    format_flag,
    format_highlights,
    format_snapshot_row,
    group_snapshots,
)

CATEGORY_LABELS = {
    "growth": "增长与收入",
    "profitability": "盈利与利润率",
    "cashflow": "现金流",
    "cost": "成本与费用",
    "industry": "行业对标",
    "other": "其他",
}


def _build_overview_dashboard(result: OperatingAnalysisResult, highlights: list[dict]) -> dict:
    stats = result.stats
    explained = stats.explained_count
    flag_count = stats.flag_count
    headline = (
        f"识别 {flag_count} 项需关注指标，{explained} 项已找到 MD&A 解释"
        if flag_count
        else "未发现显著异常波动指标"
    )

    category_stats = []
    for key in sorted(result.flags_by_category.keys()):
        flags = result.flags_by_category[key]
        if flags:
            category_stats.append(
                {
                    "key": key,
                    "label": CATEGORY_LABELS.get(key, key),
                    "count": len(flags),
                }
            )

    kpi_health = {"flag": 0, "watch": 0, "normal": 0}
    for snap in result.snapshots:
        status = snap.status if snap.status in kpi_health else "normal"
        kpi_health[status] += 1

    return {
        "headline": headline,
        "severity_stats": {
            "high": stats.high_count,
            "medium": stats.medium_count,
            "low": stats.low_count,
        },
        "category_stats": category_stats,
        "top_flags": highlights,
        "kpi_health": kpi_health,
        "explained_ratio": f"{explained}/{flag_count}" if flag_count else "—",
    }


def fetch_analysis_payload(report_id: int) -> dict:
    result = load_latest_analysis(report_id)
    if result is None:
        return {
            "meta": {"report_id": report_id},
            "empty": True,
            "summary": "",
            "stats": {},
            "severity_stats": {},
            "overview_dashboard": {},
            "categories": [],
            "snapshots": [],
            "snapshot_groups": [],
            "watch_rows": [],
            "highlights": [],
            "disclaimer": "",
        }

    categories = []
    for key, flags in sorted(result.flags_by_category.items()):
        categories.append(
            {
                "key": key,
                "label": CATEGORY_LABELS.get(key, key),
                "flags": [format_flag(f) for f in flags],
            }
        )

    snapshots = [format_snapshot_row(s) for s in result.snapshots]
    snapshot_groups = group_snapshots(result.snapshots)
    watch_rows = [row for row in snapshots if row["status"] == "watch"]
    highlights = format_highlights(result.highlights)
    overview_dashboard = _build_overview_dashboard(result, highlights)

    return {
        "meta": {
            "report_id": result.report_id,
            "company_name": result.company_name,
            "stock_code": result.stock_code,
            "report_year": result.report_year,
            "industry": result.industry,
            "run_id": result.run_id,
            "generated_at": result.generated_at.isoformat() if result.generated_at else None,
        },
        "empty": False,
        "summary": result.summary,
        "stats": {
            "flag_count": result.stats.flag_count,
            "explained_count": result.stats.explained_count,
            "unexplained_count": result.stats.unexplained_count,
            "high_count": result.stats.high_count,
            "medium_count": result.stats.medium_count,
            "low_count": result.stats.low_count,
            "snapshot_count": result.stats.snapshot_count,
        },
        "severity_stats": overview_dashboard["severity_stats"],
        "overview_dashboard": overview_dashboard,
        "benchmark_source": result.benchmark_source,
        "disclaimer": result.benchmark_disclaimer,
        "categories": categories,
        "snapshots": snapshots,
        "snapshot_groups": snapshot_groups,
        "watch_rows": watch_rows,
        "highlights": highlights,
    }
