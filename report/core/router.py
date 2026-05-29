"""Route report modes to providers and templates."""

from __future__ import annotations

from pathlib import Path

from report.core.render import OUTPUT_DIR, render_html
from report.providers.analysis import fetch_analysis_payload
from report.providers.graph import fetch_graph_payload
from report.providers.overview import fetch_overview_payload
from report.providers.qa_profile import resolve_report_root


def render_report_mode(
    report_id: int,
    mode: str,
    output_dir: Path | None = None,
    *,
    skip_qa_profile: bool = False,
    refresh_qa_profile: bool = False,
) -> Path:
    if mode == "all":
        render_report_mode(
            report_id,
            "overview",
            output_dir=output_dir,
            skip_qa_profile=skip_qa_profile,
            refresh_qa_profile=refresh_qa_profile,
        )
        render_report_mode(report_id, "graph", output_dir=output_dir, skip_qa_profile=skip_qa_profile)
        return render_report_mode(report_id, "analysis", output_dir=output_dir, skip_qa_profile=skip_qa_profile)

    if mode == "overview":
        overview_dir = output_dir or (OUTPUT_DIR / f"report_{report_id}" / "overview")
        report_root = resolve_report_root(report_id, overview_dir)
        payload = fetch_overview_payload(
            report_id,
            skip_qa=skip_qa_profile,
            refresh_qa=refresh_qa_profile,
            output_dir=report_root,
        )
        meta = payload["meta"]
        return render_html(
            "overview.html.j2",
            report_id=report_id,
            mode=mode,
            context={
                "title": f"{meta['company_name']} · 基本信息",
                "meta": meta,
                "payload": payload,
            },
            output_dir=output_dir,
        )

    if mode == "graph":
        payload = fetch_graph_payload(report_id)
        if payload["stats"]["entity_count"] == 0:
            raise RuntimeError(f"report_id={report_id} has no kg_entities; run ingest with --with-relations first")
        meta = payload["meta"]
        return render_html(
            "graph.html.j2",
            report_id=report_id,
            mode=mode,
            context={
                "title": f"{meta['company_name']} · 关系图谱",
                "meta": meta,
                "stats": payload["stats"],
                "graph_json": payload,
            },
            output_dir=output_dir,
        )

    if mode == "analysis":
        payload = fetch_analysis_payload(report_id)
        meta = payload.get("meta") or {"report_id": report_id}
        title_name = meta.get("company_name") or f"report #{report_id}"
        return render_html(
            "analysis.html.j2",
            report_id=report_id,
            mode=mode,
            context={
                "title": f"{title_name} · 经营状况",
                "meta": meta,
                "payload": payload,
            },
            output_dir=output_dir,
        )

    raise ValueError(f"unknown mode: {mode}")
