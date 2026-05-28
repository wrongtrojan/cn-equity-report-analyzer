# pipeline/ingest/db.py
from __future__ import annotations

import json
from typing import Any

import psycopg2

from .config import DATABASE_URL, DEFAULT_ALIASES


def connect():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


def load_aliases(conn) -> list[tuple[str, str, int]]:
    aliases = list(DEFAULT_ALIASES)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT alias_pattern, section_key, priority
            FROM section_aliases
            WHERE is_active = TRUE
            ORDER BY priority ASC, id ASC
            """
        )
        aliases.extend(cur.fetchall())
    return aliases


def upsert_company(cur, stock_code: str, stock_name: str, exchange: str | None) -> int:
    cur.execute(
        """
        INSERT INTO companies (stock_code, stock_name, exchange)
        VALUES (%s, %s, %s)
        ON CONFLICT (stock_code) DO UPDATE
        SET stock_name = EXCLUDED.stock_name,
            exchange = COALESCE(EXCLUDED.exchange, companies.exchange),
            updated_at = NOW()
        RETURNING id
        """,
        (stock_code, stock_name, exchange),
    )
    return cur.fetchone()[0]


def upsert_report(cur, company_id, report_year, title, pdf_path, pdf_sha256, pdf_size) -> int:
    cur.execute(
        """
        INSERT INTO reports (
            company_id, report_year, report_type, title,
            pdf_path, pdf_sha256, pdf_size_bytes,
            parse_status, parsed_at
        )
        VALUES (%s, %s, 'annual', %s, %s, %s, %s, 'parsed', NOW())
        ON CONFLICT (pdf_sha256) DO UPDATE
        SET company_id = EXCLUDED.company_id,
            report_year = EXCLUDED.report_year,
            title = EXCLUDED.title,
            pdf_path = EXCLUDED.pdf_path,
            pdf_size_bytes = EXCLUDED.pdf_size_bytes,
            parse_status = 'parsed',
            parsed_at = NOW(),
            updated_at = NOW()
        RETURNING id
        """,
        (company_id, report_year, title, pdf_path, pdf_sha256, pdf_size),
    )
    return cur.fetchone()[0]


def get_ingest_fingerprint(cur, report_id: int) -> str | None:
    cur.execute(
        "SELECT meta_json->>'ingest_fingerprint' FROM parsed_artifacts WHERE report_id = %s",
        (report_id,),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def clear_report_children(cur, report_id: int) -> None:
    for table in ("text_chunks", "financial_facts", "structured_tables", "report_sections"):
        cur.execute(f"DELETE FROM {table} WHERE report_id = %s", (report_id,))


def upsert_parsed_artifacts(cur, report_id, middle_path, md_path, images_dir, meta, ingest_fp):
    fp = meta.get("fingerprint", {})
    cfg = fp.get("parse_config", {})
    meta_json = {
        "source_meta": meta,
        "ingest_fingerprint": ingest_fp,
    }
    cur.execute(
        """
        INSERT INTO parsed_artifacts (
            report_id, middle_json_path, markdown_path, images_dir,
            parse_backend, parse_lang, meta_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (report_id) DO UPDATE
        SET middle_json_path = EXCLUDED.middle_json_path,
            markdown_path = EXCLUDED.markdown_path,
            images_dir = EXCLUDED.images_dir,
            parse_backend = EXCLUDED.parse_backend,
            parse_lang = EXCLUDED.parse_lang,
            meta_json = EXCLUDED.meta_json
        """,
        (
            report_id, str(middle_path), str(md_path),
            str(images_dir) if images_dir and images_dir.exists() else None,
            cfg.get("backend", "pipeline"), cfg.get("lang", "ch"),
            json.dumps(meta_json, ensure_ascii=False),
        ),
    )


def to_pgvector(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"