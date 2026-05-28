#!/usr/bin/env python3
# pipeline/ingest/ingest_report.py
"""Phase1 入库入口（兼容 `python -m pipeline.ingest.ingest_report`）。"""

from __future__ import annotations

import sys

from .ingest import main

if __name__ == "__main__":
    sys.exit(main())
