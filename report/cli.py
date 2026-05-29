"""Render relation graph and analysis HTML reports."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from report.core.router import render_report_mode

REPORT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = REPORT_DIR / "output"


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


def serve_report(host: str = "127.0.0.1", port: int = 8765, *, html_path: Path) -> None:
    """Serve rendered report; html_path is .../report_{id}/{mode}/index.html."""
    serve_dir = OUTPUT_DIR.resolve()
    page_dir = html_path.parent.resolve()
    try:
        url_path = page_dir.relative_to(serve_dir).as_posix()
    except ValueError:
        serve_dir = page_dir
        url_path = ""

    port = _pick_port(host, port)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(serve_dir), **kwargs)

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/{url_path}/" if url_path else f"http://{host}:{port}/"
    print(f"Serving {page_dir} at {url}")
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Render or serve HTML reports")
    parser.add_argument("--report-id", type=int, required=True)
    parser.add_argument("--mode", choices=["overview", "graph", "analysis", "all"], default="all")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--refresh-analysis",
        action="store_true",
        help="Run pipeline.analysis.cli.run before rendering analysis/all modes",
    )
    parser.add_argument(
        "--skip-qa-profile",
        action="store_true",
        help="Skip QA calls for overview company intro/business (use regex fallback)",
    )
    parser.add_argument(
        "--refresh-qa-profile",
        action="store_true",
        help="Re-run QA for overview intro/business instead of reading qa_profile_cache.json",
    )
    args = parser.parse_args()

    if args.refresh_analysis and args.mode in {"analysis", "all"}:
        cmd = [
            sys.executable,
            "-m",
            "pipeline.analysis.cli.mock_benchmark",
            "--report-id",
            str(args.report_id),
            "--seed",
            "42",
        ]
        subprocess.run(cmd, check=False)
        cmd = [sys.executable, "-m", "pipeline.analysis.cli.run", "--report-id", str(args.report_id), "--skip-llm"]
        subprocess.run(cmd, check=False)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else None
    try:
        html_path = render_report_mode(
            args.report_id,
            args.mode,
            output_dir=output_dir,
            skip_qa_profile=args.skip_qa_profile,
            refresh_qa_profile=args.refresh_qa_profile,
        )
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps({"status": "success", "mode": args.mode, "html_path": str(html_path)}, ensure_ascii=False))
    if args.serve:
        serve_path = html_path
        if args.mode == "all":
            serve_path = html_path.parent.parent / "overview" / "index.html"
        try:
            serve_report(host=args.host, port=args.port, html_path=serve_path)
        except OSError as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
