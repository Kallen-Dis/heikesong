# -*- coding: utf-8 -*-
"""五步闭环集成测试：澄清流程、多行结果、陷阱题、消融档位、参数化执行。"""
from __future__ import annotations

import pandas as pd
import pytest

from src.alignment import Alignment, TimeRange
from src.loop import Answer, Clarification, QueryLoop, _fmt, _fmt_rows
from src.db import run_sql


class TestFmtHelpers:
    def test_scalar_formatting(self):
        assert _fmt(None) == "无结果"
        assert _fmt(1234567) == "1,234,567"
        assert _fmt(0.1756) == "0.1756"
        assert _fmt(2.0) == "2"
        assert _fmt(float("nan")) == "无结果（空集）"

    def test_row_formatting_single_and_multi_column(self):
        one_col = pd.DataFrame({"value": ["中通快递", "圆通速递"]})
        assert _fmt_rows(one_col) == "中通快递\n圆通速递"
        two_col = pd.DataFrame({"value": ["苹果"], "metric": [406]})
        assert _fmt_rows(two_col) == "value=苹果，metric=406"

    def test_row_formatting_truncates_with_total(self):
        df = pd.DataFrame({"v": list(range(10))})
        text = _fmt_rows(df, max_rows=3)
        assert text.endswith("…（共 10 行）")

    def test_empty_result(self):
        assert _fmt_rows(pd.DataFrame()) == "无结果"


class TestClarificationFlow:
    def test_ambiguous_variant_returns_clarification(self, loop):
        out = loop.ask("8月的GMV是多少？")
        assert isinstance(out, Clarification)
        assert [p.id for p in out.points] == ["variant"]
        assert len(out.points[0].options) == 3

    def test_resolve_selects_requested_variant(self, loop, conn):
        clar = loop.ask("8月的GMV是多少？")
        ans = loop.resolve(clar, {"variant": 2})           # 净实付
        assert isinstance(ans, Answer) and ans.type == "answer"
        gold = run_sql(conn, """SELECT SUM(o.pay_amount) FILTER (WHERE o.status <> '已取消')
            FROM orders o WHERE o.order_time >= TIMESTAMP '2026-08-01'
              AND o.order_time < TIMESTAMP '2026-09-01'""").iloc[0, 0]
        assert ans.value == pytest.approx(gold)
        assert "净实付" in " ".join(ans.disclosure)

    def test_different_choices_yield_different_values(self, loop):
        gross = loop.resolve(loop.ask("8月的GMV是多少？"), {"variant": 0}).value
        net = loop.resolve(loop.ask("8月的GMV是多少？"), {"variant": 2}).value
        assert gross > net, "毛额应大于净实付"

    def test_entity_clarification_offers_brand_and_customer(self, loop):
        clar = loop.ask("8月苹果的订单量是多少？")
        assert isinstance(clar, Clarification)
        labels = [o["label"] for o in clar.points[0].options]
        assert any("品牌" in label for label in labels)
        assert any("客户" in label for label in labels)

    def test_auto_resolve_picks_first_option(self, loop):
        ans = loop.ask("8月的GMV是多少？", auto_resolve=True)
        assert isinstance(ans, Answer) and ans.type == "answer"

    def test_no_clarify_profile_never_returns_clarification(self, conn):
        plain = QueryLoop(conn, profile="no_clarify")
        out = plain.ask("8月的GMV是多少？")
        assert isinstance(out, Answer)

    def test_explicit_variant_keyword_answers_without_clarifying(self, loop):
        """用户明说口径时应直接作答（而不是再问一遍）。"""
        ans = loop.ask("8月华东区的履约超时率是多少按已签收口径")
        assert isinstance(ans, Answer) and ans.type == "answer"
        assert "已签收运单" in " ".join(ans.disclosure)

    def test_resolution_is_idempotent_on_same_object(self, loop):
        clar = loop.ask("8月的GMV是多少？")
        first = loop.resolve(clar, {"variant": 1})
        again = loop.ask("8月的GMV是多少？", auto_resolve=True)
        assert first.value > 0
        assert isinstance(again, Answer)
        # 同一问题重复提问结果稳定（确定性路线，无随机性）
        assert loop.ask("8月的GMV是多少？", auto_resolve=True).value == again.value


class TestAnswerShapes:
    def test_scalar_answer_has_no_rows(self, loop):
        ans = loop.ask("8月的订单量是多少？")
        assert ans.type == "answer" and ans.rows == []
        assert ans.value > 0

    def test_compare_returns_two_rows_in_question_order(self, loop):
        ans = loop.ask("8月华为和苹果的订单量对比")
        assert ans.type == "answer"
        assert [r["value"] for r in ans.rows] == ["华为", "苹果"]
        assert len(ans.text.splitlines()) == 2

    def test_ranking_returns_single_string(self, loop):
        ans = loop.ask("8月超时运单最多的承运商是谁？")
        assert ans.type == "answer" and isinstance(ans.value, str)

    def test_trap_returns_insufficient_without_rows(self, loop):
        ans = loop.ask("上个月华东区的退货率是多少？")
        assert ans.type == "insufficient" and ans.value is None
        assert "退货" in ans.text

    def test_unmappable_question_is_insufficient(self, loop):
        ans = loop.ask("今天天气怎么样？")
        assert ans.type == "insufficient"

    def test_pre_aligned_plan_can_be_executed_directly(self, loop, conn):
        """确定性流水线（MCP run_metric）复用同一闭环入口。"""
        a = Alignment(question="<metric:OrderCount>", metric_id="OrderCount", variant_id="all",
                      time=TimeRange(pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01"), "8月"))
        ans = loop.answer(a)
        assert isinstance(ans, Answer) and ans.type == "answer"
        assert ans.value == run_sql(conn, """SELECT COUNT(*) FROM orders
            WHERE order_time >= TIMESTAMP '2026-08-01'
              AND order_time < TIMESTAMP '2026-09-01'""").iloc[0, 0]

    def test_pre_aligned_multi_variant_without_choice_asks_back(self, loop):
        a = Alignment(question="<metric:GMV>", metric_id="GMV",
                      time=TimeRange(pd.Timestamp("2026-08-01"), pd.Timestamp("2026-09-01"), "8月"))
        ans = loop.answer(a)
        assert ans.type == "error" and "口径" in ans.text

    def test_missing_time_is_declined_not_guessed(self, loop):
        a = Alignment(question="<no-time>", metric_id="OrderCount", variant_id="all")
        ans = loop._proceed(a, auto_resolve=False)
        assert ans.type == "insufficient" and "时间" in ans.text


class TestTrustAndDisclosure:
    def test_every_answer_carries_trust_and_disclosure(self, loop):
        ans = loop.ask("8月华东区的履约超时率是多少按已签收口径")
        assert ans.type == "answer"
        assert ans.trust["数据截止"] == "2026-09-20"
        assert ans.trust["指标"] == "履约超时率" and ans.trust["空结果"] is False
        assert any("区域 = 华东" in line for line in ans.disclosure)
        assert ans.sql and "SELECT" in ans.sql

    def test_empty_window_is_marked_not_faked(self, loop):
        """窗口内无数据时必须是 NULL/空集并被标注，而不是编造 0。"""
        ans = loop.ask("2027年1月的GMV是多少净实付", auto_resolve=True)
        assert ans.type == "answer"
        assert ans.trust["空结果"] is True
        assert "无结果" in ans.text


class TestAblationProfiles:
    def test_no_synonyms_loses_colloquial_metric(self, conn):
        loop = QueryLoop(conn, profile="no_synonyms")
        ans = loop.ask("8月的单量是多少？")
        assert ans.type == "insufficient"

    def test_no_axioms_loses_delay_questions(self, conn):
        loop = QueryLoop(conn, profile="no_axioms")
        ans = loop.ask("8月的履约超时率是多少？")
        assert ans.type == "insufficient"

    def test_full_profile_answers_all_three(self, loop):
        for q in ("8月的单量是多少？", "8月的履约超时率是多少？", "8月的妥投率是多少？"):
            assert loop.ask(q, auto_resolve=True).type == "answer"
