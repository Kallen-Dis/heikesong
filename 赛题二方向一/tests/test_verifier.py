# -*- coding: utf-8 -*-
"""验证器（信任标签）单元测试。"""
from __future__ import annotations

import pandas as pd

from src.alignment import Alignment, TimeRange
from src.db import run_sql
from src.verifier import build_trust


def _alignment(metric_id="OrderCount", **filters) -> Alignment:
    a = Alignment(question="<test>", metric_id=metric_id, variant_id="all",
                  time=TimeRange(pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01"), "2026年8月"))
    a.filters.update(filters)
    return a


def test_trust_label_fields(conn, loop):
    a = _alignment(region="华东")
    df = run_sql(conn, """SELECT COUNT(*) AS value FROM orders o
        JOIN customers c ON o.customer_id = c.customer_id
        WHERE c.region = '华东'""")
    trust = build_trust(conn, loop.aligner.metrics, a, df)
    assert trust["数据截止"] == "2026-09-20"
    assert trust["结果行数"] == 1 and trust["空结果"] is False
    assert trust["指标"] == "订单量" and trust["时间范围"] == "2026年8月"


def test_empty_result_is_flagged(conn, loop):
    df = run_sql(conn, "SELECT o.order_amount AS value FROM orders o WHERE 1 = 0")
    trust = build_trust(conn, loop.aligner.metrics, _alignment(), df)
    assert trust["结果行数"] == 0
    assert trust["空结果"] is True


def test_nan_scalar_counts_as_empty(conn, loop):
    df = run_sql(conn, "SELECT NULL::DOUBLE AS value")
    trust = build_trust(conn, loop.aligner.metrics, _alignment(), df)
    assert trust["空结果"] is True


def test_no_metric_still_reports_freshness(conn, loop):
    a = Alignment(question="<threshold>", threshold_hours=72.0,
                  time=TimeRange(pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01"), "8月"))
    df = run_sql(conn, "SELECT COUNT(*) AS value FROM shipments")
    trust = build_trust(conn, loop.aligner.metrics, a, df)
    assert trust["数据截止"] == "2026-09-20"
    assert "指标" not in trust          # 阈值题没有指标名，不应瞎填
    assert trust["置信度"]
