# -*- coding: utf-8 -*-
"""DuckDB 连接与元信息工具、SQL 安全执行/渲染工具。"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "warehouse.duckdb"
ONTOLOGY_DIR = ROOT / "ontology"


def connect(db_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    path = Path(db_path) if db_path else DB_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"未找到数据仓库 {path}，请先运行: python data/generate_data.py")
    return duckdb.connect(str(path), read_only=True)


def run_sql(conn: duckdb.DuckDBPyConnection, sql: str,
            params: Sequence | None = None) -> pd.DataFrame:
    """执行查询并返回 DataFrame。

    传 params 时走 DuckDB 的 **参数绑定**（占位符 `?`），编译产物不含任何拼接
    而来的字面量 → 注入面为零。这是与"LLM 直接拼 SQL"最重要的工程差异之一。
    """
    if params:
        return conn.execute(sql, list(params)).fetchdf()
    return conn.execute(sql).fetchdf()


def sql_literal(value: object) -> str:
    """把 Python 值渲染为 SQL 字面量（字符串中的单引号按 SQL 标准双写转义）。"""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (pd.Timestamp,)) or hasattr(value, "strftime"):
        if (getattr(value, "hour", 0), getattr(value, "minute", 0), getattr(value, "second", 0)) == (0, 0, 0):
            return f"TIMESTAMP '{value:%Y-%m-%d}'"
        return f"TIMESTAMP '{value:%Y-%m-%d %H:%M:%S}'"
    return "'" + str(value).replace("'", "''") + "'"


def render_sql(sql: str, params: Sequence | None = None) -> str:
    """把占位符 `?` 填回转义后的字面量，得到**人类可读 SQL**。

    仅用于展示与归档（UI 代码块、MCP 返回值、实验档案）；执行一律走 run_sql 的参数绑定。
    逐字符扫描并跳过单引号/双引号包裹的片段，因此不会误替换字符串里的 `?`。
    """
    values = list(params or [])
    out: list[str] = []
    i, n, used = 0, len(sql), 0
    while i < n:
        ch = sql[i]
        if ch in "'\"":  # 跳过被引号包裹的片段（含 '' 转义）
            quote, j = ch, i + 1
            while j < n:
                if sql[j] == quote:
                    if j + 1 < n and sql[j + 1] == quote:
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i:j + 1])
            i = j + 1
            continue
        if ch == "?":
            if used >= len(values):
                raise ValueError(f"占位符多于参数：{len(values)} < used {used + 1}")
            out.append(sql_literal(values[used]))
            used += 1
            i += 1
            continue
        out.append(ch)
        i += 1
    if used != len(values):
        raise ValueError(f"参数多于占位符：{len(values)} > {used}")
    return "".join(out)


def dataset_end(conn: duckdb.DuckDBPyConnection) -> pd.Timestamp:
    """数据截止日（所有相对时间表达的基准）。"""
    row = conn.execute("SELECT value FROM meta WHERE key = 'dataset_end'").fetchone()
    return pd.Timestamp(row[0])


def ddl_text(conn: duckdb.DuckDBPyConnection) -> str:
    """导出 DDL 文本（供"裸 DDL 基线"提示词使用）。"""
    tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
    parts = []
    for t in tables:
        if t == "meta":
            continue
        cols = conn.execute(f"DESCRIBE {t}").fetchall()
        lines = ",\n  ".join(f"{c[0]} {c[1]}" for c in cols)
        parts.append(f"CREATE TABLE {t} (\n  {lines}\n);")
    return "\n\n".join(parts)
