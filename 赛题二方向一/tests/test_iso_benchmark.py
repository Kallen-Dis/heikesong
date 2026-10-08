# -*- coding: utf-8 -*-
"""端到端回归：语枢在 AmbiQuery 全量题库上的表现必须保持满分。

这是最贵也最重要的一道回归网——任何引擎改动只要让某题答错，这里立刻变红。
（LLM 组的对比见 scripts/run_experiment.py；本测试完全离线、结果确定。）
"""
from __future__ import annotations

import pytest

from src.benchmark import CATEGORIES, load_items, values_match
from src.db import run_sql


@pytest.fixture(scope="module")
def outcomes(conn, loop):
    items = load_items()
    result = []
    for it in items:
        ans = loop.ask(it.question, auto_resolve=True)
        if it.expected_outcome == "insufficient":
            ok = ans.type == "insufficient"
            detail = f"期望数据不足，实得 {ans.type}"
        elif ans.type != "answer":
            ok, detail = False, f"未得到答案（{ans.type}）"
        else:
            gold = run_sql(conn, it.gold_sql).iloc[0, 0]
            ok = values_match(ans.value, gold)
            detail = f"值不符：{ans.value!r} vs gold {gold!r}"
        result.append((it, ok, detail))
    return result


@pytest.mark.slow
def test_no_regressions_on_full_benchmark(outcomes):
    failures = [f"{it.id} {it.question} → {detail}"
                for it, ok, detail in outcomes if not ok]
    assert not failures, f"{len(failures)} 题回归失败：\n" + "\n".join(failures)


@pytest.mark.slow
@pytest.mark.parametrize("category", list(CATEGORIES))
def test_each_category_is_perfect(outcomes, category):
    subset = [(it, ok, d) for it, ok, d in outcomes if it.category == category]
    bad = [it.id for it, ok, _ in subset if not ok]
    assert not bad, f"{CATEGORIES[category]} 存在失败题：{bad}"
