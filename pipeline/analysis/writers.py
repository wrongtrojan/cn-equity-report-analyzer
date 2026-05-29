"""Persist analysis runs to PostgreSQL."""

from __future__ import annotations

import json
from decimal import Decimal

from pipeline.db import connect

from pipeline.analysis.contracts import MetricSnapshot, OperatingAnalysisResult


def _dec(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def save_analysis_run(result: OperatingAnalysisResult, *, config_version: str) -> int:
    stats = {
        "flag_count": result.stats.flag_count,
        "high_count": result.stats.high_count,
        "medium_count": result.stats.medium_count,
        "low_count": result.stats.low_count,
        "explained_count": result.stats.explained_count,
        "unexplained_count": result.stats.unexplained_count,
        "industry_compare_available": result.stats.industry_compare_available,
        "snapshot_count": result.stats.snapshot_count,
    }

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO analysis_runs
                (report_id, run_type, config_version, summary, stats, benchmark_source)
            VALUES (%s, 'operating', %s, %s, %s::jsonb, %s)
            RETURNING id
            """,
            (
                result.report_id,
                config_version,
                result.summary,
                json.dumps(stats, ensure_ascii=False),
                result.benchmark_source,
            ),
        )
        run_id = cur.fetchone()[0]

        for flag in result.highlights:
            evidence = {
                "fact_ids": flag.evidence_fact_ids,
                **flag.meta,
            }
            cur.execute(
                """
                INSERT INTO metric_flags (
                    run_id, rule_id, severity, category, item_name, period_label,
                    metric_value, benchmark_value, delta, direction,
                    summary, confidence, evidence
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                RETURNING id
                """,
                (
                    run_id,
                    flag.rule_id,
                    flag.severity,
                    flag.category,
                    flag.item_name,
                    flag.period_label,
                    _dec(flag.metric_value),
                    _dec(flag.benchmark_value),
                    _dec(flag.delta),
                    flag.direction,
                    flag.summary,
                    flag.confidence,
                    json.dumps(evidence, ensure_ascii=False),
                ),
            )
            db_flag_id = cur.fetchone()[0]

            for expl in flag.explanations:
                cur.execute(
                    """
                    INSERT INTO flag_explanations (
                        flag_id, chunk_id, snippet, section_key, page_num,
                        relevance_score, explanation_type, reason
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        db_flag_id,
                        expl.chunk_id,
                        expl.snippet,
                        expl.section_key,
                        expl.page_num,
                        expl.relevance_score,
                        expl.explanation_type,
                        expl.reason,
                    ),
                )

        for snap in result.snapshots:
            cur.execute(
                """
                INSERT INTO metric_snapshots (
                    run_id, item_name, period_label, current_value, prior_value, yoy_pct,
                    unit, is_ratio, derived, industry_p25, industry_p50, industry_p75, status
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    run_id,
                    snap.item_name,
                    snap.period_label,
                    _dec(snap.current_value),
                    _dec(snap.prior_value),
                    _dec(snap.yoy_pct),
                    snap.unit,
                    snap.is_ratio,
                    snap.derived,
                    _dec(snap.industry_p25),
                    _dec(snap.industry_p50),
                    _dec(snap.industry_p75),
                    snap.status,
                ),
            )

        conn.commit()
    return run_id
