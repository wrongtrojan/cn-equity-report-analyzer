"""Report meta from companies/reports."""

from __future__ import annotations

from pipeline.db import connect


def fetch_meta(report_id: int) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.stock_name, c.stock_code, c.industry, r.report_year, r.title
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
        "report_id": report_id,
        "company_name": row[0],
        "stock_code": row[1],
        "industry": row[2],
        "report_year": row[3],
        "title": row[4],
    }
