# 快速上手

目标：在项目根目录跑通 **report_id=1**（东方财富 2025 样例）全链路。

## 前置

按顺序完成（细节见 [operations/setup.md](operations/setup.md)）：

1. **Python 环境** — [setup.md §Python 环境](operations/setup.md#python-环境)
2. **PostgreSQL 安装、启动、连通性** — [setup.md §PostgreSQL 安装与启动](operations/setup.md#postgresql-安装与启动)（**必做**；RE 不会自动拉起数据库）
3. **建库 + schema 初始化** — [setup.md §数据库初始化](operations/setup.md#数据库初始化)（项目伊始一次性）
4. **`.env` 配置** — [setup.md §配置](operations/setup.md#配置)（`DATABASE_URL`、`OPENAI_API_KEY`）
5. 确认 `pipeline/parse/parse_result/` 下已有样例解析产物，或自行放置 PDF 后执行 parse

日常跑 pipeline 前，先确认数据库在运行：

```bash
psql "$DATABASE_URL" -c "SELECT 1"
```

## 一条龙命令

```bash
cp .env.example .env          # 填写 OPENAI_API_KEY、DATABASE_URL

python pipeline/parse/mineru_parse.py
python -m pipeline.ingest.ingest --with-relations --force
python -m pipeline.qa.cli --report-id 1 --query "2025年营业总收入是多少"

python -m pipeline.analysis.cli.mock_benchmark --report-id 1 --seed 42
python -m pipeline.analysis.cli.run --report-id 1 --skip-llm

python -m report.cli --report-id 1 --mode all --serve
```

浏览器打开终端输出的 URL，默认进入 **overview** 页。

## 逐步验收（report_id=1）

| 步骤 | 命令 | 验收 |
|------|------|------|
| 0 数据库 | 见 [setup §PostgreSQL](operations/setup.md#postgresql-安装与启动) | `psql "$DATABASE_URL" -c "SELECT 1"` 返回 `1` |
| 1 解析 | `python pipeline/parse/mineru_parse.py` | `parse_result/*/meta.json` 中 `status=success` |
| 2 入库 | `python -m pipeline.ingest.ingest --with-relations --force` | 退出码 0；见下方 SQL |
| 3 问答 | `python -m pipeline.qa.cli --report-id 1 --query "…"` | 返回数值或叙述答案 |
| 4 分析 | `mock_benchmark` + `analysis.cli.run` | stdout 输出 `run_id` 与 flag 数 |
| 5 报告 | `python -m report.cli --report-id 1 --mode all --serve` | 三页 HTML 可访问 |

入库后快速检查：

```sql
SELECT 'facts' AS t, COUNT(*) FROM financial_facts WHERE report_id = 1
UNION ALL SELECT 'chunks', COUNT(*) FROM text_chunks WHERE report_id = 1
UNION ALL SELECT 'kg_relations', COUNT(*) FROM kg_relations WHERE report_id = 1;
```

完整基线与 SQL 见 [operations/database.md#验收-sql](operations/database.md#验收-sql)。

## 常用变体

```bash
# 跳过 embedding（仅结构化 + KG，QA 叙述题不可用）
python -m pipeline.ingest.ingest --with-relations --skip-embed --force

# 仅渲染单页报告
python -m report.cli --report-id 1 --mode graph --serve

# overview 跳过 QA（regex fallback，更快）
python -m report.cli --report-id 1 --mode overview --skip-qa-profile

# 强制刷新 QA 简介缓存
python -m report.cli --report-id 1 --mode overview --refresh-qa-profile
```

## 下一步

- 理解系统边界：[architecture.md](architecture.md)
- 修改规则后的回归：[guides/evaluation.md](guides/evaluation.md)
- 故障排查：[operations/troubleshooting.md](operations/troubleshooting.md)
