"""Render HTML reports."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPORT_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPORT_DIR / "templates"
OUTPUT_DIR = REPORT_DIR / "output"


def _escape_json_for_script(payload: dict) -> str:
    graph_json = json.dumps(payload, ensure_ascii=False)
    return (
        graph_json.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def render_html(
    template_name: str,
    *,
    report_id: int,
    mode: str,
    context: dict,
    output_dir: Path | None = None,
) -> Path:
    out_dir = output_dir or (OUTPUT_DIR / f"report_{report_id}" / mode)
    out_dir.mkdir(parents=True, exist_ok=True)

    static_src = REPORT_DIR / "static"
    static_dst = out_dir / "static"
    if static_dst.exists():
        shutil.rmtree(static_dst)
    shutil.copytree(static_src, static_dst)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=False,
    )
    if "graph_json" in context and isinstance(context["graph_json"], dict):
        context = {**context, "graph_json": _escape_json_for_script(context["graph_json"])}

    html = env.get_template(template_name).render(**context, report_id=report_id, mode=mode)
    html_path = out_dir / "index.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path
