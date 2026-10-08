# -*- coding: utf-8 -*-
"""澄清回流：把每一次澄清交互沉淀为一条**带标签的语义样本**。

为什么重要：澄清卡不只是"打断用户"，它是平台唯一能拿到的**人类标注**——
"用户口中的这个词，实际想要的是哪个口径/实体/时间窗"。
把这些样本落盘并按频率挖掘，就能回答两类产品问题：

    「同一个词，80% 的人选了净实付」 → 该不该给它一个默认口径？
    「同一个词，每天被问 200 次」     → 该不该给它写一条口径关键词 / 同义词？

设计原则：**只收集与建议，不自动改本体**（本体变更仍需过三关校验 + 人工确认）。
"""
from __future__ import annotations

import dataclasses
import json
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .db import ONTOLOGY_DIR

ENV_PATH = "SEMANTICA_FEEDBACK_LOG"
DEFAULT_PATH = ONTOLOGY_DIR / "feedback_log.jsonl"


def feedback_path(path: Path | str | None = None) -> Path | None:
    """解析反馈日志路径；**未显式开启时返回 None（不写任何文件）**。

    开启方式：传 path，或设置环境变量 ``SEMANTICA_FEEDBACK_LOG``。
    库代码不应在调用方不知情时写文件——回流是**可选**的产品能力，不是副作用。
    """
    if path is not None:
        return Path(path)
    env = os.getenv(ENV_PATH)
    return Path(env) if env else None


def _jsonable(value: object) -> object:
    """把澄清 payload 转成可 JSON 化的结构（含 dataclass / Timestamp / 未知对象）。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@dataclass
class FeedbackRecord:
    ts: str
    question: str
    point_id: str          # variant | time | entity
    prompt: str
    chosen_label: str
    payload: dict = field(default_factory=dict)
    metric_id: str | None = None
    source: str = "loop"   # loop | cli | ui | mcp


def log_resolution(question: str, point_id: str, prompt: str, chosen_label: str,
                   payload: dict | None = None, metric_id: str | None = None,
                   source: str = "loop", path: Path | str | None = None) -> FeedbackRecord | None:
    """追加一条澄清样本（JSONL，追加写）。未开启回流时返回 None 且不写文件。"""
    target = feedback_path(path)
    if target is None:
        return None
    rec = FeedbackRecord(ts=datetime.now().isoformat(timespec="seconds"), question=question,
                         point_id=point_id, prompt=prompt, chosen_label=chosen_label,
                         payload=_jsonable(payload or {}), metric_id=metric_id, source=source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
    return rec


def load_feedback(path: Path | str | None = None) -> list[dict]:
    target = feedback_path(path)
    if target is None or not target.exists():
        return []
    out: list[dict] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue       # 坏行跳过，不影响分析
    return out


def summarize(records: list[dict] | None = None, path: Path | str | None = None,
              min_support: int = 3) -> dict:
    """聚合样本：口径偏好 / 时间窗偏好 / 实体歧义热点 / 高频问题。"""
    records = load_feedback(path) if records is None else records
    by_metric: dict[str, Counter] = defaultdict(Counter)
    variant_total: Counter = Counter()
    time_pref: Counter = Counter()
    entity_hot: Counter = Counter()
    by_question: Counter = Counter()

    for r in records:
        pid = r.get("point_id")
        label = r.get("chosen_label") or ""
        mid = r.get("metric_id") or "<unknown>"
        by_question[r.get("question", "")] += 1
        if pid == "variant":
            by_metric[mid][label] += 1
            variant_total[mid] += 1
        elif pid == "time":
            time_pref[label] += 1
        elif pid == "entity":
            entity_hot[label] += 1

    suggestions: list[dict] = []
    for mid, counter in by_metric.items():
        total = variant_total[mid]
        label, n = counter.most_common(1)[0]
        if total >= min_support and n / total >= 0.6:
            suggestions.append({
                "kind": "default_variant",
                "metric": mid,
                "suggest": label,
                "support": f"{n}/{total}",
                "reason": f"{n}/{total} 次澄清都选择了「{label}」→ 可考虑设为默认口径"
                          "（需人工确认，并同步 default_rationale）",
            })
    for label, n in time_pref.most_common(3):
        if n >= min_support:
            suggestions.append({"kind": "time_option", "suggest": label, "support": str(n),
                                "reason": f"「{label}」被选择 {n} 次 → 可考虑纳入时间默认选项或关键词"})
    for label, n in entity_hot.most_common(3):
        if n >= min_support:
            suggestions.append({"kind": "entity_hint", "suggest": label, "support": str(n),
                                "reason": f"实体歧义「{label}」出现 {n} 次 → 可在 UI 中提供更明确的引导"})

    return {
        "total": len(records),
        "variant_preference": {k: dict(v) for k, v in by_metric.items()},
        "time_preference": dict(time_pref),
        "entity_hotspots": dict(entity_hot),
        "top_questions": by_question.most_common(5),
        "suggestions": suggestions,
    }
