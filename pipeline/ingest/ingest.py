# pipeline/ingest/ingest.py
"""结构化入库 + 文本 embedding + CLI 入口。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import CHUNK_OVERLAP, CHUNK_SIZE, EMBED_MODEL, PARSE_RESULT_DIR
from .db import (
    clear_report_children,
    connect,
    get_ingest_fingerprint,
    load_aliases,
    to_pgvector,
    upsert_company,
    upsert_parsed_artifacts,
    upsert_report,
)
from .extract import guess_table_type, insert_all_financial_facts
from .markdown import (
    Section,
    attach_page_numbers,
    build_table_page_map,
    chunk_text,
    compute_ingest_fingerprint,
    extract_company_info,
    extract_tables,
    guess_exchange,
    sha256_text,
    split_sections,
    strip_for_chunking,
)

logger = logging.getLogger(__name__)


def insert_sections(cur, report_id, sections):
    seq_to_id = {}
    for sec in sections:
        cur.execute(
            """
            INSERT INTO report_sections (
                report_id, section_key, title_raw, heading_level,
                content_md, content_text, seq_no
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                report_id,
                sec.section_key,
                sec.title_raw,
                sec.heading_level,
                sec.content_md,
                strip_for_chunking(sec.content_md),
                sec.seq_no,
            ),
        )
        seq_to_id[sec.seq_no] = cur.fetchone()[0]
    return seq_to_id


def classify_tables(tables) -> None:
    for table in tables:
        table.table_type_guess = guess_table_type(
            table.headers,
            table.rows,
            table.section_key,
            table.table_title,
        )


def insert_tables(cur, report_id, tables):
    cur.execute(
        "SELECT id, section_key FROM report_sections WHERE report_id = %s",
        (report_id,),
    )
    key_to_id = {}
    for sid, skey in cur.fetchall():
        if skey and skey not in key_to_id:
            key_to_id[skey] = sid

    for t in tables:
        cur.execute(
            """
            INSERT INTO structured_tables (
                report_id, section_id, section_key, table_seq, table_title,
                page_num, row_count, col_count, headers, rows,
                html_raw, header_hash, table_type_guess, source
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,'mineru')
            """,
            (
                report_id,
                key_to_id.get(t.section_key),
                t.section_key,
                t.table_seq,
                t.table_title,
                t.page_num,
                len(t.rows),
                len(t.headers),
                json.dumps(t.headers, ensure_ascii=False),
                json.dumps(t.rows, ensure_ascii=False),
                t.html_raw,
                t.header_hash,
                t.table_type_guess,
            ),
        )


def ingest_structured(parse_dir: Path, force: bool = False) -> dict:
    meta_path = parse_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    if meta.get("status") != "success":
        return {"status": "skipped", "reason": "parse_not_success", "dir": str(parse_dir)}

    outputs = meta.get("outputs", {})
    md_path = parse_dir / outputs["markdown"]
    middle_path = parse_dir / outputs["middle_json"]
    images_dir = parse_dir / outputs.get("images_dir", "images")

    if not md_path.exists() or not middle_path.exists():
        raise FileNotFoundError(f"缺少 markdown 或 middle.json: {parse_dir}")

    md_text = md_path.read_text(encoding="utf-8")
    stock_code, stock_name, report_year, title = extract_company_info(md_text)
    if not all([stock_code, stock_name, report_year]):
        raise ValueError(
            f"无法从 markdown 推断公司信息: code={stock_code}, name={stock_name}, year={report_year}"
        )

    ingest_fp = compute_ingest_fingerprint(
        meta, md_path, middle_path, EMBED_MODEL, CHUNK_SIZE, CHUNK_OVERLAP
    )
    fp = meta["fingerprint"]

    conn = connect()
    try:
        aliases = load_aliases(conn)
        sections = split_sections(md_text, aliases)
        tables = extract_tables(md_text, aliases)
        attach_page_numbers(tables, build_table_page_map(middle_path))
        classify_tables(tables)

        with conn.cursor() as cur:
            company_id = upsert_company(
                cur, stock_code, stock_name, guess_exchange(stock_code)
            )
            report_id = upsert_report(
                cur,
                company_id,
                report_year,
                title,
                fp["source_pdf"],
                fp["pdf_sha256"],
                fp.get("pdf_size"),
            )

            if get_ingest_fingerprint(cur, report_id) == ingest_fp and not force:
                conn.commit()
                return {"status": "skipped", "report_id": report_id, "reason": "fingerprint_unchanged"}

            clear_report_children(cur, report_id)
            seq_to_id = insert_sections(cur, report_id, sections)
            insert_tables(cur, report_id, tables)
            fact_count = insert_all_financial_facts(cur, report_id, report_year)
            upsert_parsed_artifacts(
                cur, report_id, middle_path, md_path, images_dir, meta, ingest_fp
            )

        conn.commit()
        typed_tables = sum(1 for t in tables if t.table_type_guess)
        keyed_sections = sum(1 for s in sections if s.section_key)
        return {
            "status": "success",
            "report_id": report_id,
            "stock_code": stock_code,
            "report_year": report_year,
            "sections": len(sections),
            "sections_with_key": keyed_sections,
            "tables": len(tables),
            "tables_typed": typed_tables,
            "facts": fact_count,
            "seq_to_id": seq_to_id,
            "sections_data": sections,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ingest_embeddings(
    report_id: int,
    sections: list[Section],
    seq_to_id: dict[int, int],
) -> tuple[int, int]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBED_MODEL)
    conn = connect()
    chunk_total = 0
    embed_total = 0
    skipped_no_section = 0

    try:
        with conn.cursor() as cur:
            for sec in sections:
                section_id = seq_to_id.get(sec.seq_no)
                if section_id is None:
                    skipped_no_section += 1
                    logger.warning(
                        "skip embedding: section seq_no=%s title=%r has no section_id",
                        sec.seq_no,
                        sec.title_raw,
                    )
                    continue

                chunks = chunk_text(
                    strip_for_chunking(sec.content_md),
                    CHUNK_SIZE,
                    CHUNK_OVERLAP,
                )
                if not chunks:
                    continue

                section_key = sec.section_key or f"section_{sec.seq_no:04d}"
                vectors = model.encode(
                    chunks,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )

                for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
                    cur.execute(
                        """
                        INSERT INTO text_chunks (
                            report_id, section_id, section_key, chunk_index,
                            content, token_count, content_hash,
                            embedding, embedding_model
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector,%s)
                        ON CONFLICT (report_id, section_id, chunk_index) DO UPDATE
                        SET section_key = EXCLUDED.section_key,
                            content = EXCLUDED.content,
                            token_count = EXCLUDED.token_count,
                            content_hash = EXCLUDED.content_hash,
                            embedding = EXCLUDED.embedding,
                            embedding_model = EXCLUDED.embedding_model
                        """,
                        (
                            report_id,
                            section_id,
                            section_key,
                            idx,
                            chunk,
                            max(1, len(chunk) // 2),
                            sha256_text(chunk),
                            to_pgvector(vec.tolist()),
                            EMBED_MODEL,
                        ),
                    )
                    chunk_total += 1
                    embed_total += 1

        if skipped_no_section:
            logger.warning("ingest_embeddings skipped %s sections without section_id", skipped_no_section)
        conn.commit()
        return chunk_total, embed_total
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def discover_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        p for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(".") and (p / "meta.json").exists()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest MinerU parse_result into PostgreSQL")
    parser.add_argument(
        "--parse-root",
        default=str(PARSE_RESULT_DIR),
        help=f"parse_result 根目录（默认: {PARSE_RESULT_DIR}）",
    )
    parser.add_argument("--force", action="store_true", help="忽略 ingest_fingerprint，强制重建")
    parser.add_argument("--skip-embed", action="store_true", help="跳过 embedding，仅入库结构化数据")
    args = parser.parse_args()

    parse_root = Path(args.parse_root).resolve()
    dirs = discover_dirs(parse_root)
    if not dirs:
        print(f"未找到可入库目录: {parse_root}")
        return 1

    print(f"parse_root={parse_root}")
    print(f"待处理: {len(dirs)} 个目录")

    ok = skip = fail = 0
    for d in dirs:
        print(f"\n==> {d.name}")
        try:
            result = ingest_structured(d, force=args.force)
            summary = {k: v for k, v in result.items() if k not in ("sections_data", "seq_to_id")}
            print(json.dumps(summary, ensure_ascii=False, indent=2))

            if result["status"] == "success" and not args.skip_embed:
                c, e = ingest_embeddings(
                    result["report_id"],
                    result["sections_data"],
                    result["seq_to_id"],
                )
                print(json.dumps({"chunks": c, "embedded": e}, ensure_ascii=False, indent=2))
            elif result["status"] == "success" and args.skip_embed:
                print(
                    json.dumps(
                        {
                            "warning": "已跳过 embedding；叙述类问答将不可用，除非单独重跑 embedding",
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )

            if result["status"] == "success":
                ok += 1
            else:
                skip += 1
        except Exception as exc:
            fail += 1
            print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False, indent=2))

    print(f"\n完成: success={ok}, skipped={skip}, failed={fail}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
