# -*- coding: utf-8 -*-
"""语义缓存与澄清回流测试。"""
from __future__ import annotations

import shutil

import pytest
import yaml

from src.alignment import Aligner
from src.cache import SemanticCache, cache_version
from src.db import ONTOLOGY_DIR
from src.feedback import feedback_path, load_feedback, log_resolution, summarize
from src.loop import Answer, Clarification, QueryLoop


class TestSemanticCache:
    def test_lru_eviction_and_stats(self):
        cache = SemanticCache(maxsize=2)
        cache.put(("a",), 1)
        cache.put(("b",), 2)
        assert cache.get(("a",)) == 1              # 命中会把 a 提前
        assert cache.get(("zzz",)) is None         # 未命中
        cache.put(("c",), 3)                       # 淘汰 b
        assert ("b",) not in cache
        assert len(cache) == 2
        assert cache.stats.evictions == 1
        assert cache.stats.hit_rate == pytest.approx(0.5)   # 1 命中 / 1 未命中

    def test_key_normalizes_whitespace_and_case(self):
        cache = SemanticCache()
        k1 = cache.make_key("  8月的GMV是多少？ ", "full", "v1")
        k2 = cache.make_key("8月的gmv是多少？", "full", "v1")
        assert k1 == k2

    def test_version_changes_with_ontology_mtime(self):
        assert cache_version({"a.yaml": 1.0}, None) != cache_version({"a.yaml": 2.0}, None)

    def test_clear(self):
        cache = SemanticCache()
        cache.put(("k",), 1)
        cache.clear()
        assert len(cache) == 0


class TestCacheInLoop:
    def test_second_identical_question_hits_cache(self, conn):
        loop = QueryLoop(conn, cache=SemanticCache())
        first = loop.ask("8月的订单量是多少？")
        second = loop.ask("8月的订单量是多少？")
        assert isinstance(first, Answer) and first.value == second.value
        assert loop.cache.stats.hits == 1
        assert second is not first, "命中时应返回副本，避免调用方改坏缓存"

    def test_mutating_cached_answer_does_not_corrupt_cache(self, conn):
        loop = QueryLoop(conn, cache=SemanticCache())
        first = loop.ask("8月的订单量是多少？")
        first.text = "被调用方改坏了"
        assert loop.ask("8月的订单量是多少？").text != "被调用方改坏了"

    def test_clarification_is_never_cached(self, conn):
        loop = QueryLoop(conn, cache=SemanticCache())
        assert isinstance(loop.ask("8月的GMV是多少？"), Clarification)
        assert len(loop.cache) == 0

    def test_insufficient_is_not_cached(self, conn):
        loop = QueryLoop(conn, cache=SemanticCache())
        assert loop.ask("上个月的退货率是多少？").type == "insufficient"
        assert len(loop.cache) == 0

    def test_profile_is_part_of_the_key(self, conn):
        cache = SemanticCache()
        full = QueryLoop(conn, profile="full", cache=cache)
        ablated = QueryLoop(conn, profile="no_synonyms", cache=cache)
        assert full.ask("8月的单量是多少？").type == "answer"
        assert ablated.ask("8月的单量是多少？").type == "insufficient"
        assert cache.stats.hits == 0

    def test_ontology_change_invalidates_cache(self, conn, tmp_path):
        dst = tmp_path / "ontology"
        shutil.copytree(ONTOLOGY_DIR, dst)
        loop = QueryLoop(conn, ontology_dir=dst, cache=SemanticCache())
        loop.ask("8月的订单量是多少？")
        before = loop.version()

        learned = dst / "learned.yaml"
        data = yaml.safe_load(learned.read_text(encoding="utf-8")) or {}
        data.setdefault("metrics", {})["ProbeRatio"] = {
            "zh": "探针占比", "synonyms": [], "time_basis": "o.order_time", "table": "orders",
            "requires": ["orders"], "default_variant": "std",
            "default_rationale": "单口径",
            "variants": [{"id": "std", "zh": "探针", "expr": "COUNT(*) * 1.0 / COUNT(*)"}],
        }
        learned.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

        assert loop.version() != before, "本体变更后语义版本号必须变化"
        loop.ask("8月的订单量是多少？")                 # 重新计算（缓存已失效）
        assert loop.cache.stats.hits == 0

    def test_no_cache_by_default(self, conn):
        loop = QueryLoop(conn)
        assert loop.cache is None

    def test_realigned_question_after_reload_uses_new_metric(self, conn, tmp_path):
        """教学后立即提问：新术语应能命中（缓存不阻隔活体本体）。"""
        dst = tmp_path / "ontology"
        shutil.copytree(ONTOLOGY_DIR, dst)
        loop = QueryLoop(conn, ontology_dir=dst, cache=SemanticCache())
        assert loop.ask("8月的探针占比是多少？").type == "insufficient"

        learned = dst / "learned.yaml"
        data = yaml.safe_load(learned.read_text(encoding="utf-8")) or {}
        data.setdefault("metrics", {})["ProbeRatio"] = {
            "zh": "探针占比", "synonyms": [], "time_basis": "o.order_time", "table": "orders",
            "requires": ["orders"], "default_variant": "std",
            "default_rationale": "单口径",
            "variants": [{"id": "std", "zh": "探针", "expr": "COUNT(*) * 1.0 / COUNT(*)"}],
        }
        learned.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        assert loop.ask("8月的探针占比是多少？").value == pytest.approx(1.0)


class TestFeedbackLog:
    def test_resolution_writes_one_record_per_clarify_point(self, conn, tmp_path):
        log = tmp_path / "feedback.jsonl"
        loop = QueryLoop(conn, feedback_path=log)
        clar = loop.ask("最近的GMV是多少？")           # 时间 + 口径，两个澄清点
        assert isinstance(clar, Clarification) and len(clar.points) == 2
        loop.resolve(clar, {p.id: 0 for p in clar.points})

        records = load_feedback(log)
        assert len(records) == 2
        assert {r["point_id"] for r in records} == {"time", "variant"}
        assert all(r["question"] == "最近的GMV是多少？" for r in records)
        assert records[0]["chosen_label"]

    def test_auto_resolve_is_logged_with_source_marker(self, conn, tmp_path):
        loop = QueryLoop(conn, feedback_path=tmp_path / "f.jsonl")
        loop.ask("8月的GMV是多少？", auto_resolve=True)
        records = load_feedback(tmp_path / "f.jsonl")
        assert [r["source"] for r in records] == ["auto"]

    def test_no_log_written_for_unambiguous_question(self, conn, tmp_path):
        log = tmp_path / "f.jsonl"
        QueryLoop(conn, feedback_path=log).ask("8月的订单量是多少？")
        assert not log.exists()

    def test_env_override_for_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SEMANTICA_FEEDBACK_LOG", str(tmp_path / "env.jsonl"))
        assert feedback_path() == tmp_path / "env.jsonl"

    def test_logging_is_off_unless_explicitly_enabled(self, monkeypatch):
        """库代码不得默认写文件：未传 path 且无环境变量时回流关闭。"""
        monkeypatch.delenv("SEMANTICA_FEEDBACK_LOG", raising=False)
        assert feedback_path() is None
        assert log_resolution("q", "variant", "p", "标签") is None
        assert load_feedback() == []

    def test_time_payload_is_json_serializable(self, conn, tmp_path):
        """时间澄清的 payload 含 TimeRange 对象，落盘前必须可 JSON 化。"""
        loop = QueryLoop(conn, feedback_path=tmp_path / "t.jsonl")
        clar = loop.ask("最近的订单量是多少？")
        loop.resolve(clar, {"time": 0})
        records = load_feedback(tmp_path / "t.jsonl")
        assert records and isinstance(records[0]["payload"], dict)
        time_payload = records[0]["payload"]["time"]
        assert isinstance(time_payload, dict) and "label" in time_payload

    def test_broken_lines_are_skipped(self, tmp_path):
        path = tmp_path / "f.jsonl"
        log_resolution("q", "variant", "p", "标签", {"variant": "net"}, "GMV", path=path)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("{ 这不是合法 JSON\n")
        assert len(load_feedback(path)) == 1

    def test_summarize_suggests_default_variant(self, tmp_path):
        path = tmp_path / "f.jsonl"
        for _ in range(8):
            log_resolution("上个月的金额是多少？", "variant", "口径？", "净实付", {"variant": "net"},
                           "GMV", path=path)
        for _ in range(2):
            log_resolution("上个月的金额是多少？", "variant", "口径？", "毛额", {"variant": "gross"},
                           "GMV", path=path)
        summary = summarize(path=path, min_support=3)
        assert summary["total"] == 10
        assert summary["variant_preference"]["GMV"]["净实付"] == 8
        kinds = {s["kind"] for s in summary["suggestions"]}
        assert "default_variant" in kinds
        assert any("净实付" in s["suggest"] for s in summary["suggestions"])

    def test_summarize_stays_silent_below_support(self, tmp_path):
        path = tmp_path / "f.jsonl"
        for _ in range(2):
            log_resolution("q", "variant", "口径？", "实付", {"variant": "paid"}, "GMV", path=path)
        assert summarize(path=path, min_support=3)["suggestions"] == []
