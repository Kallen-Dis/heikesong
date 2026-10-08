# -*- coding: utf-8 -*-
"""裸 DDL 基线（对照组）：把表结构直接塞给 LLM 生成 SQL。

这是"瓶颈定律"的实验对照组——代表"传统做法"：AI 直连数仓、无人管语义。
在本工程中同时服务两个场景：
    1. pre_experiment.py —— 预实验量化对比；
    2. app.py —— 路演"一键切换"演示的对照组。
"""
from __future__ import annotations

import duckdb
import yaml

from .db import ONTOLOGY_DIR, ddl_text, run_sql
from .llm import LLMClient

BASELINE_SYSTEM = ("你是 SQL 专家。根据给定的数据库表结构和问题，生成一条 DuckDB SQL。"
                   "只输出 SQL 原文，不要解释、不要代码块。")


class BaselineRunner:
    def __init__(self, conn: duckdb.DuckDBPyConnection, client: LLMClient) -> None:
        self.conn = conn
        self.client = client
        self.ddl = ddl_text(conn)

    def ask(self, question: str) -> dict:
        """返回 {"available", "sql", "value", "error"}；error 为 None 表示成功。"""
        if not self.client or not self.client.available:
            return {"available": False, "sql": "", "value": None,
                    "error": "未配置 LLM_API_KEY（.env）"}
        try:
            sql = self.client.sql(BASELINE_SYSTEM, f"数据库表结构：\n{self.ddl}\n\n问题：{question}")
        except Exception as e:
            return {"available": True, "sql": "", "value": None, "error": f"LLM 调用失败：{e}"}
        if not sql:
            return {"available": True, "sql": "", "value": None, "error": "LLM 返回空 SQL"}
        try:
            df = run_sql(self.conn, sql)
            value = df.iloc[0, 0] if len(df) and len(df.columns) else None
            return {"available": True, "sql": sql, "value": value, "error": None}
        except Exception as e:
            return {"available": True, "sql": sql, "value": None, "error": f"SQL 执行失败：{e}"}


def annotated_ddl_text(conn: duckdb.DuckDBPyConnection) -> str:
    """注释版 DDL（B 组对照）：列名附中文注释 + 表间关系清单。"""
    onto = yaml.safe_load((ONTOLOGY_DIR / "ontology.yaml").read_text(encoding="utf-8"))
    col_zh: dict[str, dict[str, str]] = {}
    for cdef in (onto.get("concepts") or {}).values():
        table = cdef.get("table")
        if not table:
            continue
        col_zh[table] = {k: (v or {}).get("zh", "") for k, v in (cdef.get("properties") or {}).items()}

    tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall() if r[0] != "meta"]
    parts: list[str] = []
    for t in tables:
        cols = conn.execute(f"DESCRIBE {t}").fetchall()
        lines = []
        for c in cols:
            zh = col_zh.get(t, {}).get(c[0], "")
            lines.append(f"{c[0]} {c[1]}" + (f"  -- {zh}" if zh else ""))
        parts.append(f"CREATE TABLE {t} (\n  " + ",\n  ".join(lines) + "\n);")

    rels = onto.get("relations") or []
    parts.append("-- 表间关系：\n" + "\n".join(
        f"-- {r['from']} 经 {r['zh']} 关联 {r['to']}：{r['join']}" for r in rels))
    return "\n\n".join(parts)
