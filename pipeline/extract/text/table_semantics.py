"""Shared table semantics helpers for classification and relation extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

SUMMARY_LABELS = frozenset({"合计", "小计", "总计", "-", "—", ""})

ROLE_LABELS = frozenset(
    {
        "董事长",
        "副董事长",
        "总经理",
        "副总经理",
        "财务总监",
        "董事会秘书",
        "总裁",
        "首席执行官",
        "董事",
        "独立董事",
        "监事",
        "职工代表监事",
        "监事会主席",
        "合规总监",
        "姓名",
        "职务",
        "担任的职务",
    }
)

ACCOUNTING_TERMS = frozenset(
    {
        "坏账准备",
        "账面余额",
        "其他应收款",
        "其他应付款",
        "租赁负债",
        "使用权资产",
        "应付账款",
        "项目名称",
        "本期发生额",
        "上期发生额",
    }
)

ORG_SUFFIXES = ("公司", "有限", "集团", "银行", "基金", "中心", "商会", "研究院", "合伙")


def table_text_blob(headers: list[str], rows: list[list[str]], *, max_rows: int = 40) -> str:
    parts = [str(cell).strip() for cell in headers if str(cell).strip()]
    for row in rows[:max_rows]:
        for cell in row:
            text = str(cell).strip()
            if text:
                parts.append(text)
    return "|".join(parts)


def headers_text(headers: list[str]) -> str:
    return "|".join(str(h).strip() for h in headers)


def find_dynamic_header_row(rows: list[list[str]], *markers: str) -> int | None:
    for idx, row in enumerate(rows):
        if not row:
            continue
        row_text = "|".join(str(c).strip() for c in row)
        if any(marker in row_text for marker in markers):
            if any(str(c).strip() in markers for c in row):
                return idx
    return None


def header_rows(headers: list[str], rows: list[list[str]]) -> list[list[str]]:
    result: list[list[str]] = []
    static = [str(h).strip() for h in headers]
    if static and any(static):
        result.append(static)
    idx = find_dynamic_header_row(rows, "股东名称", "姓名", "关联方", "公司名称")
    if idx is not None:
        dynamic = [str(c).strip() for c in rows[idx]]
        if dynamic not in result:
            result.append(dynamic)
    return result


def _col_index_in_row(row: list[str], *candidates: str) -> int | None:
    for idx, cell in enumerate(row):
        text = str(cell).strip()
        for candidate in candidates:
            if candidate in text:
                return idx
    return None


def resolve_column_map(
    headers: list[str],
    rows: list[list[str]],
    aliases: dict[str, tuple[str, ...]],
) -> dict[str, int]:
    search_rows: list[list[str]] = []
    static = [str(h).strip() for h in headers]
    if static:
        search_rows.append(static)
    header_idx = find_dynamic_header_row(
        rows,
        "股东名称",
        "姓名",
        "关联方",
        "公司名称",
        "其他关联方名称",
        "合营或联营企业名称",
    )
    if header_idx is not None:
        search_rows.append([str(c).strip() for c in rows[header_idx]])

    col_map: dict[str, int] = {}
    for logical, candidates in aliases.items():
        if logical in col_map:
            continue
        for row in search_rows:
            idx = _col_index_in_row(row, *candidates)
            if idx is not None:
                col_map[logical] = idx
                break
    return col_map


def _is_header_like_row(row: list[str], col_map: dict[str, int]) -> bool:
    if not row:
        return True
    first = str(row[0]).strip()
    if first in {"股东名称", "姓名", "公司名称", "关联方", "项目名称", "数量", "比例", "股份状态"}:
        return True
    if first.startswith("持股") and "股东" in first:
        return True
    name_idx = col_map.get("name")
    if name_idx is not None and name_idx < len(row):
        val = str(row[name_idx]).strip()
        if val in {"股东名称", "姓名", "关联方", "公司名称"}:
            return True
    return False


def iter_data_rows(
    headers: list[str],
    rows: list[list[str]],
    col_map: dict[str, int],
) -> Iterator[list[str]]:
    header_idx = find_dynamic_header_row(
        rows,
        "股东名称",
        "姓名",
        "关联方",
        "公司名称",
    )
    start = (header_idx + 1) if header_idx is not None else 0
    if header_idx is None and _col_index_in_row([str(h) for h in headers], "股东名称", "姓名", "关联方"):
        start = 0
    for row in rows[start:]:
        if row and is_section_title_row(str(row[0]).strip()):
            break
        if _is_header_like_row(row, col_map):
            continue
        if not any(str(c).strip() for c in row):
            continue
        yield row


def is_summary_row(name: str) -> bool:
    text = str(name).strip()
    return text in SUMMARY_LABELS


def is_role_label(name: str) -> bool:
    text = str(name).strip()
    return text in ROLE_LABELS or any(text == label for label in ROLE_LABELS)


def split_role_titles(text: str) -> list[str]:
    raw = str(text).strip()
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[、,，/]", raw) if part.strip()]


def is_known_role_title(text: str) -> bool:
    token = str(text).strip()
    if not token:
        return False
    if is_role_label(token):
        return True
    role_markers = ("董事", "监事", "总经理", "总裁", "秘书", "总监", "首席")
    return any(marker in token for marker in role_markers)


@dataclass
class RosterRecord:
    name: str
    titles: list[str] = field(default_factory=list)
    gender: str = ""
    status: str = ""


def _collect_title_tokens(raw: str) -> list[str]:
    return [part for part in split_role_titles(raw) if is_known_role_title(part)]


def _is_valid_roster_main_row(name: str, gender: str, status: str) -> bool:
    if not looks_like_person_name(name):
        return False
    if not gender and not status:
        return False
    if not gender and status in {"现任", "离任"}:
        return False
    return True


def _is_roster_continuation_row(
    name: str,
    title: str,
    gender: str,
    status: str,
    *,
    current: RosterRecord | None,
) -> bool:
    if current is None or looks_like_person_name(name):
        return False
    if is_role_label(name):
        return True
    if title and is_role_label(title) and not gender and not status:
        return True
    if not name.strip() and _collect_title_tokens(title):
        return True
    return False


def _continuation_titles(name: str, title: str) -> list[str]:
    if is_role_label(name):
        return [name.strip()]
    return _collect_title_tokens(title)


def iter_roster_records(
    headers: list[str],
    rows: list[list[str]],
    col_map: dict[str, int],
) -> Iterator[RosterRecord]:
    name_idx = col_map.get("name")
    title_idx = col_map.get("title")
    if name_idx is None or title_idx is None:
        return

    def cell(row: list[str], idx: int | None) -> str:
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx]).strip()

    current: RosterRecord | None = None

    for row in iter_data_rows(headers, rows, col_map):
        name = cell(row, name_idx)
        title = cell(row, title_idx)
        gender = cell(row, col_map.get("gender"))
        status = cell(row, col_map.get("status"))

        if is_summary_row(name):
            continue

        if _is_roster_continuation_row(name, title, gender, status, current=current):
            for extra_title in _continuation_titles(name, title):
                if extra_title not in current.titles:
                    current.titles.append(extra_title)
            continue

        if current is not None:
            yield current
            current = None

        if not _is_valid_roster_main_row(name, gender, status):
            continue

        titles = _collect_title_tokens(title)
        if not titles and title:
            titles = [title]

        current = RosterRecord(name=name, titles=titles, gender=gender, status=status)

    if current is not None:
        yield current


def is_accounting_term(name: str) -> bool:
    text = str(name).strip()
    if text in ACCOUNTING_TERMS:
        return True
    return text.endswith("余额") and len(text) <= 8


def looks_like_person_name(name: str) -> bool:
    text = str(name).strip()
    if not text or is_summary_row(text) or is_role_label(text) or is_accounting_term(text):
        return False
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", text):
        return True
    if re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", text):
        return True
    return False


def is_section_title_row(first_cell: str) -> bool:
    text = str(first_cell).strip()
    if not text:
        return False
    markers = (
        "战略投资者",
        "上述股东",
        "前 10",
        "前10",
        "参与融资",
        "说明",
        "情况",
    )
    return any(text.startswith(m) for m in markers)


def is_valid_share_ratio(value: str) -> bool:
    text = str(value).strip()
    return bool(re.fullmatch(r"[\d.,]+%?", text)) and "%" in text


def looks_like_org_name(name: str) -> bool:
    text = str(name).strip()
    if not text or is_summary_row(text) or is_accounting_term(text):
        return False
    if is_role_label(text):
        return False
    if any(suffix in text for suffix in ORG_SUFFIXES):
        return True
    if len(text) >= 6 and re.search(r"[\u4e00-\u9fff]", text):
        return True
    return False
