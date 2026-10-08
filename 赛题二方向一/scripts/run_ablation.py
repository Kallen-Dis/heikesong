# -*- coding: utf-8 -*-
"""消融实验：逐个拆除构件，量化边际贡献（离线、无需 API Key、秒级完成）。

档位：
    full         全量系统（本体 + 澄清 + 验证）
    no_synonyms  去掉同义词表（只保留指标正式中文名）
    no_axioms    去掉公理与关系指标（超时率/超时数/平均时长/阈值能力）
    no_clarify   去掉澄清器（不追问、静默按第 1 选项作答）

产出：eval/ablation_<时间戳>.md
用法：python scripts/run_ablation.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import connect, run_sql
from src.loop import Clarification, QueryLoop

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "benchmark" / "ambiquery_v1.jsonl"
EVAL = ROOT / "eval"

PROFILES = {
    "full": "全量（本体 + 澄清 + 验证）",
    "no_synonyms": "去掉同义词表（只留指标正式名）",
    "no_axioms": "去掉公理/关系指标（超时率·超时数·平均时长·阈值）",
    "no_clarify": "去掉澄清器（不追问、静默作答）",
}


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


def verdict(item: dict, ans_type: str, value, gold) -> str:
    kind = item.get("compare", "manual")
    if kind == "insufficient":
        return "PASS" if ans_type == "insufficient" else "FAIL"
    if ans_type != "answer":
        return "FAIL"
    if gold is None or kind == "manual":
        return "MANUAL"
    return compare_scalar(value, gold, kind)


def main() -> None:
    items = [json.loads(l) for l in V1.read_text(encoding="utf-8").splitlines() if l.strip()]
    auto = [it for it in items if it.get("compare") != "manual"]
    clarify_items = [it["id"] for it in auto if it.get("expected_clarification")]

    conn = connect()
    print(f"消融实验：{len(auto)} 道自动判定题 × {len(PROFILES)} 个档位（离线）\n")

    results: dict[str, dict] = {}
    for prof, desc in PROFILES.items():
        loop = QueryLoop(conn, profile=prof)
        per: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        fails: list[tuple[str, str]] = []
        for it in auto:
            gold = None
            if it.get("gold_sql"):
                try:
                    gold = run_sql(conn, it["gold_sql"]).iloc[0, 0]
                except Exception:  # noqa: BLE001
                    gold = None
            ans = loop.ask(it["question"], auto_resolve=True)
            t = "clarify" if isinstance(ans, Clarification) else ans.type
            v = verdict(it, t, getattr(ans, "value", None), gold)
            per[it["category"]][1] += 1
            if v == "PASS":
                per[it["category"]][0] += 1
            else:
                fails.append((it["id"], it["question"]))
        ok = sum(a for a, _ in per.values())
        tot = sum(b for _, b in per.values())
        results[prof] = {"desc": desc, "ok": ok, "tot": tot, "per": dict(per), "fails": fails}
        print(f"[{prof:<12}] {ok}/{tot} = {ok / max(1, tot):.1%}"
              + ("" if prof == "full" else f"（相对全量 -{results['full']['ok'] - ok} 题）"))
    conn.close()

    full_ok = results["full"]["ok"]
    cats = sorted({it["category"] for it in auto})
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    md = [
        f"# 消融实验报告 · {ts}", "",
        f"题库：`benchmark/ambiquery_v1.jsonl`（自动判定 {len(auto)} 题；离线确定性执行）", "",
        "## 总体战绩", "",
        "| 档位 | 说明 | 通过率 | 相对全量损失 |", "|---|---|---|---|",
    ]
    for prof, r in results.items():
        loss = "" if prof == "full" else f"-{full_ok - r['ok']} 题"
        md.append(f"| **{prof}** | {r['desc']} | {r['ok']}/{r['tot']} = {r['ok'] / max(1, r['tot']):.1%} | {loss} |")

    md += ["", "## 分类战绩", "",
           "| 类别 | " + " | ".join(results) + " |", "|---" * (len(results) + 1) + "|"]
    for cat in cats:
        cells = [f"{results[p]['per'].get(cat, [0, 0])[0]}/{results[p]['per'].get(cat, [0, 0])[1]}"
                 for p in results]
        md.append(f"| {cat} | " + " | ".join(cells) + " |")

    md += ["", "## 结论", ""]
    for prof, r in results.items():
        if prof == "full":
            continue
        lost = full_ok - r["ok"]
        md.append(f"- **{prof}**：损失 {lost} 题（{lost / max(1, r['tot']):.1%}）——{r['desc']}的边际贡献。")
    risk = len(clarify_items)
    md += [
        "",
        f"- **no_clarify 风险敞口**：{risk}/{len(auto)} = {risk / max(1, len(auto)):.1%} 的题目"
        f"（口径/时间/实体含歧义）在无澄清模式下会**未经确认直接作答**；"
        f"本期题库标准答案恰取第 1 选项，故准确率不变；但若用户期望口径与系统默认不一致，"
        f"该比例即为潜在错误率上限。澄清器的价值 = 消除这 {risk / max(1, len(auto)):.0%} 的风险面。",
    ]

    md += ["", "## 各档位失败题清单", ""]
    for prof, r in results.items():
        if not r["fails"]:
            continue
        md.append(f"**{prof}**（{len(r['fails'])} 题）：")
        md.append("、".join(f"{i}({q[:16]}…)" for i, q in r["fails"][:20]) + ("…" if len(r["fails"]) > 20 else ""))
        md.append("")

    out = EVAL / f"ablation_{ts}.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print(f"\n报告：{out}")


if __name__ == "__main__":
    main()
