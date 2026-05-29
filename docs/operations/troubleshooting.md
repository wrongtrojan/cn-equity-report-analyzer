# 故障排查

按现象定位阶段与修复命令。

## 环境与依赖

| 现象 | 处理 |
|------|------|
| `无法导入 MinerU SDK` | Conda 环境安装 `mineru[all]` |
| `Missing required env: OPENAI_API_KEY` | `cp .env.example .env` 并填写 |
| psycopg2 连接失败 | 检查 `DATABASE_URL`、PG 服务、扩展 pgvector/pg_trgm |

## parse

| 现象 | 处理 |
|------|------|
| 找不到 `*_middle.json` | `--keep-raw` 查看 `_mineru_work` |
| 重复解析耗时过长 | 确认未误用 `--force`；检查 `meta.json` 指纹 |
| 表格在 MD 中缺失 | 确认 MinerU 版本；脚本内 `table_enable=True` |

## ingest

| 现象 | 处理 |
|------|------|
| 改了抽取规则但 DB 未变 | `python -m pipeline.ingest.ingest --force` |
| 改了 embedding 参数 | `--force` 重 ingest |
| 退出码 2 | 查看终端失败 report 列表；检查 parse_result `meta.status` |
| 仅更新 parse 产物未入库 | ingest 指纹未变时需 `--force` |

## qa

| 现象 | 处理 |
|------|------|
| 数值题答错或「未披露」 | 查 `financial_facts` 的 `item_name` / `period_label` |
| 叙述题答非所问 | 确认已 embedding；查 `text_chunks` 数量 |
| 关系题失败 | `ingest --with-relations`；查 `kg_relations` |
| smoke 关系题失败 | 部分为已知 section_keys 限制，人工核对 evidence |

## analysis / report

| 现象 | 处理 |
|------|------|
| `has no kg_entities` | `ingest --with-relations --force` |
| analysis 页无数据 | `python -m pipeline.analysis.cli.run --report-id N` |
| overview KPI 为空 | 同上，或确认 `financial_facts` 有 KPI |
| 行业基准为空 | 先 `mock_benchmark`，再 `analysis.cli.run`；确认科目名为规范化名 |
| overview 每次很慢 | 默认读 `qa_profile_cache.json`；勿加 `--refresh-qa-profile` |
| 端口被占用 | `report.cli --port 8770` 或关闭占用进程 |

## eval 未通过

| 现象 | 处理 |
|------|------|
| table_classify 非 26/26 | 改 `table_classify.py` 后 `--force` ingest 再跑 eval |
| relation_eval 失败 | 查 forbidden subject 是否误入 KG；见 database.md 负例 SQL |
| analysis_eval 失败 | 重跑 mock_benchmark + analysis run |

## 日志与 SQL 快查

```sql
SELECT id, report_year, parse_status FROM reports;
SELECT 'facts', COUNT(*) FROM financial_facts WHERE report_id = 1
UNION ALL SELECT 'chunks', COUNT(*) FROM text_chunks WHERE report_id = 1
UNION ALL SELECT 'kg_relations', COUNT(*) FROM kg_relations WHERE report_id = 1;
```

更多验收 SQL：[database.md#验收-sql](database.md#验收-sql)。
