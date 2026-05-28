# CN Equity Report Analyzer

基于上市公司 PDF 年报的分析平台，目标能力包括：

1. **财务报表解析与检索问答** — 解析入库，支持指标与叙述类问答
2. **关联关系分析** — 股东、高管、子公司、关联方等，知识图谱与可视化
3. **经营状况分析** — 财务指标异常波动及年报解释
4. **分析报告生成** — 基本信息、关联关系、经营状况综合报告

当前版本已实现解析、结构化入库与混合检索问答；图谱、异常分析与报告生成在规划中。

## 快速开始

```bash
export DATABASE_URL="postgresql://<user>@localhost:5433/re"

# 1. 解析 PDF（见 doc/parse.md）
python pipeline/parse/mineru_parse.py

# 2. 入库
python -m pipeline.ingest.ingest_report

# 3. 问答（需配置 pipeline/qa/.env）
cp pipeline/qa/.env.example pipeline/qa/.env
python -m pipeline.qa.cli --report-id 1
```

## 文档

| 文档 | 说明 |
|------|------|
| [doc/README.md](doc/README.md) | 文档索引 |
| [doc/parse.md](doc/parse.md) | PDF 解析 |
| [doc/ingest.md](doc/ingest.md) | 结构化入库 |
| [doc/qa.md](doc/qa.md) | 混合检索问答 |
| [doc/database_schema.md](doc/database_schema.md) | 数据库表结构 |
