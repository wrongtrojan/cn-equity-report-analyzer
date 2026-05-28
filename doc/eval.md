# 回归评测

> 文档索引：[README.md](README.md)

本文汇总项目内所有 **golden 回归** 入口。修改 `table_classify`、`relation_extract` 或 QA 路由后，应跑相应评测再 `--force` 入库验收。

## 评测总览

| 评测 | 模块 | Golden 文件 | 依赖 |
|------|------|-------------|------|
| 表分类 | `table_classify_eval` | `pipeline/extract/relations/eval/golden_tables.json` | DB 中已有 `structured_tables` |
| 关系抽取 | `relation_eval` | `pipeline/extract/relations/eval/golden_relations.json` | DB 中已有 `kg_relations` |
| QA Smoke | `smoke_eval` | `pipeline/qa/eval/golden_questions.json` | 完整 ingest + embedding +（关系题需 `--with-relations`） |

## 关系分支推荐顺序

修改分类或关系抽取规则时，按以下顺序执行：

```bash
# 1. 表分类 golden（26 张关系章节表，须 26/26）
python -m pipeline.extract.relations.eval.table_classify_eval --report-id 1

# 2. 重入库（含关系）
python -m pipeline.ingest.ingest --with-relations --skip-embed --force

# 3. 关系 golden（正/负例/attrs/count）
python -m pipeline.extract.relations.eval.relation_eval --report-id 1

# 4. 图谱目测（可选）
python -m report.cli --report-id 1 --serve
```

分类未全绿 **不要** 改 relation_extract；关系 golden 未全绿不要合并。

细则见 [relation_extract.md](relation_extract.md)。

---

## 表分类评测

```bash
python -m pipeline.extract.relations.eval.table_classify_eval --report-id 1
```

| 项 | 说明 |
|----|------|
| 实现 | [`table_classify_eval.py`](../pipeline/extract/relations/eval/table_classify_eval.py) |
| Golden | [`golden_tables.json`](../pipeline/extract/relations/eval/golden_tables.json) |
| 覆盖 | report_id=1 关系相关章节 **26 张表** |
| 通过标准 | `passed == total`（基线 26/26） |

评测直接读 DB 中 `structured_tables.table_type_guess`，**不**重新跑 extract。若改了分类规则，须先 `--force` ingest 更新 `table_type_guess`。

---

## 关系抽取评测

```bash
python -m pipeline.extract.relations.eval.relation_eval --report-id 1
```

| 项 | 说明 |
|----|------|
| 实现 | [`relation_eval.py`](../pipeline/extract/relations/eval/relation_eval.py) |
| Golden | [`golden_relations.json`](../pipeline/extract/relations/eval/golden_relations.json) |
| 通过标准 | 全部用例通过（基线 9/9） |

### 用例类型

| type | 含义 |
|------|------|
| `must_exist` | subject + relation_type + object 子串必须存在 |
| `must_have_attrs` | attrs 须含指定字段（如 `ratio`） |
| `must_not_exist` | forbidden_subjects 或 forbidden_evidence 不得出现 |
| `count_range` | 某 relation_type 条数落在 [min, max] |

验收 SQL 与负例检查见 [database_schema.md §8](database_schema.md#8-知识图谱表)。

---

## QA Smoke 评测

```bash
python -m pipeline.qa.smoke_eval
python -m pipeline.qa.smoke_eval --category metric
python -m pipeline.qa.smoke_eval --output pipeline/qa/eval/smoke_results.json
python -m pipeline.qa.smoke_eval --no-auto-check
```

| 参数 | 说明 |
|------|------|
| `--golden` | 用例 JSON 路径，默认 `pipeline/qa/eval/golden_questions.json` |
| `--output` | 结果路径，默认 `pipeline/qa/eval/smoke_results.json` |
| `--category` | 只跑指定类别前缀 |
| `--no-auto-check` | 跳过关键词/min_evidence 自动检查 |

结果含 `auto_check` 字段，**须结合 `answer` / `evidence` 人工核对**。QA 能力边界见 [qa.md §能力边界](qa.md#能力边界当前实现)。

---

## report_id=1 基线

东方财富 2025 年报，在 `--with-relations --skip-embed --force` 后：

| 指标 | 数值 |
|------|------|
| golden_tables | 26/26 |
| golden_relations | 9/9 |
| sections | 579 |
| tables / tables_typed | 279 / 35 |
| financial_facts | 471 |
| kg_entities / kg_relations | 29 / 35 |
| shareholder_of | 10（均含 ratio） |
| 负例 subject | 0 |

完整 SQL 见 [database_schema.md §7](database_schema.md#7-常用验收-sql)。

---

## 相关文档

| 文档 | 说明 |
|------|------|
| [relation_extract.md](relation_extract.md) | 关系分支规则与误抽对策 |
| [text_extract.md](text_extract.md) | 文本分支与 facts |
| [ingest.md](ingest.md) | 入库与 `--force` |
| [qa.md](qa.md) | 问答流水线 |
