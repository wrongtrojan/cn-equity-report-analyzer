# pipeline/ingest/ingest.py
"""结构化入库 + 文本 embedding + CLI 入口。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pipeline.extract import (
    Section,
    chunk_text,
    compute_ingest_fingerprint,
    extract_company_info,
    guess_exchange,
    run_extract,
    sha256_text,
    strip_for_chunking,
)
from pipeline.extract.contracts import (
    ExtractResult,
    ExtractedEntity,
    ExtractedFact,
    ExtractedRelation,
    ParsedTable,
    RelationEvidence,
)

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


def insert_tables(cur, report_id: int, tables: list[ParsedTable]) -> dict[int, int]:
    cur.execute(
        "SELECT id, section_key FROM report_sections WHERE report_id = %s",
        (report_id,),
    )
    key_to_id = {}
    for sid, skey in cur.fetchall():
        if skey and skey not in key_to_id:
            key_to_id[skey] = sid

    table_seq_to_id: dict[int, int] = {}
    for t in tables:
        cur.execute(
            """
            INSERT INTO structured_tables (
                report_id, section_id, section_key, table_seq, table_title,
                page_num, row_count, col_count, headers, rows,
                html_raw, header_hash, table_type_guess, source
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,'mineru')
            RETURNING id
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
        table_seq_to_id[t.table_seq] = cur.fetchone()[0]
    return table_seq_to_id


def insert_financial_facts(cur, report_id: int, facts: list[ExtractedFact], table_seq_to_id: dict[int, int]) -> int:
    inserted = 0
    for fact in facts:
        table_id = table_seq_to_id.get(fact.table_seq)
        if table_id is None:
            continue
        cur.execute(
            """
            INSERT INTO financial_facts (
                report_id, table_id, stmt_type, item_name, period_label,
                period_kind, amount, unit, is_ratio, page_num
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (report_id, stmt_type, item_name, period_label) DO UPDATE
            SET amount = EXCLUDED.amount,
                unit = EXCLUDED.unit,
                is_ratio = EXCLUDED.is_ratio,
                page_num = EXCLUDED.page_num,
                table_id = EXCLUDED.table_id,
                period_kind = EXCLUDED.period_kind
            """,
            (
                report_id,
                table_id,
                fact.stmt_type,
                fact.item_name,
                fact.period_label,
                fact.period_kind,
                fact.amount,
                fact.unit,
                fact.is_ratio,
                fact.page_num,
            ),
        )
        inserted += 1
    return inserted


def insert_kg_entities(cur, report_id: int, entities: list[ExtractedEntity]) -> dict[str, int]:
    key_to_id: dict[str, int] = {}
    for entity in entities:
        cur.execute(
            """
            INSERT INTO kg_entities (report_id, entity_key, name, entity_type, attrs)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (report_id, entity_key) DO UPDATE
            SET name = EXCLUDED.name,
                entity_type = EXCLUDED.entity_type,
                attrs = EXCLUDED.attrs
            RETURNING id
            """,
            (
                report_id,
                entity.entity_key,
                entity.name,
                entity.entity_type,
                json.dumps(entity.attrs, ensure_ascii=False),
            ),
        )
        key_to_id[entity.entity_key] = cur.fetchone()[0]
    return key_to_id


def insert_kg_relations(
    cur,
    report_id: int,
    relations: list[ExtractedRelation],
    entity_key_to_id: dict[str, int],
    table_seq_to_id: dict[int, int],
) -> dict[str, int]:
    source_key_to_id: dict[str, int] = {}
    for rel in relations:
        subject_id = entity_key_to_id.get(rel.subject_key)
        object_id = entity_key_to_id.get(rel.object_key)
        if subject_id is None or object_id is None:
            continue
        cur.execute(
            """
            INSERT INTO kg_relations (
                report_id, relation_type, subject_entity_id, object_entity_id,
                attrs, confidence, source, source_key
            ) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
            ON CONFLICT (report_id, source_key) DO UPDATE
            SET relation_type = EXCLUDED.relation_type,
                subject_entity_id = EXCLUDED.subject_entity_id,
                object_entity_id = EXCLUDED.object_entity_id,
                attrs = EXCLUDED.attrs,
                confidence = EXCLUDED.confidence,
                source = EXCLUDED.source
            RETURNING id
            """,
            (
                report_id,
                rel.relation_type,
                subject_id,
                object_id,
                json.dumps(rel.attrs, ensure_ascii=False),
                rel.confidence,
                rel.source,
                rel.source_key,
            ),
        )
        relation_id = cur.fetchone()[0]
        source_key_to_id[rel.source_key] = relation_id
        insert_kg_relation_evidence(cur, relation_id, rel.evidence, table_seq_to_id)
    return source_key_to_id


def insert_kg_relation_evidence(
    cur,
    relation_id: int,
    evidence_items: list[RelationEvidence],
    table_seq_to_id: dict[int, int],
) -> int:
    inserted = 0
    for item in evidence_items:
        table_id = table_seq_to_id.get(item.table_seq) if item.table_seq is not None else None
        cur.execute(
            """
            INSERT INTO kg_relation_evidence (
                relation_id, evidence_type, section_key, page_num, table_id, snippet, attrs
            ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
            """,
            (
                relation_id,
                item.evidence_type,
                item.section_key,
                item.page_num,
                table_id,
                item.snippet,
                json.dumps(item.attrs, ensure_ascii=False),
            ),
        )
        inserted += 1
    return inserted


def ingest_structured(
    parse_dir: Path,
    force: bool = False,
    with_relations: bool = False,
    refine_text_relations: bool = False,
) -> dict:
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
        extracted: ExtractResult = run_extract(
            md_text=md_text,
            middle_path=middle_path,
            aliases=aliases,
            report_year=report_year,
            company_name=stock_name,
            with_relations=with_relations,
            refine_text_relations=refine_text_relations,
        )

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
            seq_to_id = insert_sections(cur, report_id, extracted.sections)
            table_seq_to_id = insert_tables(cur, report_id, extracted.tables)
            fact_count = insert_financial_facts(
                cur,
                report_id,
                extracted.financial_facts,
                table_seq_to_id,
            )
            kg_entity_count = 0
            kg_relation_count = 0
            if with_relations:
                entity_key_to_id = insert_kg_entities(cur, report_id, extracted.entities)
                kg_entity_count = len(entity_key_to_id)
                relation_map = insert_kg_relations(
                    cur,
                    report_id,
                    extracted.relations,
                    entity_key_to_id,
                    table_seq_to_id,
                )
                kg_relation_count = len(relation_map)
            upsert_parsed_artifacts(
                cur, report_id, middle_path, md_path, images_dir, meta, ingest_fp
            )

        conn.commit()
        typed_tables = sum(1 for t in extracted.tables if t.table_type_guess)
        keyed_sections = sum(1 for s in extracted.sections if s.section_key)
        return {
            "status": "success",
            "report_id": report_id,
            "stock_code": stock_code,
            "report_year": report_year,
            "sections": len(extracted.sections),
            "sections_with_key": keyed_sections,
            "tables": len(extracted.tables),
            "tables_typed": typed_tables,
            "facts": fact_count,
            "kg_entities": kg_entity_count,
            "kg_relations": kg_relation_count,
            "relation_candidates": len(extracted.relation_candidates),
            "seq_to_id": seq_to_id,
            "sections_data": extracted.sections,
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
    parser.add_argument("--with-relations", action="store_true", help="启用关系抽取并写入 kg 表")
    parser.add_argument(
        "--refine-text-relations",
        action="store_true",
        help="在 --with-relations 基础上启用 LLM 文本补漏（需配置 OPENAI_API_KEY）",
    )
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
            result = ingest_structured(
                d,
                force=args.force,
                with_relations=args.with_relations,
                refine_text_relations=args.refine_text_relations,
            )
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
