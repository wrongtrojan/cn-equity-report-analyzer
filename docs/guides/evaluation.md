# 回归评测

修改 `table_classify`、`relation_extract`、QA 路由或 analysis 规则后，应跑相应 golden 再 `--force` 入库验收。

## 评测总览

| 评测 | 命令 | Golden | 依赖 |
|------|------|--------|------|
| 表分类 | `python -m pipeline.extract.relations.eval.table_classify_eval --report-id 1` | `pipeline/extract/relations/eval/golden_tables.json` | DB 中 `structured_tables` |
| 关系抽取 | `python -m pipeline.extract.relations.eval.relation_eval --report-id 1` | `pipeline/extract/relations/eval/golden_relations.json` | DB 中 `kg_relations` |
| QA Smoke | `python -m pipeline.qa.smoke_eval` | `pipeline/qa/eval/golden_questions.json` | 完整 ingest + embedding |
| 分析 | `python -m pipeline.analysis.eval.analysis_eval --report-id 1` | `pipeline/analysis/eval/golden_analysis.json` | DB 中 `analysis_runs` |

## 关系分支推荐顺序

```bash
python -m pipeline.extract.relations.eval.table_classify_eval --report-id 1   # 须 26/26
python -m pipeline.ingest.ingest --with-relations --skip-embed --force
python -m pipeline.extract.relations.eval.relation_eval --report-id 1         # 须全绿
python -m pipeline.qa.smoke_eval                                              # 可选
```

分类未全绿 **不要** 改 relation_extract；关系 golden 未全绿不要合并。

## 各评测说明

### 表分类

- 读 DB 中已有 `table_type_guess`，**不**重新跑 extract
- 改分类规则后须先 `--force` ingest
- 基线：report_id=1 关系章节 **26/26**

### 关系抽取

用例类型：`must_exist`、`must_have_attrs`、`must_not_exist`、`count_range`。基线 **9/9**（或 10/10，以 golden 为准）。

### QA Smoke

```bash
python -m pipeline.qa.smoke_eval
python -m pipeline.qa.smoke_eval --category metric
python -m pipeline.qa.smoke_eval --output pipeline/qa/eval/smoke_results.json
```

结果含 `answer`、`confidence`、`auto_check`；关系题需 ingest `--with-relations`。

### 分析评测

```bash
python -m pipeline.analysis.cli.mock_benchmark --report-id 1 --seed 42
python -m pipeline.analysis.cli.run --report-id 1 --skip-llm
python -m pipeline.analysis.eval.analysis_eval --report-id 1
```

用例类型：`run_exists`、`must_flag`、`must_explain`。基线 **4/4**。

## 数据集位置

| 文件 | 用途 |
|------|------|
| `pipeline/extract/relations/eval/golden_tables.json` | 表分类期望 |
| `pipeline/extract/relations/eval/golden_relations.json` | 关系正/负例 |
| `pipeline/qa/eval/golden_questions.json` | QA smoke 问句 |
| `pipeline/analysis/eval/golden_analysis.json` | 分析 flag/解释期望 |

## report_id=1 基线

东方财富 2025，`--with-relations --skip-embed --force` 后参考值：

| 指标 | 数值 |
|------|------|
| golden_tables | 26/26 |
| sections / tables / tables_typed | 579 / 279 / 35 |
| financial_facts | 471 |
| kg_entities / kg_relations | 29 / 49 |
| analysis_eval | 4/4 |

验收 SQL 见 [operations/database.md#验收-sql](../operations/database.md#验收-sql)。
