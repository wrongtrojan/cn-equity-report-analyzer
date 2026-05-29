# 环境与配置

## 前置要求

| 组件 | 说明 |
|------|------|
| Python | 3.10+ |
| PostgreSQL | 16+，扩展 **pgvector**、**pg_trgm** |
| GPU | 可选；MinerU `pipeline` 后端可用 CUDA |

## Python 环境

推荐使用 Conda 环境 `RE`：

```bash
conda create -n RE python=3.11
conda activate RE
pip install -U "mineru[all]" psycopg2-binary sentence-transformers openai jinja2 beautifulsoup4 python-dotenv pgvector
```

所有 `python -m pipeline.*` 与 `report.cli` 均在 **项目根目录** 执行。

## 数据库初始化

```bash
createdb -h localhost -p 5433 -U trojan re   # 示例

psql "$DATABASE_URL" -f db/schema_base.sql
psql "$DATABASE_URL" -f db/schema_kg.sql
psql "$DATABASE_URL" -f db/schema_analysis.sql
```

| 脚本 | 内容 |
|------|------|
| `db/schema_base.sql` | 公司、报告、章节、表格、facts、chunks |
| `db/schema_kg.sql` | kg_entities / kg_relations / kg_relation_evidence |
| `db/schema_analysis.sql` | industry_benchmarks、analysis_runs、metric_* |

表结构详解见 [database.md](database.md)。

## 配置

```bash
cp .env.example .env
```

[`pipeline/env.py`](../pipeline/env.py) 在 import 时加载项目根 `.env`（`override=False`）。

### 数据库

| 变量 | 默认 | 说明 |
|------|------|------|
| `DATABASE_URL` | `postgresql://trojan@localhost:5433/re` | PostgreSQL 连接串 |

### Embedding / 切块（ingest）

| 变量 | 默认 | 说明 |
|------|------|------|
| `EMBED_MODEL` | `BAAI/bge-m3` | 须与 QA 向量检索一致 |
| `EMBED_DIM` | `1024` | 对应 `text_chunks.embedding` |
| `CHUNK_SIZE` | `900` | 切块字符数 |
| `CHUNK_OVERLAP` | `120` | 重叠 |

修改以上参数会改变 `ingest_fingerprint`；结构化是否重建仍取决于 `--force`。

### LLM

| 变量 | 默认 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` | — | **必填**（QA、关系 refine、分析解释） |
| `OPENAI_BASE_URL` | OpenAI 官方 | 兼容端点 |
| `LLM_MODEL` | `gpt-4o-mini` | 全项目默认 |

### QA 检索（可选）

| 变量 | 默认 |
|------|------|
| `QA_LLM_MODEL` | 同 `LLM_MODEL` |
| `QA_SQL_TOP_K` | `5` |
| `QA_VECTOR_TOP_K` | `5` |
| `QA_MAX_EVIDENCE` | `8` |
| `QA_MAX_SESSION_TURNS` | `5` |
| `QA_NORMALIZE_TIMEOUT` | `60` |
| `QA_ANSWER_TIMEOUT` | `90` |

### YAML 规则

| 文件 | 用途 |
|------|------|
| `pipeline/analysis/config/analysis_rules.yaml` | YoY/行业阈值、KPI 分组、免责声明 |
| `pipeline/ingest/config.py` | section alias 正则、parse 路径默认值 |

## 目录准备

| 路径 | 用途 |
|------|------|
| `pipeline/parse/input/` | 待解析 PDF（需自行创建） |
| `pipeline/parse/parse_result/` | MinerU 输出 |
| `report/output/` | HTML 报告输出 |

## MinerU / GPU 注意

- 无法导入 MinerU：确认在 `RE` 环境中安装 `mineru[all]`
- GPU 加速：parse 脚本默认 `--backend pipeline`，有 CUDA 时自动使用
- 解析不连库；完成后运行 ingest

## 首次验证

```bash
cp .env.example .env
python pipeline/parse/mineru_parse.py
python -m pipeline.ingest.ingest --with-relations --force
python -m pipeline.qa.cli --report-id 1 --query "2025年营业总收入是多少"
```

完整链路见 [quickstart.md](../quickstart.md)。
