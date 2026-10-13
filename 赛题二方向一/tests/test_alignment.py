# -*- coding: utf-8 -*-
"""对齐引擎（指标/时间/实体/澄清/陷阱/消融档位/活体热加载）单元测试。"""
from __future__ import annotations

import shutil

import pandas as pd
import pytest
import yaml

from src.alignment import Aligner
from src.db import ONTOLOGY_DIR


@pytest.fixture(scope="module")
def aligner(conn):
    return Aligner(conn)


class TestTimeResolution:
    def test_explicit_month(self, aligner):
        a = aligner.align("8月的订单量是多少？")
        assert a.time.start == pd.Timestamp("2026-08-01")
        assert a.time.end_excl == pd.Timestamp("2026-09-01")

    def test_last_month_uses_dataset_end(self, aligner):
        a = aligner.align("上个月的订单量是多少？")
        assert a.time.start == pd.Timestamp("2026-08-01")
        assert a.time.end_excl == pd.Timestamp("2026-09-01")

    def test_current_month_is_capped_by_dataset_end(self, aligner):
        a = aligner.align("本月的订单量是多少？")
        assert a.time.start == pd.Timestamp("2026-09-01")
        assert a.time.end_excl == pd.Timestamp("2026-09-21")   # 数据截止 09-20

    def test_last_n_days(self, aligner):
        a = aligner.align("近7天的订单量是多少？")
        assert a.time.start == pd.Timestamp("2026-09-14")
        assert a.time.end_excl == pd.Timestamp("2026-09-21")

    def test_explicit_day_range_includes_end_day(self, aligner):
        a = aligner.align("9月1日到9月10日的订单量是多少？")
        assert a.time.end_excl == pd.Timestamp("2026-09-11")

    def test_recent_alone_is_ambiguous(self, aligner):
        a = aligner.align("最近的订单量是多少？")
        assert a.time is None
        assert [p.id for p in a.clarify] == ["time"]
        assert {o["label"] for o in a.clarify[0].options} >= {"近7天（09/14–09/20）"}


class TestMetricAlignment:
    @pytest.mark.parametrize("question,expected", [
        ("8月的妥投率是多少？", "SignedRate"),
        ("8月的履约超时率是多少？", "DelayRate"),
        ("8月的超时率是多少？", "DelayRate"),
        ("8月的超时运单数是多少？", "DelayCount"),
        ("8月的成交总额是多少？", "GMV"),
        ("8月的单量是多少？", "OrderCount"),
        ("8月的平均履约时长是多少？", "AvgFulfillmentHours"),
    ])
    def test_metric_hits(self, aligner, question, expected):
        assert aligner.align(question).metric_id == expected

    def test_longest_match_wins(self, aligner):
        """『超时运单数』不能被较短的『超时』规则吞掉。"""
        assert aligner.align("8月的超时运单数是多少？").metric_id == "DelayCount"

    def test_quantity_vs_rate_axiom_rule(self, aligner):
        assert aligner.align("8月超时了多少单？").metric_id == "DelayCount"
        assert aligner.align("8月履约超时的比例是多少？").metric_id == "DelayRate"


class TestFiltersAndRanking:
    def test_region_and_brand_filters(self, aligner):
        a = aligner.align("8月华东区小米的订单量是多少？")
        assert a.filters.get("region") == "华东"
        assert a.filters.get("brand") == "小米"

    def test_region_with_colliding_brand_asks_entity_not_filter(self, aligner):
        a = aligner.align("8月华东区苹果的订单量是多少？")
        assert a.filters.get("region") == "华东"
        assert [p.id for p in a.clarify] == ["entity"]

    def test_threshold_detection(self, aligner):
        a = aligner.align("8月从发货到签收超过72小时的运单有多少？")
        assert a.threshold_hours == 72.0

    def test_ranking_dimension_and_metric(self, aligner):
        a = aligner.align("8月超时运单最多的承运商是谁？")
        assert a.ranking == {"dim": "carrier", "metric": "DelayCount"}
        a2 = aligner.align("9月妥投率最高的区域是哪个？")
        assert a2.ranking == {"dim": "region", "metric": "SignedRate"}

    def test_region_word_inside_metric_name_is_not_a_filter(self, aligner):
        """教学指标『华东区订单占比』自带地域词，不应被拆成区域筛选。"""
        a = aligner.align("8月的华东区订单占比是多少？")
        assert a.metric_id == "EastChinaOrderRatio"
        assert "region" not in a.filters


class TestEntityAmbiguity:
    def test_brand_collides_with_customer_name_triggers_clarify(self, aligner):
        a = aligner.align("8月苹果的订单量是多少？")
        assert [p.id for p in a.clarify] == ["entity"]
        assert "brand" not in a.filters

    def test_explicit_full_customer_name_wins_without_clarify(self, aligner, conn):
        name = conn.execute(
            "SELECT customer_name FROM customers WHERE customer_name LIKE '%苹果%' "
            "AND length(customer_name) >= 6 ORDER BY customer_name LIMIT 1").fetchone()[0]
        a = aligner.align(f"8月{name}的订单量是多少？")
        assert a.clarify == []
        assert a.filters.get("customer") == name

    def test_brand_without_collision_needs_no_clarify(self, aligner):
        a = aligner.align("8月小米的订单量是多少？")
        assert a.clarify == []
        assert a.filters.get("brand") == "小米"

    def test_two_brands_mean_compare_not_ambiguity(self, aligner):
        a = aligner.align("8月苹果和OPPO的订单量对比")
        assert a.clarify == []
        assert len(a.filters.get("brands", [])) == 2

    def test_brand_order_follows_question(self, aligner):
        a = aligner.align("8月华为和苹果的订单量对比")
        assert a.filters["brands"] == ["华为", "苹果"]


class TestVariantKeywords:
    """口语里的显式口径应由本体声明的 keywords 直接识别，无需再追问。"""

    def test_net_amount_keyword(self, aligner):
        a = aligner.align("8月净实付的GMV是多少？")
        assert (a.metric_id, a.variant_id) == ("GMV", "net")
        assert a.clarify == []

    def test_delivered_only_keyword(self, aligner):
        a = aligner.align("8月华东区的履约超时率是多少按已签收口径")
        assert a.variant_id == "delivered_only" and a.clarify == []

    def test_all_shipments_keyword(self, aligner):
        a = aligner.align("8月的履约超时率是多少按全部运单口径")
        assert a.variant_id == "all_shipments" and a.clarify == []

    def test_longest_keyword_wins(self, aligner):
        """『剔除已取消』不能被更短的『含取消』抢走。"""
        a = aligner.align("8月剔除已取消的订单量是多少？")
        assert (a.metric_id, a.variant_id) == ("OrderCount", "valid")

    def test_no_keyword_still_clarifies(self, aligner):
        assert [p.id for p in aligner.align("8月的GMV是多少？").clarify] == ["variant"]


class TestUnsupported:
    @pytest.mark.parametrize("question", [
        "上个月华东区的退货率是多少？",
        "8月的毛利是多少？",
        "8月的库存有多少？",
        "8月安卓机型的订单量是多少？",
        "8月有多少客户投诉？",
    ])
    def test_trap_questions_are_declined(self, aligner, question):
        a = aligner.align(question)
        assert a.unsupported, f"{question} 应被判为数据不足"
        assert a.clarify == [], "数据不足时不应再追问澄清点"

    def test_insufficient_message_mentions_alternative(self, aligner):
        a = aligner.align("上个月华东区的退货率是多少？")
        assert "妥投率" in a.unsupported or "履约超时率" in a.unsupported

    def test_undefined_growth_metric_is_declined(self, aligner):
        a = aligner.align("最近的环比增长是多少？")
        assert a.unsupported and "未指定指标" in a.unsupported


class TestComparisonGuard:
    """含「比」但不是比较问句的说法（「占比/比例是多少」）不能被判为不支持。"""

    @pytest.mark.parametrize("question,expected", [
        ("8月的华东区订单占比是多少？", "EastChinaOrderRatio"),
        ("8月的超时比例是多少？", "DelayRate"),
    ])
    def test_ratio_phrasing_is_not_treated_as_comparison(self, aligner, question, expected):
        a = aligner.align(question)
        assert a.metric_id == expected
        assert a.unsupported is None

    def test_real_comparison_is_still_declined(self, aligner):
        a = aligner.align("8月华东的订单量比华南高多少？")
        assert a.unsupported and "不支持增长、环比或同比" in a.unsupported


class TestProfiles:
    def test_no_synonyms_profile_loses_colloquial_terms(self, conn):
        full = Aligner(conn, profile="full")
        ablated = Aligner(conn, profile="no_synonyms")
        assert full.align("8月的单量是多少？").metric_id == "OrderCount"
        assert ablated.align("8月的单量是多少？").metric_id is None
        # 正式名仍在
        assert ablated.align("8月的订单量是多少？").metric_id == "OrderCount"

    def test_no_axioms_profile_drops_axiom_metrics(self, conn):
        ablated = Aligner(conn, profile="no_axioms")
        a = ablated.align("8月的履约超时率是多少？")
        assert a.metric_id is None
        assert a.threshold_hours is None
        # 非公理指标不受影响
        assert ablated.align("8月的妥投率是多少？").metric_id == "SignedRate"


class TestLivingOntology:
    def test_new_taught_metric_is_picked_up_by_hot_reload(self, conn, tmp_path):
        dst = tmp_path / "ontology"
        shutil.copytree(ONTOLOGY_DIR, dst)
        aligner = Aligner(conn, ontology_dir=dst)
        assert aligner.align("8月的移动端订单占比是多少？").metric_id is None

        learned = dst / "learned.yaml"
        data = yaml.safe_load(learned.read_text(encoding="utf-8")) or {}
        data.setdefault("metrics", {})["MobileOrderRatio"] = {
            "zh": "移动端订单占比",
            "synonyms": [],
            "time_basis": "o.order_time",
            "table": "orders",
            "requires": ["orders"],
            "default_variant": "std",
            "default_rationale": "单口径指标，无歧义",
            "variants": [{"id": "std", "zh": "App 渠道订单占全部订单的比例",
                          "expr": "COUNT(*) FILTER (WHERE o.channel = 'App') * 1.0 / COUNT(*)"}],
        }
        learned.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                           encoding="utf-8")

        assert aligner.maybe_reload() is True
        a = aligner.align("8月的移动端订单占比是多少？")
        assert a.metric_id == "MobileOrderRatio" and a.clarify == []
        # 幂等：没有变更时不重复加载
        assert aligner.maybe_reload() is False
