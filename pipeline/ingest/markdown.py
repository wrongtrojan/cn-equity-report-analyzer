# pipeline/ingest/markdown.py
"""Markdown 解析：章节切分、表格抽取、切块与元数据推断。"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


@dataclass
class Section:
    seq_no: int
    title_raw: str
    heading_level: int
    section_key: str | None
    content_md: str


@dataclass
class ParsedTable:
    table_seq: int
    html_raw: str
    headers: list[str]
    rows: list[list[str]]
    section_key: str | None
    table_title: str | None
    page_num: int | None
    header_hash: str
    table_type_guess: str | None = None


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def match_section_key(title: str, aliases) -> str | None:
    matched = []
    for pattern, key, priority in aliases:
        if re.search(pattern, title.strip()):
            matched.append((priority, key))
    return sorted(matched)[0][1] if matched else None


def hierarchy_level(title: str, md_level: int) -> int:
    """Map markdown headings to a logical outline depth for key inheritance."""
    t = title.strip()
    if re.search(r"第[一二三四五六七八九十百\d]+节", t):
        return 1
    if re.match(r"^[一二三四五六七八九十]+、", t):
        return 2
    if re.match(r"^[（(][一二三四五六七八九十]+[)）]", t):
        return 3
    if re.match(r"^\d+[、.．]", t):
        return 3
    return md_level + 10


def resolve_section_key(title: str, md_level: int, aliases, key_stack: list[tuple[int, str | None]]) -> str | None:
    direct = match_section_key(title, aliases)
    if direct:
        return direct
    h_level = hierarchy_level(title, md_level)
    for lv, key in reversed(key_stack):
        if lv < h_level and key:
            return key
    return None


def split_sections(md_text: str, aliases) -> list[Section]:
    lines = md_text.splitlines()
    sections: list[Section] = []
    current_title, current_level, current_lines, seq = "文档开头", 1, [], 0
    heading_re = re.compile(r"^(#{1,6})\s+(.*)$")
    key_stack: list[tuple[int, str | None]] = []

    def flush() -> None:
        nonlocal seq, current_lines
        h_level = hierarchy_level(current_title, current_level)
        key = resolve_section_key(current_title, current_level, aliases, key_stack)
        seq += 1
        sections.append(
            Section(
                seq,
                current_title.strip(),
                current_level,
                key,
                "\n".join(current_lines).strip(),
            )
        )
        while key_stack and key_stack[-1][0] >= h_level:
            key_stack.pop()
        key_stack.append((h_level, key))
        current_lines = []

    for line in lines:
        m = heading_re.match(line.strip())
        if m:
            flush()
            current_level, current_title = len(m.group(1)), m.group(2)
        else:
            current_lines.append(line)
    flush()
    return sections


def parse_html_table(html: str):
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return [], []
    matrix = []
    for tr in table.find_all("tr"):
        row = [re.sub(r"\s+", " ", unescape(td.get_text())).strip()
               for td in tr.find_all(["td", "th"])]
        if any(row):
            matrix.append(row)
    if not matrix:
        return [], []
    return matrix[0], matrix[1:]


def build_section_ranges(md_text: str, sections: list[Section]) -> list[tuple[int, int, Section]]:
    """按标题在原文中的位置切分区间，避免 find(title) 误匹配。"""
    heading_re = re.compile(r"^#{1,6}\s+", re.M)
    heading_starts = [m.start() for m in heading_re.finditer(md_text)]
    ranges: list[tuple[int, int, Section]] = []

    for i, sec in enumerate(sections):
        if i == 0:
            start, end = 0, heading_starts[0] if heading_starts else len(md_text)
        elif i <= len(heading_starts):
            start = heading_starts[i - 1]
            end = heading_starts[i] if i < len(heading_starts) else len(md_text)
        else:
            start = heading_starts[-1] if heading_starts else 0
            end = len(md_text)
        ranges.append((start, end, sec))
    return ranges


def _section_for_position(ranges: list[tuple[int, int, Section]], pos: int) -> Section | None:
    for start, end, sec in ranges:
        if start <= pos < end:
            return sec
    if ranges:
        return ranges[-1][2]
    return None


def extract_tables(md_text: str, aliases) -> list[ParsedTable]:
    sections = split_sections(md_text, aliases)
    ranges = build_section_ranges(md_text, sections)

    tables = []
    for i, m in enumerate(re.finditer(r"<table[\s\S]*?</table>", md_text, re.I), 1):
        html = m.group(0)
        headers, rows = parse_html_table(html)
        if not headers and not rows:
            continue
        sec = _section_for_position(ranges, m.start())
        tables.append(ParsedTable(
            i, html, headers, rows,
            sec.section_key if sec else None,
            sec.title_raw if sec else None,
            None, sha256_text("|".join(headers))
        ))
    return tables


def build_table_page_map(middle_path: Path) -> dict[str, int]:
    data = json.loads(middle_path.read_text(encoding="utf-8"))
    page_map: dict[str, int] = {}

    def walk(node: Any):
        if isinstance(node, dict):
            yield node
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    for page in data.get("pdf_info", []):
        page_num = int(page.get("page_idx", 0)) + 1
        for block in walk(page):
            if block.get("type") == "table" and block.get("html"):
                page_map[sha256_text(block["html"])] = page_num

    return page_map


def attach_page_numbers(tables: list[ParsedTable], page_map: dict[str, int]):
    for t in tables:
        t.page_num = page_map.get(sha256_text(t.html_raw))


def extract_company_info(md_text: str):
    title = re.search(r"^#\s+(.+)$", md_text, re.M)
    year = re.search(r"(\d{4})\s*年\s*年度报告", md_text)
    code = re.search(r"股票代码</td><td[^>]*>(\d{6})</td>", md_text)
    name = re.search(r"公司的中文名称</td><td[^>]*>([^<]+)</td>", md_text)
    stock_code = code.group(1) if code else None
    stock_name = name.group(1).strip() if name else (title.group(1).strip() if title else None)
    report_year = int(year.group(1)) if year else None
    return stock_code, stock_name, report_year, (title.group(1).strip() if title else None)


def guess_exchange(stock_code: str) -> str | None:
    if stock_code.startswith(("600", "601", "603", "605", "688")):
        return "SSE"
    if stock_code.startswith(("000", "001", "002", "003", "300", "301")):
        return "SZSE"
    return None


def strip_for_chunking(md_text: str) -> str:
    text = re.sub(r"<table[\s\S]*?</table>", " ", md_text, flags=re.I)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    if not text:
        return []
    chunks, start, n = [], 0, len(text)
    while start < n:
        end = min(start + size, n)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def compute_ingest_fingerprint(meta, md_path, middle_path, embed_model, chunk_size, chunk_overlap):
    payload = {
        "pdf_sha256": meta["fingerprint"]["pdf_sha256"],
        "parse_config": meta["fingerprint"].get("parse_config"),
        "md_sha256": sha256_file(md_path),
        "middle_sha256": sha256_file(middle_path),
        "embed_model": embed_model,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
    }
    return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))