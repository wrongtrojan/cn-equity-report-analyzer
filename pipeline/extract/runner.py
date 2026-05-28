from __future__ import annotations

from pathlib import Path

from pipeline.extract.contracts import ExtractResult
from pipeline.extract.relations import build_relations, refine_relations_from_text
from pipeline.extract.text import (
    attach_page_numbers,
    build_financial_facts,
    build_table_page_map,
    extract_tables,
    guess_table_type,
    split_sections,
)


def run_extract(
    md_text: str,
    middle_path: Path,
    aliases,
    report_year: int | None,
    company_name: str | None = None,
    *,
    with_relations: bool = False,
    refine_text_relations: bool = False,
) -> ExtractResult:
    sections = split_sections(md_text, aliases)
    tables = extract_tables(md_text, aliases)
    attach_page_numbers(tables, build_table_page_map(middle_path))

    for table in tables:
        table.table_type_guess = guess_table_type(
            table.headers,
            table.rows,
            table.section_key,
            table.table_title,
        )

    facts = build_financial_facts(tables, report_year)
    entities = []
    relations = []
    if with_relations and company_name:
        entities, relations = build_relations(tables, sections, company_name, report_year)
        if refine_text_relations:
            entities, relations, _stats = refine_relations_from_text(
                sections, company_name, entities, relations
            )

    relation_candidates = [
        {
            "relation_type": rel.relation_type,
            "subject": rel.subject_name,
            "object": rel.object_name,
            "source": rel.source,
        }
        for rel in relations
    ]
    return ExtractResult(
        sections=sections,
        tables=tables,
        financial_facts=facts,
        entities=entities,
        relations=relations,
        relation_candidates=relation_candidates,
    )
