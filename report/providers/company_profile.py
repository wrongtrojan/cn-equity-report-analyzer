"""Assemble company profile from DB sources (meta, KV, text, KG)."""

from __future__ import annotations

import re
from pathlib import Path

from pipeline.db import connect

from report.providers.meta import fetch_meta


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return None
    return match.group(1).strip().rstrip("。；;，,")


def _normalize_person_name(name: str | None) -> str | None:
    """Strip honorific suffixes so fields from different report sections match."""
    if not name:
        return name
    cleaned = name.strip()
    for suffix in ("先生", "女士", "博士", "教授"):
        if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
            return cleaned[: -len(suffix)]
    return cleaned

def _pick_intro_chunk(chunks: list[tuple[str, str]]) -> str | None:
    """Prefer profile-like chunks (地址/实控人/主营业务) over generic 本公司 mentions."""
    scored: list[tuple[int, str]] = []
    for _section, content in chunks:
        if "本公司" not in content and "主营业务" not in content:
            continue
        score = 0
        if "注册地址" in content:
            score += 5000
        if "控股股东" in content or "实际控制人" in content:
            score += 2000
        if "主营业务" in content:
            score += 3000
        if "公司致力于" in content:
            score += 1000
        if len(content) > 700:
            score -= 1500
        score += min(len(content), 400)
        scored.append((score, content))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _extract_from_text(text: str) -> dict[str, str | None]:
    registered = _first_match(text, r"注册地址为([^，。\n]+)")
    office = _first_match(text, r"经营地址为([^。\n]+)")
    controller = _first_match(text, r"控股股东[、，]?实际控制人为([^。\n]+)")
    main_business = _first_match(text, r"本公司主营业务有([^。\n]+)")
    if not main_business:
        main_business = _first_match(text, r"主营业务[：:]([^。\n]+)")

    intro = None
    mission = _first_match(text, r"(公司致力于[^。\n]+)")
    if mission:
        intro = mission
    elif main_business:
        intro = f"主营业务包括{main_business}等。"

    return {
        "registered_address": registered,
        "office_address": office,
        "controller": controller,
        "legal_representative": None,
        "main_business": main_business,
        "intro": intro[:200] if intro else None,
    }


def _split_business_tags(text: str | None) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[、，,；;]", text)
    tags = [p.strip().rstrip("等。") for p in parts if p.strip()]
    return [t for t in tags if t]


def _fetch_legal_representative(report_id: int, chunks: list[tuple[str, str]]) -> str | None:
    for _section, content in chunks:
        match = re.search(r"法定代表人[：:]\s*([^\s\n]+)", content)
        if match:
            return match.group(1).strip()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT content FROM text_chunks
            WHERE report_id = %s AND content ILIKE %s
            ORDER BY chunk_index
            LIMIT 20
            """,
            (report_id, "%法定代表人%"),
        )
        for (content,) in cur.fetchall():
            match = re.search(r"法定代表人[：:]\s*([^\s\n]+)", content or "")
            if match:
                return match.group(1).strip()
    return None


def _fetch_profile_kv(report_id: int) -> dict[str, str]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ff.item_name, ff.amount, ff.unit
            FROM financial_facts ff
            JOIN structured_tables st ON st.id = ff.table_id
            WHERE ff.report_id = %s AND st.table_type_guess = 'company_profile_kv'
            ORDER BY ff.id
            """,
            (report_id,),
        )
        rows = cur.fetchall()
    return {row[0]: f"{row[1]}{row[2] or ''}".strip() for row in rows}


def _fetch_text_chunks(report_id: int) -> list[tuple[str, str]]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT section_key, content
            FROM text_chunks
            WHERE report_id = %s
              AND section_key = ANY(%s)
              AND (content ILIKE %s OR content ILIKE %s)
            ORDER BY chunk_index
            """,
            (report_id, ["company_profile", "financial_statements", "mda"], "%本公司%", "%主营业务%"),
        )
        return [(row[0], row[1]) for row in cur.fetchall()]


def _fetch_subsidiaries(report_id: int, limit: int = 5) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (sub.name) sub.name, r.attrs->>'main_business' AS main_business
            FROM kg_relations r
            JOIN kg_entities sub ON sub.id = r.subject_entity_id
            JOIN kg_entities parent ON parent.id = r.object_entity_id
            WHERE r.report_id = %s
              AND r.relation_type = 'subsidiary_of'
              AND sub.entity_type = 'subsidiary'
            UNION
            SELECT DISTINCT ON (sub.name) sub.name, r.attrs->>'main_business' AS main_business
            FROM kg_relations r
            JOIN kg_entities parent ON parent.id = r.subject_entity_id
            JOIN kg_entities sub ON sub.id = r.object_entity_id
            WHERE r.report_id = %s
              AND r.relation_type = 'invest_in'
              AND sub.entity_type = 'subsidiary'
            LIMIT %s
            """,
            (report_id, report_id, limit),
        )
        rows = cur.fetchall()
    out: list[dict] = []
    seen: set[str] = set()
    for name, business in rows:
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "main_business": business or "—"})
    return out[:limit]


def _fetch_controller_from_kg(report_id: int) -> str | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT se.name
            FROM kg_relations r
            JOIN kg_entities se ON se.id = r.subject_entity_id
            WHERE r.report_id = %s AND r.relation_type = 'actual_controller_of'
            LIMIT 1
            """,
            (report_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def fetch_company_profile(
    report_id: int,
    *,
    skip_qa: bool = False,
    refresh_qa: bool = False,
    output_dir: Path | None = None,
) -> dict:
    meta = fetch_meta(report_id)
    kv = _fetch_profile_kv(report_id)
    chunks = _fetch_text_chunks(report_id)
    intro_text = _pick_intro_chunk(chunks)
    extracted = _extract_from_text(intro_text) if intro_text else {}

    intro = extracted.get("intro")
    main_business = extracted.get("main_business")
    main_business_tags = _split_business_tags(main_business)
    profile_source = "regex"

    if not skip_qa:
        from report.providers.qa_profile import fetch_qa_profile

        qa = fetch_qa_profile(report_id, force=refresh_qa, output_dir=output_dir)
        if qa.get("intro"):
            intro = qa["intro"]
        if qa.get("main_business"):
            main_business = qa["main_business"]
        if qa.get("main_business_tags"):
            main_business_tags = qa["main_business_tags"]
        if qa.get("profile_source") == "qa":
            profile_source = "qa"

    controller = _normalize_person_name(extracted.get("controller") or _fetch_controller_from_kg(report_id))
    legal_rep = _normalize_person_name(
        kv.get("法定代表人")
        or extracted.get("legal_representative")
        or _fetch_legal_representative(report_id, chunks)
    )
    subsidiaries = _fetch_subsidiaries(report_id)

    profile = {
        "meta": meta,
        "registered_address": kv.get("注册地址") or extracted.get("registered_address"),
        "office_address": kv.get("办公地址") or kv.get("经营地址") or extracted.get("office_address"),
        "controller": controller,
        "legal_representative": legal_rep,
        "main_business": main_business,
        "main_business_tags": main_business_tags,
        "intro": intro,
        "profile_source": profile_source,
        "subsidiaries": subsidiaries,
        "subsidiary_count": len(subsidiaries),
    }

    from report.providers.profile_text import enrich_profile_narrative

    return enrich_profile_narrative(profile)
