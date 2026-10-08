# -*- coding: utf-8 -*-
"""预实验：语枢 vs 裸 DDL 基线（AmbiQuery 种子题）。

- 语枢侧：离线词典对齐 + 澄清自动取第 1 项 + 编译执行；
- 基线侧：裸 DDL 提示词 → LLM 直出 SQL（需要 LLM_API_KEY，无 Key 时自动跳过）。

产出：
    eval/results_v0_<时间戳>.csv  逐题明细
    eval/summary_v0.md            汇总（用于回填方案文档 ⏳ 数据点）

用法：
    python scripts/pre_experiment.py
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.baseline import BaselineRunner
from src.db import connect, run_sql
from src.llm import get_client
from src.loop import Clarification, QueryLoop

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "benchmark" / "ambiquery_seed_v0.jsonl"
EVAL_DIR = ROOT / "eval"


def load_items() -> list[dict]:
    return [json.loads(line) for line in SEED.read_text(encoding="utf-8").splitlines() if line.strip()]


def _to_float(v) -> float | None:
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


def run_ours(loop: QueryLoop, item: dict) -> tuple[str, object, str | None]:
    ans = loop.ask(item["question"], auto_resolve=True)
    if isinstance(ans, Clarification):  # 理论不可达：auto_resolve=True
        return "CLARIFY", None, None
    return ans.type, getattr(ans, "value", None), getattr(ans, "sql", None)


def verdict(item: dict, ans_type: str, value, gold) -> str:
    cmp_kind = item.get("compare", "manual")
    if cmp_kind == "insufficient":
        return "PASS" if ans_type == "insufficient" else "FAIL"
    if ans_type != "answer":
        return "FAIL"
    if gold is None:
        return "MANUAL"
    if cmp_kind in ("manual",):
        return "MANUAL"
    return compare_scalar(value, gold, cmp_kind)


def main() -> None:
    conn = connect()
    loop = QueryLoop(conn)
    client = get_client()
    runner = BaselineRunner(conn, client)
    items = load_items()

    print("=" * 72)
    print("预实验：语枢 vs 裸 DDL 基线")
    print(f"题目：{len(items)} 道（AmbiQuery 种子 v0） | 基线 LLM："
          f"{'可用 ' + client.model if client.available else '未配置（跳过基线）'}")
    print("=" * 72)

    rows = []
    for it in items:
        # gold
        gold = None
        gold_err = ""
        if it.get("gold_sql"):
            try:
                gold = run_sql(conn, it["gold_sql"]).iloc[0, 0]
            except Exception as e:
                gold_err = str(e)
        # ours
        o_type, o_val, o_sql = run_ours(loop, it)
        o_verdict = verdict(it, o_type, o_val, gold)
        # baseline（裸 DDL 对照组）
        b_verdict, b_val, b_sql = "-", None, ""
        if client.available:
            r = runner.ask(it["question"])
            b_verdict = verdict(it, "answer" if not r["error"] else "error", r["value"], gold)
            b_val = r["value"]
            b_sql = r["sql"] or (r["error"] or "")
        rows.append({
            "id": it["id"], "category": it["category"], "question": it["question"],
            "ours_type": o_type, "ours_value": str(o_val), "ours_verdict": o_verdict,
            "ours_sql": (o_sql or "").replace("\n", " ").replace("\r", " "),
            "baseline_verdict": b_verdict, "baseline_value": str(b_val) if client.available else "",
            "baseline_sql": b_sql.replace("\n", " ").replace("\r", " "),
            "gold_value": str(gold), "gold_err": gold_err,
        })
        flag = "✅" if o_verdict == "PASS" else ("🟡" if o_verdict == "MANUAL" else "❌")
        base = f" | baseline: {b_verdict}" if client.available else ""
        print(f"{flag} {it['id']:<4} {it['question'][:28]:<30} ours={o_verdict:<6}{base}")

    conn.close()

    # 汇总
    auto = [r for r in rows if r["ours_verdict"] in ("PASS", "FAIL")]
    ours_pass = sum(1 for r in auto if r["ours_verdict"] == "PASS")
    base_auto = [r for r in rows if r["baseline_verdict"] in ("PASS", "FAIL")]
    base_pass = sum(1 for r in base_auto if r["baseline_verdict"] == "PASS")

    EVAL_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = EVAL_DIR / f"results_v0_{ts}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    md_lines = [
        f"# 预实验结果（v0）· {ts}", "",
        f"- 题数：{len(items)}（自动判定 {len(auto)} / 人工复核 {len(rows) - len(auto)}）",
        f"- **语枢自动判定正确率：{ours_pass}/{len(auto)} = {ours_pass / max(1, len(auto)):.1%}**",
    ]
    if client.available:
        md_lines.append(f"- **裸 DDL 基线正确率：{base_pass}/{len(base_auto)} = {base_pass / max(1, len(base_auto)):.1%}**")
    else:
        md_lines.append("- 基线：未配置 LLM_API_KEY，未运行（配置后重跑以生成对比数据 ⏳）")
    if client.available:
        md_lines += ["", "## 分类战绩", "", "| 类别 | 语枢 | 基线 |", "|---|---|---|"]
        for cat in sorted({r["category"] for r in rows}):
            sub = [r for r in rows if r["category"] == cat]
            o_ok = sum(1 for r in sub if r["ours_verdict"] == "PASS")
            b_ok = sum(1 for r in sub if r["baseline_verdict"] == "PASS")
            tot = sum(1 for r in sub if r["ours_verdict"] != "MANUAL")
            md_lines.append(f"| {cat} | {o_ok}/{tot} | {b_ok}/{tot} |")
    md_lines += ["", "| id | 类别 | 问题 | 语枢 | 基线 |", "|---|---|---|---|---|"]
    for r in rows:
        md_lines.append(f"| {r['id']} | {r['category']} | {r['question']} | {r['ours_verdict']} | {r['baseline_verdict']} |")
    (EVAL_DIR / "summary_v0.md").write_text("\n".join(md_lines), encoding="utf-8")

    print("-" * 72)
    print(f"语枢：{ours_pass}/{len(auto)} PASS")
    if client.available:
        print(f"基线：{base_pass}/{len(base_auto)} PASS")
    print(f"明细：{csv_path}")
    print(f"汇总：{EVAL_DIR / 'summary_v0.md'}")


if __name__ == "__main__":
    main()
