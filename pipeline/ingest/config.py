# pipeline/ingest/config.py
from pathlib import Path
import os

INGEST_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = INGEST_DIR.parent
PARSE_RESULT_DIR = PIPELINE_DIR / "parse" / "parse_result"
PARSE_INPUT_DIR = PIPELINE_DIR / "parse" / "input"

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://trojan@localhost:5433/re")

# embedding 配置
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))

# 切块配置
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "900"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "120"))

DEFAULT_ALIASES = [
    (r"^释义$", "glossary", 10),
    (r"第[一二三四五六七八九十百\d]+节.*重要提示", "glossary", 12),
    (r"公司简介和主要财务指标", "company_profile", 15),
    (r"^五、主要会计数据和财务指标$", "key_financials", 10),
    (r"主要会计数据和财务指标", "key_financials", 14),
    (r"分季度主要财务指标", "quarterly_financials", 18),
    (r"近两年的主要会计数据和财务指标", "bond_financials", 12),
    (r"管理层讨论与分析", "mda", 15),
    (r"第[一二三四五六七八九十百\d]+节.*公司治理", "corporate_governance", 15),
    (r"第[一二三四五六七八九十百\d]+节.*重要事项", "significant_matters", 15),
    (r"股份变动及股东情况", "shareholder_section", 18),
    (r"前.?10.*股东|前十名股东", "top10_shareholders", 18),
    (r"第[一二三四五六七八九十百\d]+节.*债券", "bond_section", 15),
    (r"第[一二三四五六七八九十百\d]+节.*财务报告", "financial_statements", 12),
    (r"董事.*监事.*高级管理人员|^六、董事", "directors_supervisors", 18),
    (r"主要控股参股公司|控股子公司|主要子公司", "subsidiaries", 18),
    (r"关联方|关联交易|重大关联交易", "related_parties", 18),
]