# -*- coding: utf-8 -*-
"""题库完整性测试：schema、分类均衡、标注合法性、gold SQL 可执行。"""
from __future__ import annotations

import json

import pytest

from src.benchmark import (BENCHMARK_PATH, CATEGORIES, CLARIFY_PATTERN, dump_item,
                           load_items, normalize)
from src.db import run_sql


@pytest.fixture(scope="module")
def items():
    return load_items()


class TestSchema:
    def test_has_120_items_and_six_balanced_categories(self, items):
        assert len(items) == 120
        counts: dict[str, int] = {}
        for it in items:
            counts[it.category] = counts.get(it.category, 0) + 1
        assert counts == {c: 20 for c in CATEGORIES}

    def test_ids_unique_and_prefixed_by_category(self, items):
        ids = [it.id for it in items]
        assert len(set(ids)) == len(ids)
        for it in items:
            assert it.id.startswith(it.category[0]), f"{it.id} 与类别 {it.category} 不一致"

    def test_file_uses_normalized_field_names(self):
        raw = [json.loads(line) for line in
               BENCHMARK_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        expected = {"id", "category", "question", "expected_clarification",
                    "expected_outcome", "gold_sql", "compare", "notes"}
        for r in raw:
            assert set(r) == expected, f"{r.get('id')} 字段不规范：{sorted(r)}"

    def test_legacy_expect_key_is_still_understood(self):
        legacy = {"id": "X01", "category": "F_trap", "question": "?", "expect": "insufficient",
                  "compare": "insufficient", "gold_sql": None, "notes": ""}
        item = normalize(legacy)
        assert item.expected_outcome == "insufficient"
        assert dump_item(item)["expected_outcome"] == "insufficient"

    def test_every_question_is_non_empty_chinese(self, items):
        for it in items:
            assert it.question and any("\u4e00" <= ch <= "\u9fff" for ch in it.question)


class TestAnnotations:
    def test_clarification_labels_follow_convention(self, items):
        for it in items:
            for label in it.expected_clarification:
                assert CLARIFY_PATTERN.match(label), f"{it.id} 标注不规范：{label}"

    def test_outcome_values_are_known(self, items):
        assert {it.expected_outcome for it in items} == {"answer", "insufficient"}

    def test_trap_items_have_no_gold_sql(self, items):
        traps = [it for it in items if it.expected_outcome == "insufficient"]
        assert len(traps) == 20
        assert all(it.gold_sql is None for it in traps)

    def test_other_items_all_have_gold_sql(self, items):
        assert all(it.gold_sql for it in items if it.expected_outcome == "answer")

    def test_clarification_expectation_is_not_trivial(self, items):
        """至少 30 题需要澄清，否则澄清能力没有被真正考察。"""
        assert sum(1 for it in items if it.expected_clarification) >= 30

    @pytest.mark.slow
    def test_gold_sql_all_executable_and_scalar(self, conn, items):
        bad: list[str] = []
        for it in items:
            if not it.gold_sql:
                continue
            try:
                df = run_sql(conn, it.gold_sql)
                if df.shape[1] != 1 and it.compare != "manual":
                    bad.append(f"{it.id}: 返回 {df.shape[1]} 列")
            except Exception as e:  # noqa: BLE001
                bad.append(f"{it.id}: {e}")
        assert not bad, "gold SQL 不可执行/非标量：" + "；".join(bad)
