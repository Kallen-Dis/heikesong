# -*- coding: utf-8 -*-
"""语枢侧端到端自检（离线、确定性、无需 LLM）。

对 AmbiQuery 全量题目跑完整五步闭环（澄清按题库设计取第 1 口径），
与 gold SQL 结果比对，给出**按考点分类的正确率**与失败清单。

这正是"把本体交给编译器"的路线在同题库上的成绩；LLM 组（A/B/C）的对比
由 scripts/run_experiment.py 负责。

用法：
    python scripts/eval_iso.py [--file ...] [--out eval/iso_selfcheck.md] [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.benchmark import CATEGORIES, load_items, values_match  # noqa: E402
from src.db import connect, run_sql  # noqa: E402
from src.loop import QueryLoop  # noqa: E402

EVAL_DIR = ROOT / "eval"


def main() -> int:
    ap = argparse.ArgumentParser(description="语枢侧 120 题离线端到端自检")
    ap.add_argument("--file", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题（调试用）")
    args = ap.parse_args()

    items = load_items(args.file)
    if args.limit:
        items = items[: args.limit]
    conn = connect()
    loop = QueryLoop(conn)

    rows: list[dict] = []
    per_cat: dict[str, list[int]] = defaultdict(lambda: [0, 0])   # [正确, 总数]
    failures: list[tuple[str, str, str]] = []

    for it in items:
        per_cat[it.category][1] += 1
        ans = loop.ask(it.question, auto_resolve=True)
        verdict, detail = "PASS", ""
        if it.expected_outcome == "insufficient":
            if ans.type != "insufficient":
                verdict, detail = "FAIL", f"应诚实说数据不足，实际返回 {ans.type}: {ans.text[:60]}"
        elif ans.type != "answer":
            verdict, detail = "FAIL", f"未得到答案（{ans.type}）：{ans.text[:80]}"
        elif it.gold_sql:
            gold = run_sql(conn, it.gold_sql).iloc[0, 0]
            if not values_match(ans.value, gold):
                verdict, detail = "FAIL", f"结果不一致：语枢 {ans.value!r} vs gold {gold!r}"
        per_cat[it.category][0] += int(verdict == "PASS")
        if verdict == "FAIL":
            failures.append((it.id, it.question, detail))
        rows.append({
            "id": it.id, "category": it.category, "question": it.question,
            "verdict": verdict, "type": ans.type,
            "value": ans.value, "sql": ans.sql or "", "detail": detail,
        })

    total = len(rows)
    passed = sum(1 for r in rows if r["verdict"] == "PASS")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    csv_path = EVAL_DIR / f"iso_selfcheck_{datetime.now():%Y%m%d_%H%M%S}.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    lines = [
        "# 语枢侧端到端自检报告（AmbiQuery）",
        "",
        f"- 生成时间：{stamp}　｜　题库：{total} 题",
        "- 路线：语枢语义编译器（对齐 → 澄清 → 编译 → 执行 → 披露），**完全离线、结果确定**",
        "- 澄清策略：按题库设计取第 1 口径；陷阱题要求返回「数据不足」且不编造数字",
        "",
        f"## 总成绩：**{passed}/{total} = {passed / total:.1%}**",
        "",
        "| 类别 | 正确 | 总数 | 正确率 |",
        "|---|---|---|---|",
    ]
    for cat, zh in CATEGORIES.items():
        ok, n = per_cat[cat]
        if n:
            lines.append(f"| {zh} | {ok} | {n} | {ok / n:.0%} |")
    lines += ["", "## 失败清单", ""]
    if failures:
        for qid, q, detail in failures:
            lines.append(f"- `{qid}` {q} → {detail}")
    else:
        lines.append("无失败项。")
    lines += ["", "---", "", f"> 明细：`{csv_path.relative_to(ROOT)}`　｜　"
              "> 复现：`python scripts/eval_iso.py`（离线，无需 API Key）"]
    out = Path(args.out) if args.out else EVAL_DIR / "iso_selfcheck.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"语枢侧自检：{passed}/{total} = {passed / total:.1%}")
    for cat, zh in CATEGORIES.items():
        ok, n = per_cat[cat]
        if n:
            print(f"  {zh}: {ok}/{n} = {ok / n:.0%}")
    if failures:
        print(f"  失败 {len(failures)} 题：" + "、".join(qid for qid, _, _ in failures[:12])
              + ("…" if len(failures) > 12 else ""))
    print(f"  报告：{out.relative_to(ROOT)}｜明细：{csv_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
