"""Industry benchmark providers (mock + external table)."""

from __future__ import annotations

import hashlib
import random
from decimal import Decimal

from pipeline.db import connect
from pipeline.item_aliases import expand_item_names, normalize_item_name

from pipeline.analysis.config.settings import load_rules
from pipeline.analysis.contracts import BenchmarkSnapshot
from pipeline.analysis.readers import fetch_financial_facts, fetch_report_context


def _seed_for(industry: str, item_name: str, period_label: str, seed: int) -> int:
    raw = f"{seed}|{industry}|{item_name}|{period_label}"
    return int(hashlib.md5(raw.encode()).hexdigest(), 16) % (2**31)


def _fetch_benchmark_row(
    cur,
    industry: str,
    item_name: str,
    period_label: str,
    *,
    mock_only: bool,
) -> tuple | None:
    source_clause = "source = 'mock'" if mock_only else "source <> 'mock'"
    cur.execute(
        f"""
        SELECT p25, p50, p75, source, meta
        FROM industry_benchmarks
        WHERE industry = %s AND item_name = %s AND period_label = %s AND {source_clause}
        LIMIT 1
        """,
        (industry, item_name, period_label),
    )
    return cur.fetchone()


def _lookup_benchmark(
    industry: str,
    item_name: str,
    period_label: str,
    *,
    mock_only: bool,
) -> BenchmarkSnapshot | None:
    candidates = expand_item_names([normalize_item_name(item_name)])
    seen: set[str] = set()
    with connect() as conn, conn.cursor() as cur:
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            row = _fetch_benchmark_row(cur, industry, candidate, period_label, mock_only=mock_only)
            if row:
                return BenchmarkSnapshot(
                    industry=industry,
                    item_name=item_name,
                    period_label=period_label,
                    p25=Decimal(str(row[0])) if row[0] is not None else None,
                    p50=Decimal(str(row[1])) if row[1] is not None else None,
                    p75=Decimal(str(row[2])) if row[2] is not None else None,
                    source=row[3],
                    meta=row[4] or {},
                )
    return None


class MockBenchmarkProvider:
    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    def get_benchmark(self, industry: str, item_name: str, period_label: str) -> BenchmarkSnapshot | None:
        return _lookup_benchmark(industry, item_name, period_label, mock_only=True)

    def generate_for_report(self, report_id: int) -> int:
        ctx = fetch_report_context(report_id)
        industry = ctx.get("industry") or "未知行业"
        report_year = str(ctx.get("report_year") or "")
        facts = fetch_financial_facts(report_id, ["kpi", "income"])
        seen_keys: set[tuple[str, str]] = set()
        count = 0

        with connect() as conn, conn.cursor() as cur:
            for fact in facts:
                if fact.period_label != report_year:
                    continue
                norm_name = normalize_item_name(fact.item_name)
                key = (norm_name, fact.period_label)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                if fact.is_ratio:
                    anchor = float(fact.amount)
                else:
                    anchor = float(fact.amount)
                if anchor == 0:
                    continue

                rng = random.Random(_seed_for(industry, norm_name, fact.period_label, self.seed))
                if fact.is_ratio:
                    spread = max(abs(anchor) * 0.15, 1.0)
                else:
                    spread = abs(anchor) * 0.2
                p50 = anchor + rng.uniform(-spread, spread)
                p25 = p50 - rng.uniform(spread * 0.5, spread * 1.2)
                p75 = p50 + rng.uniform(spread * 0.5, spread * 1.2)
                cur.execute(
                    """
                    INSERT INTO industry_benchmarks
                        (industry, item_name, period_label, p25, p50, p75, source, meta)
                    VALUES (%s,%s,%s,%s,%s,%s,'mock',%s::jsonb)
                    ON CONFLICT (industry, item_name, period_label, source)
                    DO UPDATE SET p25=EXCLUDED.p25, p50=EXCLUDED.p50, p75=EXCLUDED.p75
                    """,
                    (
                        industry,
                        norm_name,
                        fact.period_label,
                        p25,
                        p50,
                        p75,
                        '{"mock": true}',
                    ),
                )
                count += 1
            conn.commit()
        return count


class ExternalBenchmarkProvider:
    def __init__(self) -> None:
        self._fallback = load_rules().get("benchmark", {}).get("fallback_to_mock", True)
        self._mock = MockBenchmarkProvider()

    def get_benchmark(self, industry: str, item_name: str, period_label: str) -> BenchmarkSnapshot | None:
        bench = _lookup_benchmark(industry, item_name, period_label, mock_only=False)
        if bench:
            return bench
        if self._fallback:
            return self._mock.get_benchmark(industry, item_name, period_label)
        return None
