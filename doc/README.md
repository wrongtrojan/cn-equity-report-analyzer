# RE 年报智能问答 — 技术文档

本目录收录数据处理与问答链路的说明文档。数据库表结构见 [database_schema.md](database_schema.md)。

| 文档 | 内容 |
|------|------|
| [parse.md](parse.md) | PDF 解析（MinerU）：产物格式、幂等与命令行 |
| [ingest.md](ingest.md) | 结构化入库：章节/表格/指标/向量索引 |
| [qa.md](qa.md) | 混合检索问答：意图路由、检索与评测 |

## 端到端流程

```text
PDF（pipeline/parse/input/）
  → MinerU 解析 → parse_result/{报告名}/
  → PostgreSQL 入库（ingest）
  → 交互式 / 批量问答（qa）
```

**推荐 Python 环境**：项目 Conda 环境 `RE`（含 `psycopg2`、`sentence-transformers`、`mineru` 等依赖）。

```bash
export DATABASE_URL="postgresql://<user>@localhost:5433/re"
/home/trojan/miniconda3/envs/RE/bin/python -m pipeline.ingest.ingest_report
/home/trojan/miniconda3/envs/RE/bin/python -m pipeline.qa.cli --report-id 1
```
