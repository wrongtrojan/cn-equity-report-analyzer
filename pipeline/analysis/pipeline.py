"""Run operating analysis end-to-end."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from pipeline.analysis.benchmarks import ExternalBenchmarkProvider, MockBenchmarkProvider
from pipeline.analysis.config.settings import load_rules
from pipeline.analysis.contracts import AnalysisRunStats, MetricFlag, OperatingAnalysisResult
from pipeline.analysis.detect import detect_anomalies, detect_industry_from_series
from pipeline.analysis.explain import explain_flags
from pipeline.analysis.metrics import load_all_series
from pipeline.analysis.snapshots import build_snapshots
from pipeline.analysis.writers import save_analysis_run


def _compose_result(
    ctx: dict,
    flags: list[MetricFlag],
    *,
    benchmark_source: str | None,
    snapshots: list | None = None,
) -> OperatingAnalysisResult:
    rules = load_rules()
    disclaimer = rules.get("benchmark", {}).get("disclaimer", "")

    flags_by_category: dict[str, list[MetricFlag]] = defaultdict(list)
    for flag in sorted(flags, key=lambda f: ({"high": 0, "medium": 1, "low": 2}[f.severity], f.item_name)):
        flags_by_category[flag.category].append(flag)

    explained = sum(1 for f in flags if any(e.explanation_type != "none" for e in f.explanations))
    unexplained = len(flags) - explained

    stats = AnalysisRunStats(
        flag_count=len(flags),
        high_count=sum(1 for f in flags if f.severity == "high"),
        medium_count=sum(1 for f in flags if f.severity == "medium"),
        low_count=sum(1 for f in flags if f.severity == "low"),
        explained_count=explained,
        unexplained_count=unexplained,
        industry_compare_available=benchmark_source is not None,
        snapshot_count=len(snapshots or []),
    )

    if flags:
        top = flags[:3]
        summary = "；".join(f.summary.rstrip("。") for f in top) + f"。共识别 {len(flags)} 项需关注指标，其中 {explained} 项找到 MD&A 解释。"
    else:
        summary = "未发现显著异常波动指标。"

    return OperatingAnalysisResult(
        report_id=ctx["report_id"],
        run_id=None,
        company_name=ctx["company_name"],
        stock_code=ctx["stock_code"],
        report_year=ctx.get("report_year"),
        industry=ctx.get("industry"),
        generated_at=None,
        summary=summary,
        highlights=flags,
        flags_by_category=dict(flags_by_category),
        stats=stats,
        benchmark_source=benchmark_source,
        benchmark_disclaimer=disclaimer if benchmark_source == "mock" else "",
        snapshots=snapshots or [],
    )


def run_pipeline(report_id: int, *, skip_llm: bool = False) -> tuple[int, OperatingAnalysisResult]:
    rules = load_rules()
    ctx, series = load_all_series(report_id)

    flags = detect_anomalies(series, ctx.get("report_year"))

    bench_cfg = rules.get("benchmark", {})
    provider_name = bench_cfg.get("default_provider", "mock")
    if provider_name == "external":
        provider = ExternalBenchmarkProvider()
        benchmark_source = "external"
    else:
        provider = MockBenchmarkProvider(seed=int(bench_cfg.get("mock_seed", 42)))
        benchmark_source = "mock"

    industry = ctx.get("industry") or "未知行业"
    flags.extend(
        detect_industry_from_series(
            series,
            industry=industry,
            get_benchmark=provider.get_benchmark,
            report_year=ctx.get("report_year"),
        )
    )

    explain_flags(report_id, flags, skip_llm=skip_llm)
    snapshots = build_snapshots(
        ctx,
        series,
        flags,
        industry=industry,
        get_benchmark=provider.get_benchmark,
    )
    result = _compose_result(ctx, flags, benchmark_source=benchmark_source, snapshots=snapshots)
    result.generated_at = datetime.now(timezone.utc)

    run_id = save_analysis_run(result, config_version=str(rules.get("version", "1.0")))
    result.run_id = run_id
    return run_id, result
