#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU 本地解析脚本（Phase1）

用法：
  # 直接运行：解析 pipeline/input/ 下所有 PDF，输出到 pipeline/parse_result/
  python mineru_parse.py

  # 指定单个 PDF
  python mineru_parse.py --pdf /path/to/report.pdf

  # 强制重新解析（忽略已有结果）
  python mineru_parse.py --force

幂等策略：
  - 以 PDF 内容 SHA256 + 解析参数（lang/backend/parse_method）作为缓存键
  - 若 parse_result/{stem}/ 下产物完整且指纹一致，则跳过
  - 重新解析时使用 staging 目录，成功后原子替换，避免半成品污染

输出结构（每个 PDF 一个子目录）：
  parse_result/{pdf_stem}/
    ├── {pdf_stem}.md
    ├── {pdf_stem}_middle.json
    ├── images/
    └── meta.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = SCRIPT_DIR / "input"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "parse_result"
META_FILENAME = "meta.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _check_gpu() -> str:
    """检测 GPU 并返回设备描述。"""
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            return f"CUDA ({name}, {vram_gb:.1f} GB)"
    except ImportError:
        pass
    return "CPU"


def _import_do_parse():
    try:
        from mineru.cli.common import do_parse

        return do_parse
    except ImportError as e:
        raise RuntimeError(
            '无法导入 MinerU SDK，请先安装: pip install -U "mineru[all]"'
        ) from e


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _parse_config(lang: str, backend: str, parse_method: str) -> dict[str, str]:
    return {
        "lang": lang,
        "backend": backend,
        "parse_method": parse_method,
    }


def _output_paths(out_root: Path, stem: str) -> dict[str, Path]:
    final_dir = out_root / stem
    return {
        "dir": final_dir,
        "md": final_dir / f"{stem}.md",
        "middle": final_dir / f"{stem}_middle.json",
        "meta": final_dir / META_FILENAME,
        "images": final_dir / "images",
        "staging": out_root / f".{stem}.staging",
    }


def _build_fingerprint(pdf_path: Path, config: dict[str, str]) -> dict[str, Any]:
    stat = pdf_path.stat()
    return {
        "source_pdf": str(pdf_path.resolve()),
        "pdf_name": pdf_path.name,
        "pdf_sha256": _sha256_file(pdf_path),
        "pdf_size": stat.st_size,
        "pdf_mtime": int(stat.st_mtime),
        "parse_config": config,
    }


def _load_meta(meta_path: Path) -> dict[str, Any] | None:
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _outputs_complete(paths: dict[str, Path]) -> bool:
    if not paths["md"].is_file() or paths["md"].stat().st_size == 0:
        return False
    if not paths["middle"].is_file() or paths["middle"].stat().st_size == 0:
        return False
    return True


def _fingerprints_match(stored: dict[str, Any], current: dict[str, Any]) -> bool:
    keys = ("pdf_sha256", "pdf_size", "parse_config")
    return all(stored.get(k) == current.get(k) for k in keys)


def _should_skip(
    pdf_path: Path,
    out_root: Path,
    config: dict[str, str],
    *,
    force: bool,
) -> tuple[bool, dict[str, Path], dict[str, Any] | None, str]:
    """
    判断是否可跳过解析。
    返回: (skip, paths, meta, reason)
    """
    paths = _output_paths(out_root, pdf_path.stem)
    fingerprint = _build_fingerprint(pdf_path, config)

    if force:
        return False, paths, None, "force"

    meta = _load_meta(paths["meta"])
    if meta is None:
        return False, paths, None, "no_meta"

    if meta.get("status") != "success":
        return False, paths, meta, "previous_failed_or_incomplete"

    if not _outputs_complete(paths):
        return False, paths, meta, "outputs_missing"

    stored_fp = meta.get("fingerprint", {})
    if not _fingerprints_match(stored_fp, fingerprint):
        return False, paths, meta, "fingerprint_changed"

    return True, paths, meta, "cache_hit"


def _collect_pdfs(pdf_arg: Path | None) -> list[Path]:
    """收集待解析 PDF 列表。"""
    if pdf_arg is None:
        search_dir = DEFAULT_INPUT_DIR
        if not search_dir.exists():
            search_dir.mkdir(parents=True, exist_ok=True)
            raise FileNotFoundError(
                f"未指定 --pdf，且默认输入目录为空: {search_dir}\n"
                f"请将 PDF 放入该目录，或使用: python mineru_parse.py --pdf <path>"
            )
        pdfs = sorted(search_dir.glob("*.pdf"))
        if not pdfs:
            raise FileNotFoundError(
                f"默认输入目录下没有 PDF 文件: {search_dir}\n"
                f"请放入 PDF 或使用: python mineru_parse.py --pdf <path>"
            )
        return pdfs

    pdf_arg = pdf_arg.expanduser().resolve()
    if pdf_arg.is_dir():
        pdfs = sorted(pdf_arg.glob("*.pdf"))
        if not pdfs:
            raise FileNotFoundError(f"目录下没有 PDF: {pdf_arg}")
        return pdfs
    if pdf_arg.suffix.lower() != ".pdf":
        raise ValueError(f"不是 PDF 文件: {pdf_arg}")
    if not pdf_arg.exists():
        raise FileNotFoundError(f"PDF 不存在: {pdf_arg}")
    return [pdf_arg]


def _run_mineru(
    do_parse,
    pdf_path: Path,
    work_dir: Path,
    *,
    lang: str,
    backend: str,
    parse_method: str,
) -> Path:
    """
    调用 MinerU 解析单个 PDF。
    MinerU 原始输出路径: {work_dir}/{pdf_filename}/{parse_method}/
    返回该目录 Path。
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    pdf_bytes = pdf_path.read_bytes()
    pdf_file_name = pdf_path.name

    do_parse(
        output_dir=str(work_dir),
        pdf_file_names=[pdf_file_name],
        pdf_bytes_list=[pdf_bytes],
        p_lang_list=[lang],
        backend=backend,
        parse_method=parse_method,
        formula_enable=True,
        table_enable=True,
        f_dump_md=True,
        f_dump_middle_json=True,
        f_dump_content_list=False,
        f_dump_model_output=False,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
        f_dump_orig_pdf=False,
    )

    parse_dir = work_dir / pdf_file_name / parse_method
    if not parse_dir.exists():
        candidates = list(work_dir.rglob("*_middle.json"))
        if not candidates:
            raise RuntimeError(
                f"MinerU 解析完成但未找到输出目录: {parse_dir}\n"
                f"请检查 MinerU 日志。"
            )
        parse_dir = candidates[0].parent

    return parse_dir


def _consolidate_output(
    parse_dir: Path,
    pdf_path: Path,
    paths: dict[str, Path],
    fingerprint: dict[str, Any],
    *,
    mineru_raw_dir: str,
) -> tuple[Path, Path]:
    """
    将 MinerU 输出写入 staging 目录，校验通过后原子替换 final 目录。
    """
    stem = pdf_path.stem
    staging_dir = paths["staging"]
    final_dir = paths["dir"]

    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)

    md_src = parse_dir / f"{pdf_path.name}.md"
    middle_src = parse_dir / f"{pdf_path.name}_middle.json"

    if not md_src.exists():
        md_candidates = list(parse_dir.glob("*.md"))
        if not md_candidates:
            raise RuntimeError(f"未找到 Markdown: {parse_dir}")
        md_src = md_candidates[0]

    if not middle_src.exists():
        middle_candidates = list(parse_dir.glob("*_middle.json"))
        if not middle_candidates:
            raise RuntimeError(f"未找到 middle.json: {parse_dir}")
        middle_src = middle_candidates[0]

    md_dst = staging_dir / f"{stem}.md"
    middle_dst = staging_dir / f"{stem}_middle.json"
    shutil.copy2(md_src, md_dst)
    shutil.copy2(middle_src, middle_dst)

    images_src = parse_dir / "images"
    if images_src.exists() and any(images_src.iterdir()):
        shutil.copytree(images_src, staging_dir / "images")

    meta = {
        "status": "success",
        "parsed_at": _utc_now_iso(),
        "fingerprint": fingerprint,
        "outputs": {
            "markdown": f"{stem}.md",
            "middle_json": f"{stem}_middle.json",
            "images_dir": "images" if (staging_dir / "images").exists() else None,
        },
        "mineru_raw_dir": mineru_raw_dir,
    }
    (staging_dir / META_FILENAME).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    staging_paths = {
        "dir": staging_dir,
        "md": md_dst,
        "middle": middle_dst,
        "meta": staging_dir / META_FILENAME,
        "images": staging_dir / "images",
        "staging": staging_dir,
    }
    if not _outputs_complete(staging_paths):
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise RuntimeError("staging 产物校验失败，已回滚")

    backup_dir = final_dir.parent / f".{stem}.backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    if final_dir.exists():
        final_dir.rename(backup_dir)

    try:
        staging_dir.rename(final_dir)
    except Exception:
        if backup_dir.exists() and not final_dir.exists():
            backup_dir.rename(final_dir)
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    if backup_dir.exists():
        shutil.rmtree(backup_dir, ignore_errors=True)

    final_paths = _output_paths(final_dir.parent, stem)
    return final_paths["middle"], final_paths["md"]


def parse_one(
    pdf_path: Path,
    out_root: Path,
    *,
    lang: str = "ch",
    backend: str = "pipeline",
    parse_method: str = "auto",
    keep_raw: bool = False,
    force: bool = False,
) -> tuple[Path, Path, str]:
    """
    解析单个 PDF。
    返回: (middle_json_path, markdown_path, status)
    status: "skipped" | "parsed"
    """
    config = _parse_config(lang, backend, parse_method)
    skip, paths, _meta, reason = _should_skip(
        pdf_path, out_root, config, force=force
    )

    if skip:
        print(f"  [跳过] 已存在且指纹一致 ({reason})")
        return paths["middle"], paths["md"], "skipped"

    if reason != "force":
        print(f"  [重解析] 原因: {reason}")

    fingerprint = _build_fingerprint(pdf_path, config)
    do_parse = _import_do_parse()

    work_dir = out_root / "_mineru_work"
    parse_dir = _run_mineru(
        do_parse,
        pdf_path,
        work_dir,
        lang=lang,
        backend=backend,
        parse_method=parse_method,
    )

    try:
        middle_dst, md_dst = _consolidate_output(
            parse_dir,
            pdf_path,
            _output_paths(out_root, pdf_path.stem),
            fingerprint,
            mineru_raw_dir=str(parse_dir),
        )
    finally:
        if not keep_raw:
            raw_parent = work_dir / pdf_path.name
            if raw_parent.exists():
                shutil.rmtree(raw_parent, ignore_errors=True)

    return middle_dst, md_dst, "parsed"


def parse_batch(
    pdfs: list[Path],
    out_root: Path,
    *,
    lang: str,
    backend: str,
    parse_method: str,
    keep_raw: bool,
    force: bool,
) -> list[tuple[Path, Path, Path, str]]:
    """批量解析，返回 [(pdf_path, middle_json, markdown, status), ...]。"""
    results: list[tuple[Path, Path, Path, str]] = []
    for i, pdf_path in enumerate(pdfs, 1):
        print(f"\n[{i}/{len(pdfs)}] 处理: {pdf_path.name}")
        middle, md, status = parse_one(
            pdf_path,
            out_root,
            lang=lang,
            backend=backend,
            parse_method=parse_method,
            keep_raw=keep_raw,
            force=force,
        )
        print(f"  -> {middle}")
        print(f"  -> {md}")
        results.append((pdf_path, middle, md, status))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MinerU PDF 解析：输出 middle.json + markdown 到 parse_result/"
    )
    parser.add_argument(
        "--pdf",
        default=None,
        help=f"PDF 文件或目录；省略则扫描 {DEFAULT_INPUT_DIR}",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"输出根目录（默认: {DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument("--lang", default="ch", help="语言: ch / ch_server / en")
    parser.add_argument(
        "--backend",
        default="pipeline",
        choices=["pipeline", "hybrid-auto-engine"],
        help="解析后端；有 GPU 时 pipeline 会自动使用 CUDA（推荐）",
    )
    parser.add_argument(
        "--parse-method",
        default="auto",
        choices=["auto", "txt", "ocr"],
        help="解析模式：auto 自动判断文本层/OCR",
    )
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="保留 _mineru_work/ 下的 MinerU 原始输出（调试用）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新解析，忽略已有缓存结果",
    )
    args = parser.parse_args()

    device = _check_gpu()
    print(f"设备: {device}")
    print(f"后端: {args.backend}")
    print(f"输出: {Path(args.out).resolve()}")
    print(f"幂等: {'关闭 (--force)' if args.force else '开启 (SHA256 + 解析参数)'}")

    pdf_arg = Path(args.pdf) if args.pdf else None
    pdfs = _collect_pdfs(pdf_arg)
    out_root = Path(args.out).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"待处理 PDF 数量: {len(pdfs)}")

    results = parse_batch(
        pdfs,
        out_root,
        lang=args.lang,
        backend=args.backend,
        parse_method=args.parse_method,
        keep_raw=args.keep_raw,
        force=args.force,
    )

    parsed = sum(1 for *_, status in results if status == "parsed")
    skipped = sum(1 for *_, status in results if status == "skipped")

    print("\n全部完成:")
    for pdf_path, middle, md, status in results:
        tag = "跳过" if status == "skipped" else "解析"
        print(f"  [{tag}] {pdf_path.name}")
        print(f"    middle: {middle}")
        print(f"    md    : {md}")

    print(f"\n统计: 解析 {parsed} 个, 跳过 {skipped} 个")

    work_dir = out_root / "_mineru_work"
    if work_dir.exists() and not args.keep_raw and not any(work_dir.iterdir()):
        work_dir.rmdir()

    return 0


if __name__ == "__main__":
    sys.exit(main())
