from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import unicodedata
from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterable

from .config import QA_LLM_MODEL
from .pipeline import QAPipeline, ReportSummary

if TYPE_CHECKING:
    from .pipeline import QASession, Turn
    from .schemas import QAResponse

_INTENT_LABELS = {
    "numeric": "数值查询",
    "narrative": "叙述解读",
    "relational": "关系查询",
    "hybrid": "混合检索",
}


class _Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def wrap(self, code: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, text: str) -> str:
        return self.wrap("1", text)

    def dim(self, text: str) -> str:
        return self.wrap("2", text)

    def cyan(self, text: str) -> str:
        return self.wrap("36", text)

    def green(self, text: str) -> str:
        return self.wrap("32", text)

    def yellow(self, text: str) -> str:
        return self.wrap("33", text)

    def magenta(self, text: str) -> str:
        return self.wrap("35", text)

    def blue(self, text: str) -> str:
        return self.wrap("34", text)


def _use_color(no_color: bool) -> bool:
    if no_color or os.getenv("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _term_width(default: int = 72) -> int:
    try:
        return max(48, min(shutil.get_terminal_size().columns, 100))
    except OSError:
        return default


def _char_display_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in {"F", "W"}:
        return 2
    return 1


def _display_width(text: str) -> int:
    return sum(_char_display_width(ch) for ch in text)


def _truncate_display(text: str, width: int) -> str:
    if width <= 0:
        return ""
    out: list[str] = []
    used = 0
    for ch in text:
        ch_w = _char_display_width(ch)
        if used + ch_w > width:
            break
        out.append(ch)
        used += ch_w
    return "".join(out)


def _pad_display(text: str, width: int, align: str = "left") -> str:
    text_w = _display_width(text)
    if text_w > width:
        return _truncate_display(text, width)
    pad = width - text_w
    if align == "center":
        left = pad // 2
        return (" " * left) + text + (" " * (pad - left))
    if align == "right":
        return (" " * pad) + text
    return text + (" " * pad)


def _wrap_display(text: str, max_width: int) -> list[str]:
    if max_width <= 0:
        return [text]
    lines: list[str] = []
    current: list[str] = []
    current_w = 0
    for ch in text:
        ch_w = _char_display_width(ch)
        if ch == "\n":
            lines.append("".join(current))
            current = []
            current_w = 0
            continue
        if current and current_w + ch_w > max_width:
            lines.append("".join(current))
            current = [ch]
            current_w = ch_w
        else:
            current.append(ch)
            current_w += ch_w
    if current:
        lines.append("".join(current))
    return lines or [""]


def _box_top_title(title: str, box_width: int) -> str:
    inner = box_width - 2
    head = f"─ {title} "
    dashes = max(0, inner - _display_width(head))
    return "┌" + head + ("─" * dashes) + "┐"


def _box_row(text: str, box_width: int, align: str = "left") -> str:
    inner = box_width - 2
    return "│" + _pad_display(text, inner, align) + "│"


def _box_bottom(box_width: int) -> str:
    return "└" + ("─" * (box_width - 2)) + "┘"


def _box_line(text: str, width: int, style: _Style) -> str:
    return _box_row(text, width)


def _print_box(title: str, lines: Iterable[str], style: _Style, width: int) -> None:
    print(style.dim(_box_top_title(title, width)))
    for line in lines:
        print(style.dim(_box_line(line, width, style)))
    print(style.dim(_box_bottom(width)))


def print_banner(session: QASession, model: str, *, no_color: bool = False) -> None:
    style = _Style(_use_color(no_color))
    width = _term_width()
    year = f"{session.report_year} 年报" if session.report_year else "未知年份"
    rows = [
        ("公司", session.company_name),
        ("报告", f"{year}  (#{session.report_id})"),
        ("模型", model),
    ]
    print()
    print(style.bold(style.cyan("┌" + ("─" * (width - 2)) + "┐")))
    print(style.bold(style.cyan(_box_row("财报问答 · Hybrid QA", width, "center"))))
    print(style.bold(style.cyan("├" + ("─" * (width - 2)) + "┤")))
    for label, value in rows:
        line = _pad_display(f" {label}", 6) + value
        print(style.bold(style.cyan(_box_row(line, width))))
    print(style.bold(style.cyan(_box_bottom(width))))
    print()
    print(style.dim("  命令"))
    print(f"  {style.cyan('/report [id]')}  切换报告    {style.cyan('/history')}  查看历史")
    print(f"  {style.cyan('/clear')}        清空上下文   {style.cyan('/help')}     显示帮助")
    print(f"  {style.cyan('/exit')}         退出")
    print(style.dim("─" * width))


def print_help(*, no_color: bool = False) -> None:
    style = _Style(_use_color(no_color))
    lines = [
        "直接输入问题即可开始问答，例如：",
        "  · 2025年的营业总收入是多少？",
        "  · 请介绍一下公司的主要业务",
        "  · 前十大股东有哪些？",
        "",
        "系统会先标准化问题，再按意图检索表格/向量证据，最后生成回答。",
        "引用来源来自检索到的证据，不是模型自行编造。",
    ]
    _print_box("帮助", lines, style, _term_width())


def _wrap_answer(text: str, width: int) -> list[str]:
    paragraphs = (text.strip() or "（无回答）").split("\n\n")
    lines: list[str] = []
    for i, paragraph in enumerate(paragraphs):
        chunk = paragraph.strip()
        if not chunk:
            continue
        if i > 0 and lines:
            lines.append("")
        lines.extend(_wrap_display(chunk, width))
    return lines or ["（无回答）"]


def print_response(resp: QAResponse, *, elapsed_sec: float | None = None, no_color: bool = False) -> None:
    style = _Style(_use_color(no_color))
    width = _term_width()
    intent = _INTENT_LABELS.get(resp.normalized.intent, resp.normalized.intent)
    evidence_count = len(resp.evidence)

    wrapped = _wrap_answer(resp.answer, width=width - 4)
    _print_box("回答", wrapped, style, width)

    citation_lines: list[str]
    if resp.citations:
        citation_lines = [f"{i}. {c}" for i, c in enumerate(resp.citations, start=1)]
    else:
        citation_lines = ["暂无引用（未检索到可用证据）"]

    meta = f"引用来源 ({len(resp.citations)}) · {intent}"
    _print_box(meta, citation_lines, style, width)

    if elapsed_sec is not None:
        footer = f"证据 {evidence_count} 条 · 耗时 {elapsed_sec:.1f}s"
        print(style.dim(f"  {footer}"))
    print()


def print_history(turns: list[Turn], *, no_color: bool = False) -> None:
    style = _Style(_use_color(no_color))
    width = _term_width()
    if not turns:
        print(style.yellow("  暂无对话历史。"))
        return

    print(style.dim(f"  共 {len(turns)} 轮对话"))
    print(style.dim("─" * width))
    for i, turn in enumerate(turns, start=1):
        intent = _INTENT_LABELS.get(turn.normalized.intent, turn.normalized.intent)
        print(style.bold(f"  #{i}  {style.cyan(turn.question)}"))
        print(style.dim(f"      意图: {intent}"))
        preview = turn.answer.replace("\n", " ")
        if _display_width(preview) > width - 8:
            preview = _truncate_display(preview, width - 11) + "..."
        print(f"      {preview}")
        if turn.citations:
            cites = " · ".join(turn.citations[:3])
            if len(turn.citations) > 3:
                cites += f" · +{len(turn.citations) - 3}"
            print(style.dim(f"      引用: {cites}"))
        print()


def print_report_list(
    reports: list[ReportSummary],
    current_report_id: int | None = None,
    *,
    no_color: bool = False,
) -> None:
    style = _Style(_use_color(no_color))
    width = _term_width()

    if not reports:
        print_warn("数据库中暂无可用报告。", no_color=no_color)
        print(style.dim("  请先运行 ingest 入库。"))
        return

    print(style.dim(f"  共 {len(reports)} 份报告"))
    print(style.dim("─" * width))
    for report in reports:
        marker = " ← 当前" if report.report_id == current_report_id else ""
        year_label = f"{report.report_year} {report.report_type}"
        name = _truncate_display(report.stock_name, width - 28)
        line = (
            f"  #{report.report_id:<3} {report.stock_code}  "
            f"{name}  {year_label}  {report.parse_status}{marker}"
        )
        if report.report_id == current_report_id:
            print(style.bold(style.cyan(line)))
        else:
            print(line)
    print(style.dim("─" * width))
    print(style.dim("  切换报告: /report <id>"))


def print_info(message: str, *, no_color: bool = False) -> None:
    style = _Style(_use_color(no_color))
    print(style.green(f"  ✓ {message}"))


def print_warn(message: str, *, no_color: bool = False) -> None:
    style = _Style(_use_color(no_color))
    print(style.yellow(f"  ! {message}"))


def print_error(message: str, *, no_color: bool = False) -> None:
    style = _Style(_use_color(no_color))
    print(style.wrap("31", f"  ✗ {message}"))


def prompt_text(*, no_color: bool = False) -> str:
    style = _Style(_use_color(no_color))
    label = style.bold(style.green("qa")) + style.dim(" › ")
    return label


@contextmanager
def thinking(*, no_color: bool = False):
    style = _Style(_use_color(no_color))
    if not sys.stdout.isatty():
        yield
        return
    msg = style.dim("  ⏳ 正在检索证据并生成回答...")
    print(msg, end="", flush=True)
    try:
        yield
    finally:
        print("\r\033[K", end="", flush=True)


def read_input(*, no_color: bool = False) -> str:
    try:
        return input(f"\n{prompt_text(no_color=no_color)}").strip()
    except EOFError:
        raise KeyboardInterrupt from None

def run_repl(report_id: int, *, no_color: bool = False) -> int:
    qa = QAPipeline()
    session = qa.load_session(report_id)
    print_banner(session, QA_LLM_MODEL, no_color=no_color)

    while True:
        try:
            user_input = read_input(no_color=no_color)
        except KeyboardInterrupt:
            print("\n  再见。")
            return 0

        if not user_input:
            continue
        if user_input in {"/exit", "/quit", "/q"}:
            print("  再见。")
            return 0
        if user_input == "/help":
            print_help(no_color=no_color)
            continue
        if user_input == "/history":
            print_history(session.turns, no_color=no_color)
            continue
        if user_input == "/clear":
            session.clear()
            print_info("已清空会话上下文。", no_color=no_color)
            continue
        if user_input == "/report" or user_input.startswith("/report "):
            parts = user_input.split(maxsplit=1)
            if len(parts) == 1 or not parts[1].strip():
                print_report_list(
                    qa.list_reports(),
                    session.report_id,
                    no_color=no_color,
                )
                continue
            try:
                rid = int(parts[1].strip())
            except ValueError:
                print_warn("用法: /report [id]", no_color=no_color)
                continue
            try:
                session = qa.load_session(rid)
            except ValueError as exc:
                print_error(str(exc), no_color=no_color)
                continue
            print_info(
                f"已切换至 {session.company_name}（{session.report_year} 年报, #{session.report_id}）",
                no_color=no_color,
            )
            continue

        started = time.perf_counter()
        try:
            with thinking(no_color=no_color):
                response = qa.ask(session, user_input)
        except Exception as exc:
            print_error(f"问答失败: {exc}", no_color=no_color)
            continue

        elapsed = time.perf_counter() - started
        print_response(response, elapsed_sec=elapsed, no_color=no_color)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hybrid QA CLI")
    parser.add_argument("--report-id", type=int, required=True, help="目标报告 ID")
    parser.add_argument("--query", type=str, default=None, help="单次问答")
    parser.add_argument("--json", action="store_true", help="单次问答时输出 JSON")
    parser.add_argument("--no-color", action="store_true", help="禁用终端颜色")
    args = parser.parse_args()

    qa = QAPipeline()
    if args.query:
        session = qa.load_session(args.report_id)
        started = time.perf_counter()
        try:
            resp = qa.ask(session, args.query)
        except Exception as exc:
            print_error(f"问答失败: {exc}", no_color=args.no_color)
            return 1
        elapsed = time.perf_counter() - started

        if args.json:
            print(
                json.dumps(
                    {
                        "answer": resp.answer,
                        "citations": resp.citations,
                        "normalized": resp.normalized.model_dump(),
                        "evidence": [x.model_dump() for x in resp.evidence],
                        "elapsed_sec": round(elapsed, 3),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print_banner(session, QA_LLM_MODEL, no_color=args.no_color)
            print_response(resp, elapsed_sec=elapsed, no_color=args.no_color)
        return 0

    return run_repl(args.report_id, no_color=args.no_color)


if __name__ == "__main__":
    sys.exit(main())
