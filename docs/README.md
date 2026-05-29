# 技术文档

CN Equity Report Analyzer — 上市公司 PDF 年报 → 结构化知识库 → 问答 / 分析 / HTML 报告。

## 按读者选择路径

| 读者 | 目标 | 阅读顺序 |
|------|------|----------|
| **快速上手** | 30 分钟跑通 report_id=1 | [quickstart.md](quickstart.md) → 遇错查 [operations/troubleshooting.md](operations/troubleshooting.md) |
| **开发参考** | 理解模块边界与扩展点 | [architecture.md](architecture.md) → [guides/ingestion.md](guides/ingestion.md) 或 [guides/consumption.md](guides/consumption.md) |
| **运维手册** | 部署、配置、CLI、表结构 | [operations/setup.md](operations/setup.md) → [cli-reference.md](operations/cli-reference.md) → [database.md](operations/database.md) |

## 主题地图

| 主题 | 文档 |
|------|------|
| 系统边界与模块依赖 | [architecture.md](architecture.md) |
| 幂等 / force / QA 缓存 | [architecture.md#幂等与缓存](architecture.md#幂等与缓存) |
| parse → extract → ingest | [guides/ingestion.md](guides/ingestion.md) |
| QA / analysis / report | [guides/consumption.md](guides/consumption.md) |
| golden 回归 | [guides/evaluation.md](guides/evaluation.md) |
| 环境变量与 YAML | [operations/setup.md#配置](operations/setup.md#配置) |
| 全部 CLI | [operations/cli-reference.md](operations/cli-reference.md) |
| 表结构 + 验收 SQL | [operations/database.md](operations/database.md) |

## 仓库结构

```text
pipeline/
  parse/       MinerU PDF → parse_result/
  extract/     纯计算：text/ ∥ relations/ → ExtractResult
  ingest/      写库 + embedding
  qa/          混合检索问答
  analysis/    异常检测 + 行业对标 + MD&A 解释
report/        Jinja2 静态 HTML（overview / graph / analysis）
db/            schema_base.sql + schema_kg.sql + schema_analysis.sql
docs/          本文档目录
```

## 开发迭代

修改抽取或关系规则后，推荐顺序：

1. 跑对应 golden（见 [guides/evaluation.md](guides/evaluation.md)）
2. `python -m pipeline.ingest.ingest --with-relations --force`（关系变更时）
3. 回归 QA smoke / analysis_eval
4. 重新渲染报告验证

文档约定：中文撰写；CLI 均在**项目根目录**执行（parse 脚本除外）；架构图用 mermaid。
