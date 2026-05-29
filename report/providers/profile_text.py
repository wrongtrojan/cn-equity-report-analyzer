"""Parse QA / regex profile text into structured blocks for HTML."""

from __future__ import annotations

import re


def _strip_prefix(text: str) -> str:
    return text.strip().rstrip("。；;，,")


def _split_title_body(line: str) -> dict[str, str]:
    line = line.strip()
    for sep in ("：", ":"):
        if sep in line:
            title, _, body = line.partition(sep)
            title = _strip_prefix(title)
            body = _strip_prefix(body)
            if title and body:
                return {"title": title, "body": body}
    return {"title": "", "body": _strip_prefix(line)}


def parse_business_list(text: str | None) -> list[dict[str, str]]:
    """Extract ordered business items from QA answer or regex text."""
    if not text or not text.strip():
        return []

    raw = text.strip()
    raw = re.sub(r"^公司主要业务[^：:\n]*[：:]\s*", "", raw)
    raw = re.sub(r"^主要业务[^：:\n]*[：:]\s*", "", raw)

    items: list[dict[str, str]] = []

    numbered = re.split(r"\n\s*(?=\d+[\.、．]\s*)", raw)
    if len(numbered) > 1 or re.match(r"^\d+[\.、．]", raw):
        for part in numbered:
            part = re.sub(r"^\d+[\.、．]\s*", "", part.strip())
            if part:
                items.append(_split_title_body(part))
        if items:
            return items

    bullet_lines = [ln.strip() for ln in re.split(r"\n+", raw) if re.match(r"^[·•\-]\s*", ln.strip())]
    if bullet_lines:
        for ln in bullet_lines:
            ln = re.sub(r"^[·•\-]\s*", "", ln)
            if ln:
                items.append(_split_title_body(ln))
        if items:
            return items

    if "·" in raw or "•" in raw:
        parts = re.split(r"\s*[·•]\s*", raw)
        for part in parts:
            part = part.strip()
            if part and len(part) >= 4:
                items.append(_split_title_body(part))
        if items:
            return items

    segments = re.split(r"(?<=[。；])\s*(?=[^\s，。；]{2,20}业务[：:])", raw)
    if len(segments) > 1:
        for seg in segments:
            seg = seg.strip()
            if seg:
                items.append(_split_title_body(seg))
        if items:
            return items

    if "、" in raw and raw.count("、") <= 5 and len(raw) < 120:
        for part in re.split(r"[、，,；;]", raw):
            part = _strip_prefix(part)
            if part and part not in {"等", "等业务"}:
                items.append({"title": part, "body": ""})

    if items:
        return items

    return [{"title": "", "body": _strip_prefix(raw)}]


def parse_intro_blocks(text: str | None) -> list[dict]:
    """Split intro into paragraphs and bullet/numbered lists."""
    if not text or not text.strip():
        return []

    blocks: list[dict] = []
    paragraphs = re.split(r"\n\s*\n+", text.strip())

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        bullet_lines = [ln for ln in lines if re.match(r"^[·•\-]\s*", ln)]
        numbered_lines = [ln for ln in lines if re.match(r"^\d+[\.、．]\s*", ln)]

        if bullet_lines and len(bullet_lines) == len(lines):
            items = [_split_title_body(re.sub(r"^[·•\-]\s*", "", ln)) for ln in bullet_lines]
            blocks.append({"kind": "list", "ordered": False, "entries": items})
            continue

        if numbered_lines and len(numbered_lines) == len(lines):
            items = [_split_title_body(re.sub(r"^\d+[\.、．]\s*", "", ln)) for ln in numbered_lines]
            blocks.append({"kind": "list", "ordered": True, "entries": items})
            continue

        if "·" in para and para.count("·") >= 2:
            lead_end = para.find("·")
            lead = para[:lead_end].strip()
            if lead and ("包括" in lead or "：" in lead or ":" in lead):
                blocks.append({"kind": "paragraph", "text": lead})
            items = []
            for part in re.split(r"\s*[·•]\s*", para[lead_end:]):
                part = part.strip()
                if part and len(part) >= 4:
                    items.append(_split_title_body(part))
            if items:
                blocks.append({"kind": "list", "ordered": False, "entries": items})
            continue

        blocks.append({"kind": "paragraph", "text": para.replace("\n", " ")})

    return blocks


_BUSINESS_ITEM_HINT = re.compile(
    r"(业务|服务|经纪|销售|数据终端|财富管理|电子商务|期货|证券|基金|资管|投行)"
)


def _trim_business_lead_from_paragraph(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None
    text = re.sub(r"[，,、]?\s*主要业务包括[：:]\s*$", "", text).strip()
    text = re.sub(r"[，,、]?\s*主营业务包括[：:]\s*$", "", text).strip()
    text = re.sub(r"[，,、]?\s*公司主要业务[包括为有][：:][^。]*。?", "", text).strip()
    if re.match(r"^(主要业务|主营业务|公司主要业务)", text) and len(text) < 40:
        return None
    return text or None


def _is_business_enumeration_list(block: dict) -> bool:
    if block.get("kind") != "list":
        return False
    entries = block.get("entries") or []
    if not entries:
        return False
    hits = 0
    for entry in entries:
        label = f"{entry.get('title', '')} {entry.get('body', '')}"
        if _BUSINESS_ITEM_HINT.search(label):
            hits += 1
    return hits >= max(1, len(entries) // 2)


def filter_intro_blocks(blocks: list[dict]) -> list[dict]:
    """Drop business enumeration from intro; main business has its own section."""
    filtered: list[dict] = []
    for block in blocks:
        if block.get("kind") == "paragraph":
            trimmed = _trim_business_lead_from_paragraph(block.get("text") or "")
            if trimmed:
                filtered.append({"kind": "paragraph", "text": trimmed})
        elif block.get("kind") == "list":
            if _is_business_enumeration_list(block):
                continue
            filtered.append(block)
    return filtered


def enrich_profile_narrative(profile: dict) -> dict:
    """Add intro_blocks and main_business_items to profile dict."""
    intro = profile.get("intro") or ""
    business = profile.get("main_business") or ""

    intro_blocks = filter_intro_blocks(parse_intro_blocks(intro))
    if not intro_blocks and intro:
        intro_blocks = filter_intro_blocks([{"kind": "paragraph", "text": intro}])

    business_items = parse_business_list(business)
    if not business_items and profile.get("main_business_tags"):
        business_items = [{"title": t, "body": ""} for t in profile["main_business_tags"]]

    profile["intro_blocks"] = intro_blocks
    profile["main_business_items"] = business_items
    return profile
