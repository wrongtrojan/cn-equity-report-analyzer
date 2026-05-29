"""Shared PostgreSQL helpers for pipeline modules."""

from __future__ import annotations

import os

import psycopg2

import pipeline.env  # noqa: F401 — load project-root .env

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://trojan@localhost:5433/re")


def connect():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


def to_pgvector(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"
