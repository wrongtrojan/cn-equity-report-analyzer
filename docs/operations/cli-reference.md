# CLI 参考

所有命令均在 **项目根目录** 执行，除非注明。

## parse

```bash
python pipeline/parse/mineru_parse.py                    # 扫描 input/ 下 PDF
python pipeline/parse/mineru_parse.py --pdf /path/to.pdf
python pipeline/parse/mineru_parse.py --force              # 忽略缓存
python pipeline/parse/mineru_parse.py --out /path/to/out
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--lang` | `ch` | 文档语言 |
| `--backend` | `pipeline` | MinerU 后端 |
| `--parse-method` | `auto` | `auto` / `txt` / `ocr` |
| `--keep-raw` | 关 | 保留 `_mineru_work/` |
| `--force` | 关 | 强制重解析 |

## ingest

```bash
python -m pipeline.ingest.ingest
python -m pipeline.ingest.ingest --force
python -m pipeline.ingest.ingest --with-relations --force
python -m pipeline.ingest.ingest --with-relations --refine-text-relations --force
python -m pipeline.ingest.ingest --skip-embed --force
python -m pipeline.ingest.ingest --parse-root /path/to/parse_result
```

退出码：`0` 成功，`2` 部分失败。

## qa

```bash
python -m pipeline.qa.cli --report-id 1
python -m pipeline.qa.cli --report-id 1 --query "问句" --json
python -m pipeline.qa.smoke_eval
python -m pipeline.qa.smoke_eval --category metric --output pipeline/qa/eval/smoke_results.json
```

REPL：`/report`, `/report <id>`, `/history`, `/clear`, `/help`, `/exit`

## analysis

```bash
python -m pipeline.analysis.cli.mock_benchmark --report-id 1 --seed 42
python -m pipeline.analysis.cli.run --report-id 1
python -m pipeline.analysis.cli.run --report-id 1 --skip-llm
python -m pipeline.analysis.eval.analysis_eval --report-id 1
```

## extract eval

```bash
python -m pipeline.extract.relations.eval.table_classify_eval --report-id 1
python -m pipeline.extract.relations.eval.relation_eval --report-id 1
```

## report

```bash
python -m report.cli --report-id 1 --mode all --serve
python -m report.cli --report-id 1 --mode overview
python -m report.cli --report-id 1 --mode graph
python -m report.cli --report-id 1 --mode analysis
python -m report.cli --report-id 1 --mode all --refresh-analysis
python -m report.cli --report-id 1 --mode overview --refresh-qa-profile
python -m report.cli --report-id 1 --mode overview --skip-qa-profile
python -m report.cli --report-id 1 --mode all --serve --host 127.0.0.1 --port 8765
python -m report.cli --report-id 1 --mode all --output-dir /path/to/out
```

| 参数 | 说明 |
|------|------|
| `--mode` | `overview` / `graph` / `analysis` / `all`（默认 `all`） |
| `--refresh-analysis` | 渲染前跑 mock_benchmark + analysis run |
| `--refresh-qa-profile` | 强制重跑 overview QA 简介 |
| `--skip-qa-profile` | overview 用 regex，不调 QA |
| `--serve` | 渲染后启动 HTTP；`all` 默认打开 overview |

成功 stdout：`{"status": "success", "mode": "...", "html_path": "..."}`

## 典型工作流

```bash
# 全链路
python pipeline/parse/mineru_parse.py
python -m pipeline.ingest.ingest --with-relations --force
python -m pipeline.analysis.cli.mock_benchmark --report-id 1 --seed 42
python -m pipeline.analysis.cli.run --report-id 1 --skip-llm
python -m report.cli --report-id 1 --mode all --serve

# 改关系规则后
python -m pipeline.extract.relations.eval.table_classify_eval --report-id 1
python -m pipeline.ingest.ingest --with-relations --skip-embed --force
python -m pipeline.extract.relations.eval.relation_eval --report-id 1
```

详见 [guides/evaluation.md](../guides/evaluation.md)。
