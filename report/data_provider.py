"""Load knowledge-graph nodes/edges for report visualization."""

from __future__ import annotations

from pipeline.db import connect

ENTITY_COLORS = {
    "company": "#2563eb",
    "person": "#f59e0b",
    "organization": "#10b981",
    "subsidiary": "#ef4444",
}

RELATION_LABELS = {
    "shareholder_of": "股东",
    "actual_controller_of": "实控人",
    "executive_of": "高管",
    "director_of": "董事",
    "subsidiary_of": "子公司",
    "invest_in": "投资",
    "related_party_of": "关联方",
    "transaction_with": "关联交易",
}

RELATION_TAB_ORDER = list(RELATION_LABELS.keys())

VIEW_DESCRIPTIONS = {
    "shareholder_of": "展示主要股东及持股比例。",
    "actual_controller_of": "展示公司实际控制人。",
    "executive_of": "展示高级管理人员任职关系。",
    "director_of": "展示董事会成员任职关系。",
    "subsidiary_of": "展示控股子公司结构。",
    "invest_in": "展示母公司对子公司的投资关系。",
    "related_party_of": "展示关联方认定关系。",
    "transaction_with": "展示关联交易事项。",
}


def fetch_report_meta(report_id: int) -> dict:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.stock_name, c.stock_code, r.report_year, r.title
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
        "report_year": row[2],
        "title": row[3],
    }


def _build_node(entity_id: int, entity_key: str, name: str, entity_type: str, attrs: dict) -> dict:
    return {
        "id": entity_id,
        "label": name,
        "entity_key": entity_key,
        "entity_type": entity_type,
        "color": ENTITY_COLORS.get(entity_type, "#94a3b8"),
        "attrs": attrs or {},
    }


def _build_edge(
    relation_id: int,
    relation_type: str,
    from_id: int,
    to_id: int,
    subject_name: str,
    object_name: str,
    subject_type: str,
    object_type: str,
    attrs: dict,
    confidence: float,
    source: str,
    evidence: list[dict],
) -> dict:
    edge_label = RELATION_LABELS.get(relation_type, relation_type)
    title = attrs.get("title") if isinstance(attrs, dict) else None
    if title and relation_type in {"executive_of", "director_of"}:
        edge_label = title
    elif isinstance(attrs, dict) and attrs.get("transaction_content"):
        edge_label = str(attrs["transaction_content"])[:24]
    return {
        "id": relation_id,
        "from_id": from_id,
        "to_id": to_id,
        "subject_name": subject_name,
        "object_name": object_name,
        "label": edge_label,
        "relation_type": relation_type,
        "confidence": confidence,
        "source": source,
        "subject_type": subject_type,
        "object_type": object_type,
        "attrs": attrs or {},
        "evidence": evidence,
    }


def _merge_edge_labels(edges: list[dict]) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    for edge in edges:
        attrs = edge.get("attrs") or {}
        title = attrs.get("title")
        candidate = str(title or edge.get("label") or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        labels.append(candidate)
    if labels:
        return " · ".join(labels)
    return str(edges[0].get("label") or "")


def _merge_parallel_edges(edges: list[dict]) -> list[dict]:
    """Merge same (relation_type, from, to) edges for cleaner graph rendering."""
    merge_types = {"executive_of", "director_of", "actual_controller_of"}
    buckets: dict[tuple[str, int, int], list[dict]] = {}
    for edge in edges:
        relation_type = edge["relation_type"]
        if relation_type not in merge_types:
            continue
        key = (relation_type, edge["from_id"], edge["to_id"])
        buckets.setdefault(key, []).append(edge)

    merged_keys = {key for key, group in buckets.items() if len(group) > 1}
    if not merged_keys:
        return edges

    result: list[dict] = []
    emitted: set[tuple[str, int, int]] = set()
    for edge in edges:
        relation_type = edge["relation_type"]
        key = (relation_type, edge["from_id"], edge["to_id"])
        if relation_type not in merge_types or key not in merged_keys:
            result.append(edge)
            continue
        if key in emitted:
            continue
        emitted.add(key)
        group = buckets[key]
        primary = dict(group[0])
        primary["label"] = _merge_edge_labels(group)
        attrs = dict(primary.get("attrs") or {})
        titles = []
        for item in group:
            title = (item.get("attrs") or {}).get("title")
            if title and title not in titles:
                titles.append(str(title))
        if titles:
            attrs["title"] = " · ".join(titles)
        primary["attrs"] = attrs

        evidence: list[dict] = []
        seen_evidence: set[tuple] = set()
        for item in group:
            for ev in item.get("evidence") or []:
                signature = (ev.get("snippet"), ev.get("section_key"), ev.get("page_num"))
                if signature in seen_evidence:
                    continue
                seen_evidence.add(signature)
                evidence.append(ev)
        primary["evidence"] = evidence
        primary["merged_count"] = len(group)
        primary["merged_relation_ids"] = [item["id"] for item in group]
        result.append(primary)
    return result


def build_views(all_nodes: list[dict], all_edges: list[dict]) -> dict[str, dict]:
    node_by_id = {node["id"]: node for node in all_nodes}
    views: dict[str, dict] = {}

    for relation_type in RELATION_TAB_ORDER:
        typed_edges = _merge_parallel_edges(
            [edge for edge in all_edges if edge["relation_type"] == relation_type]
        )
        used_ids: set[int] = set()
        for edge in typed_edges:
            used_ids.add(edge["from_id"])
            used_ids.add(edge["to_id"])

        views[relation_type] = {
            "relation_type": relation_type,
            "label": RELATION_LABELS[relation_type],
            "description": VIEW_DESCRIPTIONS.get(relation_type, ""),
            "count": len(typed_edges),
            "empty": len(typed_edges) == 0,
            "nodes": [node_by_id[nid] for nid in sorted(used_ids) if nid in node_by_id],
            "edges": typed_edges,
        }
    return views


def fetch_graph_payload(report_id: int) -> dict:
    meta = fetch_report_meta(report_id)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, entity_key, name, entity_type, attrs
            FROM kg_entities
            WHERE report_id = %s
            ORDER BY id
            """,
            (report_id,),
        )
        entity_rows = cur.fetchall()

        cur.execute(
            """
            SELECT r.id, r.relation_type, r.attrs, r.confidence, r.source,
                   se.id AS subject_id, se.name AS subject_name, se.entity_type AS subject_type,
                   oe.id AS object_id, oe.name AS object_name, oe.entity_type AS object_type
            FROM kg_relations r
            JOIN kg_entities se ON se.id = r.subject_entity_id
            JOIN kg_entities oe ON oe.id = r.object_entity_id
            WHERE r.report_id = %s
            ORDER BY r.id
            """,
            (report_id,),
        )
        relation_rows = cur.fetchall()

        cur.execute(
            """
            SELECT e.relation_id, e.evidence_type, e.section_key, e.page_num,
                   e.snippet, e.attrs
            FROM kg_relation_evidence e
            JOIN kg_relations r ON r.id = e.relation_id
            WHERE r.report_id = %s
            ORDER BY e.id
            """,
            (report_id,),
        )
        evidence_rows = cur.fetchall()

    evidence_map: dict[int, list[dict]] = {}
    for relation_id, evidence_type, section_key, page_num, snippet, attrs in evidence_rows:
        evidence_map.setdefault(relation_id, []).append(
            {
                "evidence_type": evidence_type,
                "section_key": section_key,
                "page_num": page_num,
                "snippet": snippet,
                "attrs": attrs or {},
            }
        )

    all_nodes = [
        _build_node(entity_id, entity_key, name, entity_type, attrs)
        for entity_id, entity_key, name, entity_type, attrs in entity_rows
    ]

    all_edges = [
        _build_edge(
            relation_id,
            relation_type,
            subject_id,
            object_id,
            subject_name,
            object_name,
            subject_type,
            object_type,
            attrs,
            confidence,
            source,
            evidence_map.get(relation_id, []),
        )
        for (
            relation_id,
            relation_type,
            attrs,
            confidence,
            source,
            subject_id,
            subject_name,
            subject_type,
            object_id,
            object_name,
            object_type,
        ) in relation_rows
    ]

    views = build_views(all_nodes, all_edges)
    return {
        "meta": meta,
        "stats": {
            "entity_count": len(all_nodes),
            "relation_count": len(all_edges),
        },
        "views": views,
        "relation_labels": RELATION_LABELS,
    }


def fetch_relation_detail(report_id: int, relation_id: int) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.relation_type, r.attrs, r.confidence, r.source,
                   se.name, oe.name
            FROM kg_relations r
            JOIN kg_entities se ON se.id = r.subject_entity_id
            JOIN kg_entities oe ON oe.id = r.object_entity_id
            WHERE r.report_id = %s AND r.id = %s
            """,
            (report_id, relation_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            """
            SELECT evidence_type, section_key, page_num, snippet, attrs
            FROM kg_relation_evidence
            WHERE relation_id = %s
            ORDER BY id
            """,
            (relation_id,),
        )
        evidence = [
            {
                "evidence_type": e[0],
                "section_key": e[1],
                "page_num": e[2],
                "snippet": e[3],
                "attrs": e[4] or {},
            }
            for e in cur.fetchall()
        ]
    return {
        "relation_id": row[0],
        "relation_type": row[1],
        "attrs": row[2] or {},
        "confidence": row[3],
        "source": row[4],
        "subject": row[5],
        "object": row[6],
        "evidence": evidence,
    }
