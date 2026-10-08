# -*- coding: utf-8 -*-
"""澄清质量评估（离线、确定性、无需 LLM）。

对 AmbiQuery 全量题目跑语枢的对齐引擎，把产出的澄清点与题库标注逐一比对，
给出 **澄清精准率 / 召回率 / F1**，并列出漏报（该问却没问）与误报（不该问却问）。

用法：
    python scripts/eval_clarification.py [--file benchmark/ambiquery_v1.jsonl] [--quiet]

产出：eval/clarification_report.md（控制台同时打印摘要）
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.benchmark import CATEGORIES, load_items, predicted_clarifications  # noqa: E402
from src.db import connect  # noqa: E402
from src.loop import QueryLoop  # noqa: E402

EVAL_DIR = ROOT / "eval"


def main() -> int:
    ap = argparse.ArgumentParser(description="澄清质量评估（精准率/召回率/F1）")
    ap.add_argument("--file", default=None, help="题库文件（默认 benchmark/ambiquery_v1.jsonl）")
    ap.add_argument("--out", default=None, help="报告输出路径")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    items = load_items(args.file)
    conn = connect()
    loop = QueryLoop(conn)

    tp = fp = fn = 0
    strict_ok = 0                       # 澄清点集合完全一致
    per_point: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    per_cat: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    misses: list[tuple[str, str, set[str]]] = []
    alarms: list[tuple[str, str, set[str]]] = []

    for it in items:
        a = loop.aligner.align(it.question)
        pred = predicted_clarifications(a)
        want = set(it.expected_clarification)

        hit, extra, missing = pred & want, pred - want, want - pred
        tp += len(hit)
        fp += len(extra)
        fn += len(missing)
        strict_ok += int(pred == want)
        for label in want:
            per_point[label][1] += 1
            per_cat[it.category][1] += 1
        for label in pred:
            per_point[label][0] += 1
            per_cat[it.category][0] += 1
        for label in hit:
            per_point[label][2] += 1
            per_cat[it.category][2] += 1
        if missing:
            misses.append((it.id, it.question, missing))
        if extra:
            alarms.append((it.id, it.question, extra))

    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    positives = sum(1 for it in items if it.expected_clarification)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 澄清质量评估报告（AmbiQuery）",
        "",
        f"- 生成时间：{stamp}　｜　题库：{len(items)} 题（其中 {positives} 题需要澄清）",
        "- 评测对象：语枢对齐引擎（离线词典 + 公理规则，**不调用任何 LLM**）",
        "- 判定口径：澄清点集合与题库标注逐一比对；`①.variants` 表示指标口径澄清，"
        "`time.range` 表示时间范围澄清，`entity.X` 表示实体歧义澄清",
        "",
        "## 1. 总体指标",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 澄清点精准率 Precision | **{precision:.1%}**（{tp}/{tp + fp}） |",
        f"| 澄清点召回率 Recall | **{recall:.1%}**（{tp}/{tp + fn}） |",
        f"| 澄清点 F1 | **{f1:.1%}** |",
        f"| 整题澄清集合完全一致 | **{strict_ok}/{len(items)} = {strict_ok / len(items):.1%}** |",
        "",
        "## 2. 分类别",
        "",
        "| 类别 | 期望澄清点 | 实际澄清点 | 命中 | 精准率 | 召回率 |",
        "|---|---|---|---|---|---|",
    ]
    for cat, zh in CATEGORIES.items():
        pred_n, want_n, hit_n = per_cat[cat]
        p = hit_n / pred_n if pred_n else 1.0
        r = hit_n / want_n if want_n else 1.0
        lines.append(f"| {zh} | {want_n} | {pred_n} | {hit_n} | {p:.0%} | {r:.0%} |")

    lines += ["", "## 3. 分类别澄清点明细", "", "| 澄清点 | 期望 | 实际 | 命中 | 精准率 | 召回率 |",
              "|---|---|---|---|---|---|"]
    for label in sorted(per_point, key=lambda k: -per_point[k][1]):
        pred_n, want_n, hit_n = per_point[label]
        p = hit_n / pred_n if pred_n else 1.0
        r = hit_n / want_n if want_n else 1.0
        lines.append(f"| `{label}` | {want_n} | {pred_n} | {hit_n} | {p:.0%} | {r:.0%} |")

    lines += ["", "## 4. 漏报（该澄清却没澄清）", ""]
    if misses:
        for qid, q, missing in misses:
            lines.append(f"- `{qid}` {q} → 缺：{sorted(missing)}")
    else:
        lines.append("无：全部应澄清题目均已触发澄清。")

    lines += ["", "## 5. 误报（不该澄清却澄清）", ""]
    if alarms:
        for qid, q, extra in alarms:
            lines.append(f"- `{qid}` {q} → 多：{sorted(extra)}")
    else:
        lines.append("无：无误触发的澄清。")

    lines += ["", "---", "",
              "> 复现：`python scripts/eval_clarification.py`（离线，无需 API Key）"]

    out = Path(args.out) if args.out else EVAL_DIR / "clarification_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not args.quiet:
        print("澄清质量评估完成")
        print(f"  Precision {precision:.1%}  Recall {recall:.1%}  F1 {f1:.1%}")
        print(f"  整题一致 {strict_ok}/{len(items)}　漏报 {len(misses)} 题　误报 {len(alarms)} 题")
        print(f"  报告：{out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
