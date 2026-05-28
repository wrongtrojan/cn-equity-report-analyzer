"""Render relation graph HTML report."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .data_provider import fetch_graph_payload

REPORT_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = REPORT_DIR / "templates"
OUTPUT_DIR = REPORT_DIR / "output"


def render_report(report_id: int, output_dir: Path | None = None) -> Path:
    payload = fetch_graph_payload(report_id)
    if payload["stats"]["entity_count"] == 0:
        raise RuntimeError(f"report_id={report_id} has no kg_entities; run ingest with --with-relations first")

    out_dir = output_dir or (OUTPUT_DIR / f"report_{report_id}")
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
    template = env.get_template("report.html.j2")
    meta = payload["meta"]
    graph_json = json.dumps(payload, ensure_ascii=False)
    # Avoid breaking <script type="application/json"> by escaping HTML-significant chars.
    graph_json = (
        graph_json.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

    html = template.render(
        title=f"{meta['company_name']} · 关系图谱",
        meta=meta,
        stats=payload["stats"],
        graph_json=graph_json,
    )
    html_path = out_dir / "index.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path


def _pick_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise OSError(f"no free port found near {preferred}")


def serve_report(
    report_id: int,
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    root: Path | None = None,
) -> None:
    html_path = root / "index.html" if root else render_report(report_id)
    root = root or html_path.parent
    port = _pick_port(host, port)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving {html_path} at http://{host}:{port}/")
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Render or serve relation graph report")
    parser.add_argument("--report-id", type=int, required=True)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--serve", action="store_true", help="Render then start local HTTP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve() if args.output_dir else None
    try:
        html_path = render_report(args.report_id, output_dir=output_dir)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps({"status": "success", "html_path": str(html_path)}, ensure_ascii=False))
    if args.serve:
        try:
            serve_report(args.report_id, host=args.host, port=args.port, root=html_path.parent)
        except OSError as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
