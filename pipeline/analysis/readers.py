"""Read financial facts, text chunks, and persisted analysis runs."""

from __future__ import annotations

from decimal import Decimal

from pipeline.db import connect

from pipeline.analysis.contracts import (
    AnalysisRunStats,
    FlagExplanation,
    MetricFlag,
    MetricPoint,
    MetricSnapshot,
    OperatingAnalysisResult,
)


def fetch_report_context(report_id: int) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.report_year, r.company_id,
                   c.stock_name, c.stock_code, c.industry
            FROM reports r
            JOIN companies c ON c.id = r.company_id
            WHERE r.id = %s
            """,
            (report_id,),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError(f"report_id={report_id} not found")
    return {
        "report_id": row[0],
        "report_year": row[1],
        "company_id": row[2],
        "company_name": row[3],
        "stock_code": row[4],
        "industry": row[5],
    }


def fetch_financial_facts(report_id: int, stmt_types: list[str] | None = None) -> list[MetricPoint]:
    params: list = [report_id]
    filter_sql = ""
    if stmt_types:
        filter_sql = " AND ff.stmt_type = ANY(%s)"
        params.append(stmt_types)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT ff.id, ff.item_name, ff.period_label, ff.period_kind,
                   ff.amount, ff.unit, ff.is_ratio, ff.stmt_type
            FROM financial_facts ff
            WHERE ff.report_id = %s{filter_sql}
            ORDER BY ff.stmt_type, ff.item_name, ff.period_label
            """,
            params,
        )
        rows = cur.fetchall()

    return [
        MetricPoint(
            fact_id=row[0],
            item_name=row[1],
            period_label=row[2],
            period_kind=row[3] or "other",
            amount=Decimal(str(row[4])) if row[4] is not None else Decimal(0),
            unit=row[5] or "",
            is_ratio=bool(row[6]),
            stmt_type=row[7] or "other",
        )
        for row in rows
    ]


def fetch_prior_year_facts(company_id: int, report_year: int, stmt_types: list[str] | None = None) -> list[MetricPoint]:
    params: list = [company_id, report_year - 1]
    filter_sql = ""
    if stmt_types:
        filter_sql = " AND ff.stmt_type = ANY(%s)"
        params.append(stmt_types)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT ff.id, ff.item_name, ff.period_label, ff.period_kind,
                   ff.amount, ff.unit, ff.is_ratio, ff.stmt_type
            FROM financial_facts ff
            JOIN reports r ON r.id = ff.report_id
            WHERE r.company_id = %s AND r.report_year = %s{filter_sql}
            ORDER BY ff.item_name, ff.period_label
            """,
            params,
        )
        rows = cur.fetchall()

    return [
        MetricPoint(
            fact_id=row[0],
            item_name=row[1],
            period_label=row[2],
            period_kind=row[3] or "other",
            amount=Decimal(str(row[4])) if row[4] is not None else Decimal(0),
            unit=row[5] or "",
            is_ratio=bool(row[6]),
            stmt_type=row[7] or "other",
        )
        for row in rows
    ]


def search_text_chunks_keyword(
    report_id: int,
    keywords: list[str],
    section_keys: list[str],
    limit: int = 10,
) -> list[dict]:
    if not keywords:
        return []
    clauses = " OR ".join(["tc.content ILIKE %s"] * len(keywords))
    params: list = [report_id, section_keys]
    params.extend([f"%{kw}%" for kw in keywords])

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT tc.id, tc.section_key, tc.page_num, tc.content
            FROM text_chunks tc
            WHERE tc.report_id = %s
              AND tc.section_key = ANY(%s)
              AND ({clauses})
            ORDER BY tc.page_num NULLS LAST, tc.chunk_index
            LIMIT %s
            """,
            [*params, limit],
        )
        rows = cur.fetchall()

    return [
        {
            "chunk_id": row[0],
            "section_key": row[1],
            "page_num": row[2],
            "content": row[3],
            "score": 0.5,
        }
        for row in rows
    ]


def _dec(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def load_latest_analysis(report_id: int) -> OperatingAnalysisResult | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ar.id, ar.summary, ar.stats, ar.benchmark_source, ar.created_at,
                   c.stock_name, c.stock_code, c.industry, r.report_year
            FROM analysis_runs ar
            JOIN reports r ON r.id = ar.report_id
            JOIN companies c ON c.id = r.company_id
            WHERE ar.report_id = %s
            ORDER BY ar.created_at DESC
            LIMIT 1
            """,
            (report_id,),
        )
        run = cur.fetchone()
        if not run:
            return None

        run_id, summary, stats_json, benchmark_source, created_at, company_name, stock_code, industry, report_year = run
        stats_data = stats_json or {}

        cur.execute(
            """
            SELECT id, rule_id, severity, category, item_name, period_label,
                   metric_value, benchmark_value, delta, direction,
                   summary, confidence, evidence
            FROM metric_flags
            WHERE run_id = %s
            ORDER BY
                CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                item_name
            """,
            (run_id,),
        )
        flag_rows = cur.fetchall()

        flags: list[MetricFlag] = []
        flags_by_category: dict[str, list[MetricFlag]] = {}
        for row in flag_rows:
            db_flag_id = row[0]
            evidence = row[12] or {}
            flag = MetricFlag(
                flag_id=str(db_flag_id),
                rule_id=row[1],
                severity=row[2],
                category=row[3],
                item_name=row[4],
                period_label=row[5] or "",
                metric_value=_dec(row[6]),
                benchmark_value=_dec(row[7]),
                delta=_dec(row[8]),
                direction=row[9],
                summary=row[10],
                confidence=float(row[11] or 0.0),
                evidence_fact_ids=list(evidence.get("fact_ids") or []),
                meta={k: v for k, v in evidence.items() if k != "fact_ids"},
            )

            cur.execute(
                """
                SELECT chunk_id, snippet, section_key, page_num,
                       relevance_score, explanation_type, reason
                FROM flag_explanations
                WHERE flag_id = %s
                ORDER BY relevance_score DESC NULLS LAST
                """,
                (db_flag_id,),
            )
            expl_rows = cur.fetchall()
            flag.explanations = [
                FlagExplanation(
                    chunk_id=r[0],
                    snippet=r[1] or "",
                    section_key=r[2],
                    page_num=r[3],
                    relevance_score=float(r[4] or 0.0),
                    explanation_type=r[5] or "none",
                    reason=r[6] or "",
                )
                for r in expl_rows
            ]
            flags.append(flag)
            flags_by_category.setdefault(flag.category, []).append(flag)

        cur.execute(
            """
            SELECT item_name, period_label, current_value, prior_value, yoy_pct,
                   unit, is_ratio, derived, industry_p25, industry_p50, industry_p75, status
            FROM metric_snapshots
            WHERE run_id = %s
            ORDER BY derived ASC, item_name
            """,
            (run_id,),
        )
        snapshot_rows = cur.fetchall()
        snapshots = [
            MetricSnapshot(
                item_name=row[0],
                period_label=row[1],
                current_value=_dec(row[2]),
                prior_value=_dec(row[3]),
                yoy_pct=_dec(row[4]),
                unit=row[5] or "",
                is_ratio=bool(row[6]),
                derived=bool(row[7]),
                industry_p25=_dec(row[8]),
                industry_p50=_dec(row[9]),
                industry_p75=_dec(row[10]),
                status=row[11] or "normal",
            )
            for row in snapshot_rows
        ]

        disclaimer = ""
        if benchmark_source == "mock":
            disclaimer = "行业基准为模拟数据，非真实同业统计，仅供参考。"

        return OperatingAnalysisResult(
            report_id=report_id,
            run_id=run_id,
            company_name=company_name,
            stock_code=stock_code,
            report_year=report_year,
            industry=industry,
            generated_at=created_at,
            summary=summary or "",
            highlights=flags,
            flags_by_category=flags_by_category,
            stats=AnalysisRunStats(
                flag_count=int(stats_data.get("flag_count", len(flags))),
                high_count=int(stats_data.get("high_count", 0)),
                medium_count=int(stats_data.get("medium_count", 0)),
                low_count=int(stats_data.get("low_count", 0)),
                explained_count=int(stats_data.get("explained_count", 0)),
                unexplained_count=int(stats_data.get("unexplained_count", 0)),
                industry_compare_available=bool(stats_data.get("industry_compare_available", False)),
                snapshot_count=int(stats_data.get("snapshot_count", len(snapshots))),
            ),
            benchmark_source=benchmark_source,
            benchmark_disclaimer=disclaimer,
            snapshots=snapshots,
        )
