"""Company profile facts for report."""

from __future__ import annotations

from pipeline.db import connect

from report.providers.meta import fetch_meta


def fetch_profile_payload(report_id: int) -> dict:
    meta = fetch_meta(report_id)
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ff.item_name, ff.amount, ff.unit, ff.period_label
            FROM financial_facts ff
            JOIN structured_tables st ON st.id = ff.table_id
            WHERE ff.report_id = %s
              AND st.table_type_guess = 'company_profile_kv'
            ORDER BY ff.id
            """,
            (report_id,),
        )
        rows = cur.fetchall()
    items = [
        {
            "item_name": row[0],
            "amount": str(row[1]) if row[1] is not None else "",
            "unit": row[2] or "",
            "period_label": row[3] or "",
        }
        for row in rows
    ]
    return {"meta": meta, "profile_items": items}
