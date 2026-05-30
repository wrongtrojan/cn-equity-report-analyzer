"""Rule-based relation extraction from classified tables."""

from __future__ import annotations

import re

from pipeline.extract.contracts import (
    ExtractedEntity,
    ExtractedRelation,
    ParsedTable,
    RelationEvidence,
    Section,
)
from pipeline.extract.text.table_semantics import (
    is_summary_row,
    is_valid_share_ratio,
    iter_data_rows,
    iter_roster_records,
    looks_like_org_name,
    looks_like_person_name,
    resolve_column_map,
)
from pipeline.extract.relations.relation_validate import validate_relation

EXECUTIVE_TITLES = ("董事长", "总经理", "副总经理", "财务总监", "董事会秘书", "总裁", "首席执行官")
DIRECTOR_TITLES = ("董事", "独立董事", "副董事长")

EXTRACTOR_BY_TYPE = {}


def normalize_entity_key(name: str) -> str:
    text = re.sub(r"\s+", "", name.strip())
    return text.lower()


def _entity(
    registry: dict[str, ExtractedEntity],
    name: str,
    entity_type: str,
    **attrs,
) -> ExtractedEntity:
    key = normalize_entity_key(name)
    if key not in registry:
        registry[key] = ExtractedEntity(entity_key=key, name=name.strip(), entity_type=entity_type, attrs=dict(attrs))
    else:
        registry[key].attrs.update({k: v for k, v in attrs.items() if v})
    return registry[key]


def _relation_key(
    relation_type: str,
    subject_key: str,
    object_key: str,
    table_seq: int,
    extra: str = "",
) -> str:
    base = f"{relation_type}|{subject_key}|{object_key}|{table_seq}"
    if extra:
        return f"{base}|{extra}"
    return base


def semantic_relation_key(relation_type: str, subject_key: str, object_key: str) -> str:
    """Identity of a relation edge regardless of source/table_seq."""
    return f"{relation_type}|{subject_key}|{object_key}"


def _relation_quality_rank(rel: ExtractedRelation) -> tuple:
    table_evidence = sum(1 for item in rel.evidence if item.evidence_type == "table_row")
    return (
        1 if rel.source == "rule" else 0,
        rel.confidence,
        len(rel.attrs or {}),
        table_evidence,
    )


def prefer_relation(candidate: ExtractedRelation, existing: ExtractedRelation) -> bool:
    """True if candidate should replace existing for the same semantic edge."""
    return _relation_quality_rank(candidate) > _relation_quality_rank(existing)


def _add_relation(
    relations: dict[str, ExtractedRelation],
    rel: ExtractedRelation,
    *,
    table_type: str | None,
) -> None:
    if validate_relation(rel, table_type=table_type):
        relations[rel.source_key] = rel


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return str(row[idx]).strip()


def _classify_role(title: str) -> str:
    if any(token in title for token in EXECUTIVE_TITLES):
        return "executive_of"
    if any(token in title for token in DIRECTOR_TITLES):
        return "director_of"
    if "监事" in title:
        return "executive_of"
    return "executive_of"


def extract_shareholders_top10(
    table: ParsedTable,
    company: ExtractedEntity,
    registry: dict[str, ExtractedEntity],
    relations: dict[str, ExtractedRelation],
) -> None:
    col_map = resolve_column_map(
        table.headers,
        table.rows,
        {
            "name": ("股东名称", "股东姓名"),
            "ratio": ("持股比例",),
            "shares": ("报告期末持股数量", "持股数量"),
            "nature": ("股东性质",),
        },
    )
    name_idx = col_map.get("name")
    if name_idx is None:
        return

    for row in iter_data_rows(table.headers, table.rows, col_map):
        name = _cell(row, name_idx)
        if is_summary_row(name) or not (looks_like_person_name(name) or looks_like_org_name(name)):
            continue
        nature = _cell(row, col_map.get("nature"))
        entity_type = "person" if "自然人" in nature else "organization"
        ratio = _cell(row, col_map.get("ratio"))
        shares = _cell(row, col_map.get("shares"))
        if not is_valid_share_ratio(ratio):
            continue
        if not ratio and not shares:
            continue

        subject = _entity(registry, name, entity_type, shareholder_nature=nature or None)
        attrs = {}
        if ratio:
            attrs["ratio"] = ratio
        if shares:
            attrs["share_count"] = shares
        if nature:
            attrs["shareholder_nature"] = nature

        source_key = _relation_key("shareholder_of", subject.entity_key, company.entity_key, table.table_seq)
        snippet = " | ".join(x for x in [name, ratio, shares, nature] if x)
        _add_relation(
            relations,
            ExtractedRelation(
                relation_type="shareholder_of",
                subject_key=subject.entity_key,
                subject_name=subject.name,
                subject_type=subject.entity_type,
                object_key=company.entity_key,
                object_name=company.name,
                object_type=company.entity_type,
                attrs=attrs,
                source_key=source_key,
                evidence=[
                    RelationEvidence(
                        evidence_type="table_row",
                        section_key=table.section_key,
                        page_num=table.page_num,
                        table_seq=table.table_seq,
                        snippet=snippet,
                        attrs={"table_title": table.table_title},
                    )
                ],
            ),
            table_type=table.table_type_guess,
        )


def _normalize_executive_title(text: str) -> str | None:
    raw = str(text).strip()
    if not raw:
        return None
    for title in EXECUTIVE_TITLES + DIRECTOR_TITLES:
        if title in raw:
            return title
    if "监事" in raw:
        return "监事"
    return None


def extract_controller(
    table: ParsedTable,
    company: ExtractedEntity,
    registry: dict[str, ExtractedEntity],
    relations: dict[str, ExtractedRelation],
) -> None:
    col_map = resolve_column_map(
        table.headers,
        table.rows,
        {
            "name": ("控股股东姓名", "实际控制人姓名", "姓名"),
            "occupation": ("主要职业及职务", "职务", "担任的职务"),
        },
    )
    name_idx = col_map.get("name")
    occupation_idx = col_map.get("occupation")

    for row in iter_data_rows(table.headers, table.rows, col_map):
        name = _cell(row, name_idx) if name_idx is not None else _cell(row, 0)
        if not name or name in {"姓名", "控股股东姓名", "实际控制人姓名"}:
            continue
        if not looks_like_person_name(name):
            continue

        subject = _entity(registry, name, "person")
        occupation = _cell(row, occupation_idx)
        source_key = _relation_key("actual_controller_of", subject.entity_key, company.entity_key, table.table_seq)
        _add_relation(
            relations,
            ExtractedRelation(
                relation_type="actual_controller_of",
                subject_key=subject.entity_key,
                subject_name=subject.name,
                subject_type=subject.entity_type,
                object_key=company.entity_key,
                object_name=company.name,
                object_type=company.entity_type,
                source_key=source_key,
                evidence=[
                    RelationEvidence(
                        evidence_type="table_row",
                        section_key=table.section_key,
                        page_num=table.page_num,
                        table_seq=table.table_seq,
                        snippet=" | ".join(x for x in [name, occupation] if x),
                        attrs={"table_title": table.table_title},
                    )
                ],
            ),
            table_type=table.table_type_guess,
        )

        normalized_title = _normalize_executive_title(occupation) if occupation else None
        if normalized_title:
            exec_source_key = _relation_key(
                "executive_of",
                subject.entity_key,
                company.entity_key,
                table.table_seq,
                normalized_title,
            )
            _add_relation(
                relations,
                ExtractedRelation(
                    relation_type="executive_of",
                    subject_key=subject.entity_key,
                    subject_name=subject.name,
                    subject_type=subject.entity_type,
                    object_key=company.entity_key,
                    object_name=company.name,
                    object_type=company.entity_type,
                    attrs={"title": normalized_title, "source": "controller_info"},
                    source_key=exec_source_key,
                    evidence=[
                        RelationEvidence(
                            evidence_type="table_row",
                            section_key=table.section_key,
                            page_num=table.page_num,
                            table_seq=table.table_seq,
                            snippet=f"{name} | {occupation}",
                            attrs={"table_title": table.table_title},
                        )
                    ],
                ),
                table_type=table.table_type_guess,
            )
        break


def extract_directors_roster(
    table: ParsedTable,
    company: ExtractedEntity,
    registry: dict[str, ExtractedEntity],
    relations: dict[str, ExtractedRelation],
) -> None:
    col_map = resolve_column_map(
        table.headers,
        table.rows,
        {
            "name": ("姓名",),
            "title": ("职务", "担任的职务"),
            "status": ("任职状态",),
            "gender": ("性别",),
        },
    )
    if col_map.get("name") is None or col_map.get("title") is None:
        return

    for record in iter_roster_records(table.headers, table.rows, col_map):
        if not record.titles:
            continue

        subject = _entity(registry, record.name, "person", title=record.titles[0])
        combined_title = "、".join(record.titles)
        shared_attrs: dict[str, str] = {}
        if record.status:
            shared_attrs["status"] = record.status

        for title in record.titles:
            relation_type = _classify_role(title)
            attrs = {"title": title, **shared_attrs}
            source_key = _relation_key(
                relation_type,
                subject.entity_key,
                company.entity_key,
                table.table_seq,
                title,
            )
            _add_relation(
                relations,
                ExtractedRelation(
                    relation_type=relation_type,
                    subject_key=subject.entity_key,
                    subject_name=subject.name,
                    subject_type=subject.entity_type,
                    object_key=company.entity_key,
                    object_name=company.name,
                    object_type=company.entity_type,
                    attrs=attrs,
                    source_key=source_key,
                    evidence=[
                        RelationEvidence(
                            evidence_type="table_row",
                            section_key=table.section_key,
                            page_num=table.page_num,
                            table_seq=table.table_seq,
                            snippet=f"{record.name} | {combined_title}",
                            attrs={"table_title": table.table_title},
                        )
                    ],
                ),
                table_type=table.table_type_guess,
            )


def extract_subsidiaries(
    table: ParsedTable,
    company: ExtractedEntity,
    registry: dict[str, ExtractedEntity],
    relations: dict[str, ExtractedRelation],
) -> None:
    col_map = resolve_column_map(
        table.headers,
        table.rows,
        {
            "name": ("公司名称", "子公司名称", "企业名称"),
            "type": ("公司类型", "子公司类型"),
            "business": ("主要业务", "经营范围"),
            "capital": ("注册资本",),
        },
    )
    name_idx = col_map.get("name")
    if name_idx is None:
        return

    for row in iter_data_rows(table.headers, table.rows, col_map):
        name = _cell(row, name_idx)
        if is_summary_row(name) or not looks_like_org_name(name):
            continue

        company_type = _cell(row, col_map.get("type"))
        subject = _entity(registry, name, "subsidiary", company_type=company_type or None)
        attrs = {}
        if company_type:
            attrs["company_type"] = company_type
        business = _cell(row, col_map.get("business"))
        if business:
            attrs["main_business"] = business
        capital = _cell(row, col_map.get("capital"))
        if capital:
            attrs["registered_capital"] = capital

        for relation_type, subj, obj in (
            ("subsidiary_of", subject, company),
            ("invest_in", company, subject),
        ):
            source_key = _relation_key(relation_type, subj.entity_key, obj.entity_key, table.table_seq)
            _add_relation(
                relations,
                ExtractedRelation(
                    relation_type=relation_type,
                    subject_key=subj.entity_key,
                    subject_name=subj.name,
                    subject_type=subj.entity_type,
                    object_key=obj.entity_key,
                    object_name=obj.name,
                    object_type=obj.entity_type,
                    attrs=dict(attrs),
                    source_key=source_key,
                    evidence=[
                        RelationEvidence(
                            evidence_type="table_row",
                            section_key=table.section_key,
                            page_num=table.page_num,
                            table_seq=table.table_seq,
                            snippet=f"{name} | {company_type or ''}".strip(" |"),
                            attrs={"table_title": table.table_title},
                        )
                    ],
                ),
                table_type=table.table_type_guess,
            )


def extract_related_transactions(
    table: ParsedTable,
    company: ExtractedEntity,
    registry: dict[str, ExtractedEntity],
    relations: dict[str, ExtractedRelation],
) -> None:
    col_map = resolve_column_map(
        table.headers,
        table.rows,
        {
            "party": ("关联方",),
            "content": ("关联交易内容", "交易内容"),
            "current": ("本期发生额", "本期金额", "支付的租金"),
            "prior": ("上期发生额", "上期金额"),
        },
    )
    party_idx = col_map.get("party")
    if party_idx is None:
        return

    for row in iter_data_rows(table.headers, table.rows, col_map):
        party = _cell(row, party_idx)
        if is_summary_row(party) or not looks_like_org_name(party):
            continue

        subject = _entity(registry, party, "organization")
        content = _cell(row, col_map.get("content"))
        attrs = {
            "transaction_content": content or None,
            "amount_current": _cell(row, col_map.get("current")) or None,
            "amount_prior": _cell(row, col_map.get("prior")) or None,
        }
        attrs = {k: v for k, v in attrs.items() if v}

        source_key = _relation_key(
            "transaction_with",
            subject.entity_key,
            company.entity_key,
            table.table_seq,
            content,
        )
        _add_relation(
            relations,
            ExtractedRelation(
                relation_type="transaction_with",
                subject_key=subject.entity_key,
                subject_name=subject.name,
                subject_type=subject.entity_type,
                object_key=company.entity_key,
                object_name=company.name,
                object_type=company.entity_type,
                attrs=dict(attrs),
                source_key=source_key,
                evidence=[
                    RelationEvidence(
                        evidence_type="table_row",
                        section_key=table.section_key,
                        page_num=table.page_num,
                        table_seq=table.table_seq,
                        snippet=" | ".join(x for x in [party, content] if x),
                        attrs={"table_title": table.table_title},
                    )
                ],
            ),
            table_type=table.table_type_guess,
        )


def extract_related_party_list(
    table: ParsedTable,
    company: ExtractedEntity,
    registry: dict[str, ExtractedEntity],
    relations: dict[str, ExtractedRelation],
) -> None:
    col_map = resolve_column_map(
        table.headers,
        table.rows,
        {
            "party": ("关联方名称", "其他关联方名称", "合营或联营企业名称"),
        },
    )
    party_idx = col_map.get("party")
    if party_idx is None:
        return

    for row in iter_data_rows(table.headers, table.rows, col_map):
        party = _cell(row, party_idx)
        if is_summary_row(party) or not looks_like_org_name(party):
            continue

        subject = _entity(registry, party, "organization")
        source_key = _relation_key("related_party_of", subject.entity_key, company.entity_key, table.table_seq)
        _add_relation(
            relations,
            ExtractedRelation(
                relation_type="related_party_of",
                subject_key=subject.entity_key,
                subject_name=subject.name,
                subject_type=subject.entity_type,
                object_key=company.entity_key,
                object_name=company.name,
                object_type=company.entity_type,
                source_key=source_key,
                evidence=[
                    RelationEvidence(
                        evidence_type="table_row",
                        section_key=table.section_key,
                        page_num=table.page_num,
                        table_seq=table.table_seq,
                        snippet=party,
                        attrs={"table_title": table.table_title},
                    )
                ],
            ),
            table_type=table.table_type_guess,
        )


EXTRACTOR_BY_TYPE.update(
    {
        "top10_shareholders": extract_shareholders_top10,
        "controller_info": extract_controller,
        "director_roster": extract_directors_roster,
        "subsidiaries": extract_subsidiaries,
        "related_party_transactions": extract_related_transactions,
        "related_party_list": extract_related_party_list,
    }
)


def build_relations(
    tables: list[ParsedTable],
    sections: list[Section],
    company_name: str,
    report_year: int | None = None,
) -> tuple[list[ExtractedEntity], list[ExtractedRelation]]:
    _ = (sections, report_year)
    registry: dict[str, ExtractedEntity] = {}
    relations: dict[str, ExtractedRelation] = {}
    company = _entity(registry, company_name, "company")

    for table in tables:
        extractor = EXTRACTOR_BY_TYPE.get(table.table_type_guess or "")
        if extractor is None:
            continue
        extractor(table, company, registry, relations)

    return list(registry.values()), list(relations.values())
