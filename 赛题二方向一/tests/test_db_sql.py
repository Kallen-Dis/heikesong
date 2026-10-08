# -*- coding: utf-8 -*-
"""SQL 安全执行/渲染工具与答案比较器的单元测试。"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from src.benchmark import values_match
from src.db import render_sql, sql_literal


class TestSqlLiteral:
    def test_string_is_single_quoted(self):
        assert sql_literal("华东") == "'华东'"

    def test_single_quote_is_escaped(self):
        assert sql_literal("O'Brien") == "'O''Brien'"
        assert sql_literal("x'; DROP TABLE orders; --") == "'x''; DROP TABLE orders; --'"

    def test_numbers_and_bools(self):
        assert sql_literal(42) == "42"
        assert sql_literal(4.5) == "4.5"
        assert sql_literal(True) == "TRUE"
        assert sql_literal(None) == "NULL"

    def test_timestamp_midnight_is_compacted(self):
        assert sql_literal(pd.Timestamp("2026-08-01")) == "TIMESTAMP '2026-08-01'"
        assert sql_literal(pd.Timestamp("2026-08-01 13:05:00")) == "TIMESTAMP '2026-08-01 13:05:00'"


class TestRenderSql:
    def test_fills_placeholders_in_order(self):
        sql = "SELECT * FROM t WHERE a = ? AND b = ?"
        assert render_sql(sql, ["x", 3]) == "SELECT * FROM t WHERE a = 'x' AND b = 3"

    def test_question_mark_inside_literal_is_not_a_placeholder(self):
        sql = "SELECT '??' AS q, ? AS v"
        assert render_sql(sql, [1]) == "SELECT '??' AS q, 1 AS v"

    def test_escaped_quote_inside_literal_is_kept(self):
        sql = "SELECT ? AS a, 'it''s ok' AS b"
        assert render_sql(sql, ["中文"]) == "SELECT '中文' AS a, 'it''s ok' AS b"

    def test_mismatched_counts_raise(self):
        with pytest.raises(ValueError):
            render_sql("SELECT ?", [])
        with pytest.raises(ValueError):
            render_sql("SELECT 1", [1])


class TestValuesMatch:
    def test_numeric_relative_tolerance(self):
        assert values_match(100.0000001, 100.0)
        assert not values_match(101.0, 100.0)

    def test_zero_and_nan(self):
        assert values_match(0.0, 0.0)
        assert values_match(math.nan, None)
        assert values_match(None, None)
        assert not values_match(0.0, None)

    def test_strings_are_stripped(self):
        assert values_match(" 中通快递 ", "中通快递")
        assert not values_match("中通", "圆通")

    def test_scalar_types_mixed(self):
        assert values_match(3, 3.0)
        assert not values_match(3, "3")
