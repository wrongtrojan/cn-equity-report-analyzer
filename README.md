# CN Equity Report Analyzer

基于上市公司 PDF 年报的分析平台：

1. **财务报表解析与检索问答** — 解析入库，支持指标与叙述类问答
2. **关联关系分析** — 股东、高管、子公司、关联方等知识图谱
3. **经营状况分析** — 财务指标异常波动及年报解释（规划中）
4. **分析报告生成** — 综合报告（规划中）

**已实现**：PDF 解析、结构化入库、混合检索问答、知识图谱关系抽取、关系图谱 HTML 预览。

## 快速开始

```bash
cp .env.example .env   # DATABASE_URL、OPENAI_API_KEY 等，见 doc/setup.md

python pipeline/parse/mineru_parse.py
python -m pipeline.ingest.ingest --with-relations --force
python -m pipeline.qa.cli --report-id 1
```

## 文档

完整文档索引：**[doc/README.md](doc/README.md)**

| 文档 | 说明 |
|------|------|
| [doc/setup.md](doc/setup.md) | 环境与数据库初始化 |
| [doc/parse.md](doc/parse.md) | PDF 解析 |
| [doc/extract.md](doc/extract.md) | 提取层（text ∥ relations） |
| [doc/ingest.md](doc/ingest.md) | 结构化入库 |
| [doc/qa.md](doc/qa.md) | 混合检索问答 |
| [doc/report.md](doc/report.md) | 关系图谱预览 |
| [doc/eval.md](doc/eval.md) | 回归评测 |
| [doc/database_schema.md](doc/database_schema.md) | 数据库表结构 |

关系图谱（需 `--with-relations` 入库）：

```bash
python -m report.cli --report-id 1 --serve
```
