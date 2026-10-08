# -*- coding: utf-8 -*-
"""AmbiQuery 题库装载与规范化（题库字段的**单一事实来源**）。

历史字段差异（F 类陷阱题曾用 `expect` 且缺 `expected_clarification`）在此统一：

    expected_clarification: list[str]   例 ['GMV.variants', 'time.range', 'entity.苹果']
    expected_outcome:       str         answer | insufficient

所有脚本与测试都应通过本模块读取题库，避免各自解析出现口径漂移。
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = ROOT / "benchmark" / "ambiquery_v1.jsonl"

# 六类考点的中文名（报告与图表统一使用）
CATEGORIES: dict[str, str] = {
    "A_synonym": "同义词/黑话",
    "B_metric_ambiguity": "指标口径歧义",
    "C_entity_ambiguity": "实体歧义",
    "D_time": "时间口径",
    "E_multi_hop": "多跳/排名/阈值",
    "F_trap": "陷阱（应诚实说数据不足）",
}

# 题库中"期望澄清点"允许的取值形态
CLARIFY_PATTERN = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*\.variants|time\.range|entity\..+)$")


@dataclass
class Item:
    id: str
    category: str
    question: str
    expected_clarification: list[str] = field(default_factory=list)
    expected_outcome: str = "answer"          # answer | insufficient
    gold_sql: str | None = None
    compare: str = "scalar_numeric"           # scalar_numeric | scalar_string | manual | insufficient
    notes: str = ""

    @property
    def kind_zh(self) -> str:
        return CATEGORIES.get(self.category, self.category)


def normalize(raw: dict) -> Item:
    """兼容历史字段写法，输出统一的 Item。"""
    outcome = raw.get("expected_outcome")
    if not outcome:
        if raw.get("expect") == "insufficient" or raw.get("compare") == "insufficient":
            outcome = "insufficient"
        else:
            outcome = "answer"
    return Item(
        id=raw["id"],
        category=raw["category"],
        question=raw["question"],
        expected_clarification=list(raw.get("expected_clarification") or []),
        expected_outcome=outcome,
        gold_sql=raw.get("gold_sql"),
        compare=raw.get("compare") or "scalar_numeric",
        notes=raw.get("notes") or "",
    )


def load_items(path: Path | str | None = None) -> list[Item]:
    p = Path(path) if path else BENCHMARK_PATH
    with p.open(encoding="utf-8") as fh:
        return [normalize(json.loads(line)) for line in fh if line.strip()]


def dump_item(it: Item) -> dict:
    """Item → 规范化后的 JSON（用于题库归一化写回）。"""
    return {
        "id": it.id,
        "category": it.category,
        "question": it.question,
        "expected_clarification": it.expected_clarification,
        "expected_outcome": it.expected_outcome,
        "gold_sql": it.gold_sql,
        "compare": it.compare,
        "notes": it.notes,
    }


def values_match(got: object, want: object, rel: float = 1e-6) -> bool:
    """答案比较：数值按相对误差，字符串去空白，NaN/None 视为同一类"无结果"。"""
    def clean(v: object) -> object:
        if hasattr(v, "item"):
            v = v.item()
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    got, want = clean(got), clean(want)
    if got is None or want is None:
        return got is None and want is None
    if isinstance(got, (int, float)) and isinstance(want, (int, float)):
        if want == 0:
            return abs(float(got)) < rel
        return abs(float(got) - float(want)) <= rel * abs(float(want))
    if isinstance(got, str) and isinstance(want, str):
        return got.strip() == want.strip()
    return False   # 类型/语义不同（如 3 与 '3'）不得视为相等


def predicted_clarifications(alignment) -> set[str]:
    """把对齐产出的澄清点映射到题库标注口径。

    Aligner 的 ClarifyPoint.id ∈ {variant, time, entity} →
    题库标注：'{Metric}.variants' / 'time.range' / 'entity.{品牌词}'
    """
    labels: set[str] = set()
    for point in alignment.clarify:
        if point.id == "variant":
            labels.add(f"{alignment.metric_id}.variants")
        elif point.id == "time":
            labels.add("time.range")
        elif point.id == "entity":
            m = re.search(r"「([^」]+)」", point.prompt)
            labels.add(f"entity.{m.group(1)}" if m else "entity")
        else:
            labels.add(point.id)
    return labels
