# -*- coding: utf-8 -*-
"""题库机器验证：① gold SQL 可执行（非空结果或陷阱题允许空）；
② 语枢系统（auto 模式）答案与 gold 一致；③ 系统实际澄清点与 expected_clarification 一致。

默认验证终稿 benchmark/ambiquery_v1.jsonl（120 题）；也可验证草稿分片：

    python scripts/validate_draft.py                                   # 验 v1 全量 120 题
    python scripts/validate_draft.py --file draft_part1_AB.jsonl       # 验单批草稿
    python scripts/validate_draft.py --file a.jsonl,b.jsonl            # 验多文件

产出：eval/benchmark_validation.md（逐题清单 + 汇总）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import connect, run_sql
from src.loop import Clarification, QueryLoop

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmark"


def _to_float(v):
    try:
        if hasattr(v, "item"):
            v = v.item()
        return float(v)
    except Exception:
        return None


def compare_scalar(ours, gold, kind: str) -> str:
    if kind == "scalar_numeric":
        a, b = _to_float(ours), _to_float(gold)
        if a is None or b is None:
            return "FAIL"
        return "PASS" if abs(a - b) <= max(1e-9, 1e-6 * abs(b)) else "FAIL"
    if kind == "scalar_string":
        return "PASS" if str(ours).strip() == str(gold).strip() else "FAIL"
    return "MANUAL"


def expected_point_ids(item: dict) -> set[str]:
    pts: set[str] = set()
    for e in item.get("expected_clarification") or []:
        if e.startswith("entity"):
            pts.add("entity")
        elif e.startswith("time"):
            pts.add("time")
        else:  # GMV.variants / DelayRate.variants / variant
            pts.add("variant")
    return pts


def main() -> None:
    ap = argparse.ArgumentParser(description="题库机器验证")
    ap.add_argument("--file", default="ambiquery_v1.jsonl",
                    help="题库文件名（可逗号分隔多个），默认验证终稿 ambiquery_v1.jsonl")
    args = ap.parse_args()
    files = [f.strip() for f in args.file.split(",") if f.strip()]

    conn = connect()
    loop = QueryLoop(conn)

    items: list[dict] = []
    for f in files:
        for line in (BENCH / f).read_text(encoding="utf-8").splitlines():
            if line.strip():
                items.append(json.loads(line))

    print(f"共 {len(items)} 道题（{'、'.join(files)}），开始三道自检……\n")
    rows = []
    n_ok = 0
    for it in items:
        issues: list[str] = []

        # ① gold SQL 可执行 + 取值
        gold = None
        if it.get("gold_sql"):
            try:
                gold = run_sql(conn, it["gold_sql"]).iloc[0, 0]
            except Exception as e:  # noqa: BLE001
                issues.append(f"gold_sql 报错: {str(e)[:80]}")

        # ② 系统答案 vs gold（auto 模式）
        ans = loop.ask(it["question"], auto_resolve=True)
        ans_type = "clarify" if isinstance(ans, Clarification) else ans.type
        value = None if isinstance(ans, Clarification) else getattr(ans, "value", None)

        if it.get("compare") == "insufficient":
            if ans_type != "insufficient":
                issues.append(f"应为 insufficient，实际 {ans_type}")
        elif it.get("compare") == "manual":
            pass  # 人工复核项，不做机器判定
        else:
            v = compare_scalar(value, gold, it.get("compare", "scalar_numeric"))
            if v != "PASS":
                issues.append(f"答案不一致: ours={value} gold={gold}")

        # ③ 澄清点一致性（auto=False 单独跑一遍）
        raw = loop.ask(it["question"], auto_resolve=False)
        actual_pts = set()
        if isinstance(raw, Clarification):
            actual_pts = {p.id for p in raw.points}
        exp_pts = expected_point_ids(it)
        if actual_pts != exp_pts:
            issues.append(f"澄清点不符: 实际={sorted(actual_pts)} 预期={sorted(exp_pts)}")

        ok = not issues
        n_ok += ok
        rows.append((it["id"], it["question"], "✅" if ok else "❌", "；".join(issues)))
        print(f"{'✅' if ok else '❌'} {it['id']:<4} {it['question']}"
              + (f"  << {rows[-1][3]}" if issues else ""))

    conn.close()

    lines = [f"# 草稿题库机器初验报告（{n_ok}/{len(items)} 通过）", "",
             "| id | 问题 | 结果 | 问题说明 |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |")
    out = ROOT / "eval" / "benchmark_validation.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n通过 {n_ok}/{len(items)}｜报告：{out}")


if __name__ == "__main__":
    main()
