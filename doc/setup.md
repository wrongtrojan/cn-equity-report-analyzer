# 环境与初始化

> 文档索引：[README.md](README.md)

本文说明首次运行 RE 项目所需的环境、数据库与配置。各阶段用法分别见 [parse.md](parse.md)、[ingest.md](ingest.md)、[qa.md](qa.md)。

## 前置要求

| 组件 | 版本 / 说明 |
|------|-------------|
| Python | 3.10+ |
| PostgreSQL | 16+，需安装 **pgvector**、**pg_trgm** |
| GPU | 可选；MinerU `pipeline` 后端可用 CUDA 加速 |

## Python 环境

推荐使用 Conda 环境 `RE`，包含：

- `psycopg2-binary` — 数据库
- `sentence-transformers` — embedding（入库）
- `mineru[all]` — PDF 解析
- `openai`、`jinja2`、`beautifulsoup4`、`python-dotenv` 等

```bash
# 示例（按实际环境调整）
conda create -n RE python=3.11
conda activate RE
pip install -U "mineru[all]" psycopg2-binary sentence-transformers openai jinja2 beautifulsoup4 python-dotenv pgvector
```

所有 `python -m pipeline.*` 命令均在 **项目根目录** 执行。

## 数据库初始化

1. 创建数据库（示例）：

```bash
createdb -h localhost -p 5433 -U trojan re
```

2. 执行建表脚本：

```bash
psql "$DATABASE_URL" -f db/schema_base.sql
psql "$DATABASE_URL" -f db/schema_kg.sql
```

- [`db/schema_base.sql`](../db/schema_base.sql) — 公司、报告、章节、表格、facts、chunks 等
- [`db/schema_kg.sql`](../db/schema_kg.sql) — `kg_entities` / `kg_relations` / `kg_relation_evidence`

表结构说明见 [database_schema.md](database_schema.md)。

## 环境变量

```bash
cp .env.example .env
```

[`pipeline/env.py`](../pipeline/env.py) 在模块加载时读取项目根 `.env`（`override=False`，shell 已 export 的变量优先）。

### 数据库

| 变量 | 默认 | 说明 |
|------|------|------|
| `DATABASE_URL` | `postgresql://trojan@localhost:5433/re` | PostgreSQL 连接串 |

### Embedding / 切块（ingest）

| 变量 | 默认 | 说明 |
|------|------|------|
| `EMBED_MODEL` | `BAAI/bge-m3` | 向量模型，须与 QA 一致 |
| `EMBED_DIM` | `1024` | 向量维度，对应 `text_chunks.embedding VECTOR(1024)` |
| `CHUNK_SIZE` | `900` | 切块字符数 |
| `CHUNK_OVERLAP` | `120` | 切块重叠 |

修改以上参数会改变 `ingest_fingerprint`，触发重 embedding；结构化数据是否重建仍取决于 `--force`。

### LLM（QA、关系补漏）

| 变量 | 默认 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` | — | **必填**（QA 与 `--refine-text-relations`） |
| `OPENAI_BASE_URL` | OpenAI 官方 | 兼容端点 |
| `LLM_MODEL` | `gpt-4o-mini` | 全项目默认 LLM |

### QA 检索（可选）

| 变量 | 默认 | 说明 |
|------|------|------|
| `QA_LLM_MODEL` | 同 `LLM_MODEL` | QA 专用模型 |
| `QA_SQL_TOP_K` | `5` | SQL 证据条数 |
| `QA_VECTOR_TOP_K` | `5` | 向量证据条数 |
| `QA_MAX_EVIDENCE` | `8` | 合并后上限 |
| `QA_MAX_SESSION_TURNS` | `5` | REPL 会话保留轮数 |
| `QA_NORMALIZE_TIMEOUT` | `60` | 查询标准化超时（秒） |
| `QA_ANSWER_TIMEOUT` | `90` | 作答生成超时（秒） |

QA 细节见 [qa.md](qa.md)。

## 目录准备

| 路径 | 用途 |
|------|------|
| `pipeline/parse/input/` | 放置待解析 PDF（`*.pdf`） |
| `pipeline/parse/parse_result/` | MinerU 输出（可含样例报告） |
| `report/output/` | 关系图谱 HTML 输出 |

`input/` 目录需自行创建；parse 脚本会扫描其中 PDF。

## 首次端到端验证

```bash
cp .env.example .env          # 填写 OPENAI_API_KEY、DATABASE_URL

python pipeline/parse/mineru_parse.py
python -m pipeline.ingest.ingest --with-relations --force
python -m pipeline.qa.cli --report-id 1 --query "2025年营业总收入是多少"
```

验收 SQL 与基线数值见 [database_schema.md §7](database_schema.md#7-常用验收-sql)。

## 相关文档

| 文档 | 说明 |
|------|------|
| [parse.md](parse.md) | PDF 解析 |
| [ingest.md](ingest.md) | 入库 CLI |
| [eval.md](eval.md) | 回归评测 |
| [database_schema.md](database_schema.md) | 表结构 |
