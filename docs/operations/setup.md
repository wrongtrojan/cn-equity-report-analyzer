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

## PostgreSQL 安装与启动

> RE **不会**自动安装或启动 PostgreSQL。`ingest` / `qa` / `analysis` / `report` 仅通过 `DATABASE_URL` 连接已有实例；连不上库时请先确认 **PostgreSQL 服务已在运行**。

### 首次 vs 日常

| 场景 | 要做的事 |
|------|----------|
| **项目伊始（一次性）** | 安装 PostgreSQL → 安装扩展 → 启动服务 → 建库 → 跑 schema 脚本 → 配置 `.env` |
| **日常开发** | 确认服务已启动 → `psql "$DATABASE_URL" -c "SELECT 1"` 通过后，再跑 pipeline |

WSL / Linux 重启后，PostgreSQL **通常不会自动运行**，需手动启动（除非你已配置 systemd 开机自启）。

### 安装（Ubuntu / WSL 示例）

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
# pgvector：按发行版安装 postgresql-16-pgvector，或从源码/官方仓库安装
```

版本须 **16+**。扩展 **pgvector**（向量检索）、**pg_trgm**（`schema_base.sql` 会 `CREATE EXTENSION`）须在实例中可用。

`.env.example` 默认端口为 **5433**（非 PostgreSQL 默认 5432），表示「按你本机实际实例修改 `DATABASE_URL`」——端口、用户名、库名须与安装一致。

### 启动与停止

```bash
# 常见（apt 安装 + systemd）
sudo service postgresql start
sudo service postgresql status

# 或
sudo systemctl start postgresql
sudo systemctl enable postgresql   # 可选：开机自启
```

若使用自定义端口（如 5433），请确认 `postgresql.conf` / `pg_hba.conf` 已配置，并与 `.env` 中 `DATABASE_URL` 一致。

### 连通性检查

在项目根目录、已 `cp .env.example .env` 且填写 `DATABASE_URL` 后：

```bash
psql "$DATABASE_URL" -c "SELECT 1"
```

返回一行 `1` 表示服务可达。失败常见原因：服务未启动、端口/用户/库名错误、WSL 未启动 PostgreSQL。

### 建库（一次性）

服务已启动且 `psql` 能连上实例后：

```bash
createdb -h localhost -p 5433 -U trojan re   # 主机/端口/用户按本机调整
```

## 数据库初始化

在项目根目录执行（**须已建库且 `psql "$DATABASE_URL" -c "SELECT 1"` 成功**）：

```bash
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
psql "$DATABASE_URL" -c "SELECT 1"    # 确认 PostgreSQL 已启动
python pipeline/parse/mineru_parse.py
python -m pipeline.ingest.ingest --with-relations --force
python -m pipeline.qa.cli --report-id 1 --query "2025年营业总收入是多少"
```

完整链路见 [quickstart.md](../quickstart.md)。
