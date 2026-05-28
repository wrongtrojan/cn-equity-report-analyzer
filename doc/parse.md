# PDF 解析（MinerU）

## 概述

解析模块将上市公司年报 PDF 转为结构化文本与版面中间表示，供后续入库使用。实现基于 [MinerU](https://github.com/opendatalab/MinerU) SDK，输出保留 HTML 表格、标题层级与页码映射信息。

**入口脚本**：[`pipeline/parse/mineru_parse.py`](../pipeline/parse/mineru_parse.py)

## 目录结构

| 路径 | 说明 |
|------|------|
| `pipeline/parse/input/` | 待解析 PDF 放置目录（默认扫描 `*.pdf`） |
| `pipeline/parse/parse_result/` | 解析产物根目录，每个 PDF 对应一个子目录 |
| `pipeline/parse/parse_result/_mineru_work/` | MinerU 临时工作区（默认可清理） |

单份报告产物示例：

```text
parse_result/东方财富年报/
├── meta.json                 # 状态、指纹、产物路径索引
├── 东方财富年报.md           # 全文 Markdown（含 <table> HTML）
├── 东方财富年报_middle.json  # 版面/块级 JSON（含页码、表格 HTML）
└── images/                   # 抽取的图片（可选）
```

## 产物说明

### `meta.json`

记录解析是否成功、时间戳、源文件指纹及相对路径，供入库模块判断是否可跳过重复处理。

| 字段 | 含义 |
|------|------|
| `status` | `success` 表示产物完整可用 |
| `fingerprint.pdf_sha256` | 源 PDF 内容哈希 |
| `fingerprint.parse_config` | `lang` / `backend` / `parse_method` |
| `outputs.markdown` | 相对路径至 `.md` 文件 |
| `outputs.middle_json` | 相对路径至 `_middle.json` |
| `outputs.images_dir` | 图片子目录名，无则为 `null` |

### Markdown（`.md`）

- 保留 MinerU 生成的标题（`#` / `##`）与 HTML `<table>` 块。
- 公司概况表（股票代码、公司名称等）通常为 HTML 表格，入库时从中正则提取元数据。
- 表格不转为 Markdown 管道表，以便后续用 BeautifulSoup 解析表头与单元格。

### Middle JSON（`*_middle.json`）

- 包含 `pdf_info` 等层级结构，每个 `table` 块带 `html` 与 `page_idx`。
- 入库时遍历该文件，建立「表格 HTML → 页码」映射，写入 `structured_tables.page_num`。

## 幂等与缓存

解析默认**开启幂等**：在 `parse_result/{pdf_stem}/` 已存在且满足下列条件时跳过 MinerU 调用：

1. `meta.json` 中 `status == success`
2. `.md` 与 `_middle.json` 非空
3. 存储指纹与当前 PDF 的 `pdf_sha256`、`pdf_size`、`parse_config` 一致

使用 `--force` 可强制全量重解析。重解析采用 **staging 目录 + 原子替换**：先写入 `.{stem}.staging`，校验通过后替换正式目录，避免半成品污染。

指纹变更场景（会触发重解析）：

- PDF 文件内容变化
- 修改 `--lang`、`--backend`、`--parse-method` 等解析参数

## 命令行

在 `pipeline/parse/` 目录或项目根目录执行：

```bash
# 解析 input/ 下全部 PDF
python pipeline/parse/mineru_parse.py

# 指定单个文件或目录
python pipeline/parse/mineru_parse.py --pdf /path/to/report.pdf
python pipeline/parse/mineru_parse.py --pdf /path/to/pdf_dir/

# 强制重解析
python pipeline/parse/mineru_parse.py --force

# 自定义输出根目录
python pipeline/parse/mineru_parse.py --out /path/to/parse_result
```

### 常用参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--lang` | `ch` | 文档语言（`ch` / `ch_server` / `en`） |
| `--backend` | `pipeline` | MinerU 后端；有 GPU 时 `pipeline` 可使用 CUDA |
| `--parse-method` | `auto` | `auto` / `txt` / `ocr` |
| `--keep-raw` | 关 | 保留 `_mineru_work/` 原始输出（调试） |
| `--force` | 关 | 忽略缓存 |

## 依赖与环境

- Python 3.10+
- MinerU：`pip install -U "mineru[all]"`
- 可选 GPU：`torch` + CUDA（脚本启动时会打印设备信息）

解析**不连接数据库**；完成后需运行 [ingest.md](ingest.md) 中的入库命令。

## 与下游的衔接

入库模块扫描 `parse_result/*` 下含 `meta.json` 的子目录，读取：

- `meta.json` → 校验 `status`、计算 `ingest_fingerprint`
- `outputs.markdown` → 章节切分、表格抽取
- `outputs.middle_json` → 表格页码

若仅更新解析产物而未改 embedding 相关参数，入库可能因 `ingest_fingerprint` 未变而跳过；需使用 `ingest_report --force` 强制重建数据库侧数据。

## 故障排查

| 现象 | 处理建议 |
|------|----------|
| `无法导入 MinerU SDK` | 在 `RE` 环境中安装 `mineru[all]` |
| 输出目录找不到 `*_middle.json` | 加 `--keep-raw` 查看 `_mineru_work`，核对 MinerU 版本与日志 |
| 重复解析耗时过长 | 确认未误用 `--force`；检查 `meta.json` 指纹是否与当前 PDF 一致 |
| 表格在 MD 中缺失 | 确认 `table_enable=True`（脚本内已默认开启） |
