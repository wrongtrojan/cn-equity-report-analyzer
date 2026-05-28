"""Shared validation for rule-based and LLM relation extraction."""

from __future__ import annotations

from pipeline.extract.contracts import ExtractedRelation
from pipeline.extract.text.table_semantics import (
    is_accounting_term,
    is_role_label,
    is_summary_row,
    is_valid_share_ratio,
    looks_like_org_name,
    looks_like_person_name,
)


def validate_entity_name(name: str, entity_type: str) -> bool:
    text = str(name).strip()
    if not text or is_summary_row(text) or is_role_label(text) or is_accounting_term(text):
        return False
    if entity_type == "person":
        return looks_like_person_name(text)
    if entity_type in {"organization", "subsidiary", "company"}:
        return looks_like_org_name(text) or looks_like_person_name(text)
    return True


def validate_relation(rel: ExtractedRelation, *, table_type: str | None = None) -> bool:
    _ = table_type
    if not validate_entity_name(rel.subject_name, rel.subject_type):
        return False
    if rel.object_type != "company" and not validate_entity_name(rel.object_name, rel.object_type):
        return False
    if rel.relation_type in {"related_party_of", "transaction_with"}:
        if not looks_like_org_name(rel.subject_name):
            return False
    if rel.relation_type == "shareholder_of":
        if rel.subject_type == "person" and not (
            looks_like_person_name(rel.subject_name) or looks_like_org_name(rel.subject_name)
        ):
            return False
        ratio = str(rel.attrs.get("ratio", "")).strip()
        if not is_valid_share_ratio(ratio) and not rel.attrs.get("share_count"):
            return False
    if rel.relation_type == "actual_controller_of":
        if not looks_like_person_name(rel.subject_name):
            return False
    return True
