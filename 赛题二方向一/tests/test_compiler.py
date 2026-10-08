# -*- coding: utf-8 -*-
"""语义编译器单元测试：四种形态、按需 JOIN、参数化、安全守卫。"""
from __future__ import annotations

import pandas as pd
import pytest

from src.alignment import Alignment, TimeRange
from src.compiler import Compiler
from src.db import run_sql


@pytest.fixture(scope="module")
def metrics(conn):
    from src.alignment import Aligner

    return Aligner(conn).metrics


@pytest.fixture()
def compiler(metrics):
    return Compiler(metrics)


def _a(metric_id="OrderCount", variant="all", **kw) -> Alignment:
    a = Alignment(question="<test>", metric_id=metric_id, variant_id=variant,
                  time=TimeRange(pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01"), "2026年8月"))
    a.filters.update(kw)
    return a


class TestParameterization:
    def test_sql_has_no_inlined_literals(self, compiler):
        res = compiler.compile(_a(region="华东"))
        assert "'华东'" not in res.sql, "可执行 SQL 必须是参数化的（值不能内联）"
        assert res.sql.count("?") == len(res.params) == 3     # 起止时间 + 区域

    def test_params_are_typed_values(self, compiler):
        res = compiler.compile(_a(region="华东"))
        assert isinstance(res.params[0], pd.Timestamp)
        assert res.params[2] == "华东"

    def test_display_sql_inlines_escaped_literals(self, compiler):
        res = compiler.compile(_a(region="华东"))
        assert "TIMESTAMP '2026-08-01'" in res.sql_display
        assert "c.region = '华东'" in res.sql_display
        assert "?" not in res.sql_display

    def test_injected_value_cannot_break_out_of_literal(self, compiler):
        res = compiler.compile(_a(region="华东' OR 1=1 --"))
        assert "'华东'' OR 1=1 --'" in res.sql_display
        assert res.params[2] == "华东' OR 1=1 --"


class TestJoinAssembly:
    def test_plain_metric_only_scans_orders(self, compiler):
        res = compiler.compile(_a())
        assert "JOIN" not in res.sql, "无筛选/无跨表表达式时不应有多余 JOIN"

    def test_region_filter_adds_customers_join(self, compiler):
        assert "JOIN customers" in compiler.compile(_a(region="华东")).sql

    def test_brand_filter_adds_products_join(self, compiler):
        assert "JOIN products" in compiler.compile(_a(brand="苹果")).sql

    def test_carrier_metric_adds_shipments_and_carriers(self, compiler):
        res = compiler.compile(_a(metric_id="DelayRate", variant="delivered_only", carrier="中通快递"))
        assert "JOIN shipments" in res.sql and "JOIN carriers" in res.sql

    def test_expr_alias_is_enough_to_trigger_join(self, compiler):
        """表达式引用 c./p./k. 时自动补 JOIN（教学指标常见：地域/渠道占比）。"""
        res = compiler.compile(_a(metric_id="EastChinaOrderRatio", variant="std"))
        assert "JOIN customers" in res.sql

    def test_compare_uses_in_with_one_placeholder_per_brand(self, compiler):
        res = compiler.compile(_a(brands=["苹果", "OPPO"]))
        assert "p.brand IN (?, ?)" in res.sql
        assert res.params[-2:] == ["苹果", "OPPO"]
        assert "GROUP BY 1" in res.sql


class TestForms:
    def test_ranking_picks_top1(self, compiler):
        a = _a(metric_id="DelayCount", variant="std")
        a.ranking = {"dim": "carrier", "metric": "DelayCount"}
        res = compiler.compile(a)
        assert res.kind == "ranking"
        assert "k.carrier_name AS value" in res.sql
        assert "ORDER BY" in res.sql and "LIMIT 1" in res.sql
        assert any("排名" in line for line in res.disclosure)

    def test_threshold_supports_filters(self, compiler):
        a = _a(metric_id=None, variant=None, region="华东")
        a.threshold_hours = 72.0
        res = compiler.compile(a)
        assert res.kind == "threshold"
        assert "date_diff('hour', s.ship_time, s.delivery_time) > ?" in res.sql
        assert 72.0 in res.params
        assert any("区域 = 华东" in line for line in res.disclosure), "阈值题也应披露筛选条件"

    def test_disclosure_reports_variant_and_time_basis(self, compiler):
        res = compiler.compile(_a(metric_id="GMV", variant="net"))
        joined = " ".join(res.disclosure)
        assert "成交总额" in joined and "净实付" in joined and "按下单时间过滤" in joined

    def test_compare_disclosure_does_not_duplicate_brand_filter(self, compiler):
        disc = " ".join(compiler.compile(_a(brands=["苹果", "OPPO"])).disclosure)
        assert "对比：品牌分组（苹果、OPPO）" in disc
        assert "筛选：品牌" not in disc


class TestGuards:
    def test_multi_variant_without_variant_is_rejected(self, compiler):
        with pytest.raises(ValueError, match="必须先澄清口径"):
            compiler.compile(Alignment(question="<t>", metric_id="GMV",
                                       time=TimeRange(pd.Timestamp("2026-08-01"),
                                                      pd.Timestamp("2026-09-01"), "8月")))

    def test_unknown_variant_is_rejected(self, compiler):
        with pytest.raises(ValueError, match="不存在口径"):
            compiler.compile(_a(metric_id="GMV", variant="不存在"))

    def test_forbidden_expression_is_rejected(self, metrics):
        tampered = {**metrics, "Evil": {**metrics["OrderCount"],
                                        "variants": [{"id": "x", "zh": "恶意", "expr": "COUNT(*); DROP TABLE orders"}]}}
        with pytest.raises(ValueError, match="禁止片段"):
            Compiler(tampered).compile(_a(metric_id="Evil", variant="x"))

    def test_illegal_base_table_is_rejected(self, metrics):
        tampered = {**metrics, "Bad": {**metrics["OrderCount"], "table": "meta"}}
        with pytest.raises(ValueError, match="不在允许列表"):
            Compiler(tampered).compile(_a(metric_id="Bad", variant="all"))

    def test_missing_time_is_rejected(self, compiler):
        with pytest.raises(ValueError, match="缺少时间范围"):
            compiler.compile(Alignment(question="<t>", metric_id="OrderCount", variant_id="all"))

    def test_unknown_metric_is_rejected(self, compiler):
        with pytest.raises(KeyError):
            compiler.compile(_a(metric_id="NotExist", variant="all"))


class TestExecution:
    """编译产物必须能被参数绑定执行（端到端，非 mock）。"""

    def test_standard_query_runs(self, conn, compiler):
        res = compiler.compile(_a(region="华东"))
        df = run_sql(conn, res.sql, res.params)
        gold = run_sql(conn, """SELECT COUNT(*) AS value FROM orders o
            JOIN customers c ON o.customer_id = c.customer_id
            WHERE c.region = '华东' AND o.order_time >= TIMESTAMP '2026-08-01'
              AND o.order_time < TIMESTAMP '2026-09-01'""").iloc[0, 0]
        assert df.iloc[0, 0] == gold > 0

    def test_compare_returns_one_row_per_brand(self, conn, compiler):
        res = compiler.compile(_a(brands=["苹果", "华为"]))
        df = run_sql(conn, res.sql, res.params)
        assert sorted(df.iloc[:, 0]) == ["华为", "苹果"]
        assert len(df) == 2
