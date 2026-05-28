# RE 年报智能问答 — 技术文档

本目录为 **CN Equity Report Analyzer** 的完整技术文档。建议从本文索引进入各专题；数据库表结构见 [database_schema.md](database_schema.md)。

## 文档地图

按数据处理流水线组织：

```text
setup → parse → extract (text ∥ relations) → ingest → qa / report
                              ↓
                           eval（质量门禁）
```

| 阶段 | 文档 | 内容 |
|------|------|------|
| 环境与初始化 | [setup.md](setup.md) | Conda、PostgreSQL、`.env`、建库 |
| PDF 解析 | [parse.md](parse.md) | MinerU → `parse_result/` |
| 提取层总览 | [extract.md](extract.md) | `text/` 与 `relations/` 并列架构 |
| 文本分支 | [text_extract.md](text_extract.md) | 章节、表格、分类、`financial_facts` |
| 关系分支 | [relation_extract.md](relation_extract.md) | 实体关系、校验、golden |
| 结构化入库 | [ingest.md](ingest.md) | 写库、幂等、CLI、embedding |
| 数据模型 | [database_schema.md](database_schema.md) | 13 张业务表、验收 SQL、基线 |
| 混合检索问答 | [qa.md](qa.md) | 意图路由、SQL/向量/KG 检索 |
| 关系图谱 | [report.md](report.md) | HTML 图谱预览与本地服务 |
| 回归评测 | [eval.md](eval.md) | 表分类、关系、QA smoke |

## 快速开始

```bash
# 1. 环境（详见 setup.md）
cp .env.example .env
# 初始化 PostgreSQL + schema

# 2. 解析 PDF
python pipeline/parse/mineru_parse.py

# 3. 入库（结构化 + 关系 + 向量）
python -m pipeline.ingest.ingest --with-relations --force

# 4. 问答
python -m pipeline.qa.cli --report-id 1

# 5. 关系图谱（可选）
python -m report.cli --report-id 1 --serve
```

开发迭代时，修改抽取规则后须 `--force` 重入库；关系分支变更建议先跑 [eval.md](eval.md) 中的 golden。

## 代码包结构

```text
pipeline/
  env.py              # 加载项目根 .env（各模块 import 时生效）
  parse/              # MinerU PDF 解析
  extract/            # 纯计算：text/ + relations/
  ingest/             # 事务写库 + embedding
  qa/                 # 混合检索问答
report/               # 关系图谱 HTML 渲染
db/                   # schema_base.sql + schema_kg.sql
doc/                  # 本文档目录
```

## 环境变量速查

完整说明见 [setup.md §环境变量](setup.md#环境变量)。常用项：

| 变量 | 用途 |
|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 |
| `EMBED_MODEL` / `EMBED_DIM` / `CHUNK_*` | 入库 embedding |
| `OPENAI_API_KEY` / `LLM_MODEL` | QA、关系 LLM 补漏 |
| `QA_*` | 检索 Top-K、超时、会话轮数 |

模板文件：项目根 [`.env.example`](../.env.example)。

## 文档约定

- **分支文档**（`text_extract.md`、`relation_extract.md`）只写各自子包；并列关系与 `ExtractResult` 见 [extract.md](extract.md)。
- **命令行**：入库命令以 [ingest.md](ingest.md) 为准；评测命令以 [eval.md](eval.md) 为准；验收 SQL 与 report_id=1 基线以 [database_schema.md §7](database_schema.md#7-常用验收-sql) 为准。
- **路径**：CLI 均在项目根目录执行；parse 脚本为 `python pipeline/parse/mineru_parse.py`（非 `-m`）。

## 能力状态

| 能力 | 状态 |
|------|------|
| PDF 解析与结构化入库 | 已实现 |
| 财务指标 SQL 检索 + 叙述向量检索 | 已实现 |
| 知识图谱关系抽取与 QA 消费 | 已实现（`--with-relations`） |
| 关系图谱 HTML 预览 | 已实现（`report.cli`） |
| 跨报告联合问答 | 未实现 |
| 异常分析与综合报告生成 | 规划中 |
