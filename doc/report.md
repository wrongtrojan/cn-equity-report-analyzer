# 关系图谱预览

> 文档索引：[README.md](README.md)

`report` 模块将已入库的知识图谱（`kg_entities` / `kg_relations`）渲染为 **静态 HTML 页面**，支持按关系类型 Tab 切换子图，并可在本地启动 HTTP 服务预览。

**前置条件**：须先执行 `python -m pipeline.ingest.ingest --with-relations` 写入 KG 数据。关系抽取规则见 [relation_extract.md](relation_extract.md)。

## 模块结构

```text
report/
  cli.py              # CLI：渲染 + 可选 --serve
  data_provider.py    # 从 PostgreSQL 加载图谱 payload
  templates/
    report.html.j2    # 页面模板
  static/             # 前端资源（复制到输出目录）
  output/
    report_{id}/      # 默认输出
      index.html
      static/
```

## 命令行

```bash
# 渲染 HTML（默认输出 report/output/report_1/index.html）
python -m report.cli --report-id 1

# 指定输出目录
python -m report.cli --report-id 1 --output-dir /tmp/graph_report

# 渲染后启动本地 HTTP 服务
python -m report.cli --report-id 1 --serve
python -m report.cli --report-id 1 --serve --host 127.0.0.1 --port 8765
```

| 参数 | 说明 |
|------|------|
| `--report-id` | 必填，对应 `reports.id` |
| `--output-dir` | 输出根目录；默认 `report/output/report_{id}/` |
| `--serve` | 渲染完成后启动静态文件服务 |
| `--host` | 默认 `127.0.0.1` |
| `--port` | 默认 `8765`；若被占用会自动尝试后续端口 |

成功时 stdout 输出 JSON：`{"status": "success", "html_path": "..."}`。

## 页面功能

- **按关系类型分 Tab**：`shareholder_of`、`actual_controller_of`、`executive_of`、`director_of`、`subsidiary_of`、`invest_in`、`related_party_of`、`transaction_with`
- **节点着色**：公司 / 人 / 机构 / 子公司（见 `data_provider.ENTITY_COLORS`）
- **边标签**：中文关系名 + attrs（如持股比例 `ratio`）
- **统计摘要**：实体数、边数、各 relation_type 计数

数据来源：[`data_provider.fetch_graph_payload()`](../report/data_provider.py)。

## 故障排查

| 现象 | 处理 |
|------|------|
| `has no kg_entities; run ingest with --with-relations first` | 先 `--with-relations --force` 入库 |
| 端口被占用 | 换 `--port` 或关闭占用进程；CLI 会自动尝试 +1~+19 |
| 图谱为空或边很少 | 跑 [eval.md](eval.md) 中 relation_eval；查 `kg_relations` 计数 |
| report_id 不存在 | 确认 `reports` 表中有对应记录 |

## 与 QA 的关系

- **report**：可视化浏览全图，按类型 Tab 探索
- **qa**：`KGRetriever` 按问句关键词检索相关边，作为 LLM 证据

二者读同一套 `kg_*` 表，见 [qa.md §KG 检索](qa.md#kg-检索kgretriever)。

## 相关文档

| 文档 | 说明 |
|------|------|
| [relation_extract.md](relation_extract.md) | 关系如何写入 kg_* |
| [database_schema.md §8](database_schema.md#8-知识图谱表) | KG 表结构与验收 SQL |
| [eval.md](eval.md) | 关系 golden 回归 |
| [ingest.md](ingest.md) | `--with-relations` 入库 |
