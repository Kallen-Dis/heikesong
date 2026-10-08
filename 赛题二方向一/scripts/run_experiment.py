# -*- coding: utf-8 -*-
"""W2 实验矩阵：四组对比（可复现，支持多次采样取多数）。

    A：裸 DDL（现状基线）
    B：DDL + 中文列注释与表间关系（证明"加注释"不够）
    C：DDL + 本体/语义层全文入提示词（证明"把本体塞给模型"不够）
    D：语枢（本体 + 澄清 + 验证；离线确定性，单次）

LLM 三组支持 --samples N 次采样，组内取多数票（对标方案中的"统计纪律"）。

用法：
    python scripts/run_experiment.py                 # 全量，LLM 组 1 次采样
    python scripts/run_experiment.py --samples 3     # LLM 组 3 次采样取多数（W2 正式跑法）
    python scripts/run_experiment.py --limit 3       # 冒烟

产出：eval/matrix_<时间戳>.csv 与 eval/matrix_summary_<时间戳>.md
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.baseline import BASELINE_SYSTEM, annotated_ddl_text
from src.db import ONTOLOGY_DIR, connect, ddl_text, run_sql
from src.llm import get_client
from src.loop import Clarification, QueryLoop

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "benchmark" / "ambiquery_seed_v0.jsonl"
EVAL = ROOT / "eval"


def load_items() -> list[dict]:
    return [json.loads(line) for line in SEED.read_text(encoding="utf-8").splitlines() if line.strip()]


def _to_float(v):
    try:
        if hasattr(v, "item"):
            v = v.item()
        return float(v)
    except Exception:
        return None


def compare_scalar(ours, gold, kind: str) -> str:
    """与 pre_experiment.py 相同判定标准（严格一致性）。"""
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


def ontology_dump() -> str:
    parts = []
    for n in ("ontology.yaml", "metrics.yaml", "synonyms.yaml"):
        parts.append(f"# ---- {n} ----\n" + (ONTOLOGY_DIR / n).read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def build_user(group: str, q: str, ctx: dict) -> str:
    if group == "A":
        return f"数据库表结构：\n{ctx['ddl']}\n\n问题：{q}"
    if group == "B":
        return f"数据库表结构（含中文注释与表间关系）：\n{ctx['annotated']}\n\n问题：{q}"
    if group == "C":
        return (f"数据库表结构：\n{ctx['ddl']}\n\n"
                f"本体与语义层资料（术语 / 口径 / 关系，供参考）：\n{ctx['ontology']}\n\n问题：{q}")
    raise ValueError(group)


def llm_attempt(client, user: str, conn) -> dict:
    try:
        sql = client.sql(BASELINE_SYSTEM, user)
        if not sql:
            return {"sql": "", "value": None, "error": "空 SQL"}
        df = run_sql(conn, sql)
        value = df.iloc[0, 0] if len(df) and len(df.columns) else None
        return {"sql": sql, "value": value, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"sql": "", "value": None, "error": str(e)[:200]}


def main() -> None:
    ap = argparse.ArgumentParser(description="W2 实验矩阵（A/B/C/D 四组对比）")
    ap.add_argument("--samples", type=int, default=1, help="LLM 组每题采样次数（取多数票）")
    ap.add_argument("--groups", default="A,B,C", help="要跑的 LLM 组，如 A,B,C 或 A")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题（冒烟用）")
    args = ap.parse_args()
    groups = [g.strip().upper() for g in args.groups.split(",") if g.strip()]
    samples = max(1, args.samples)

    conn = connect()
    loop = QueryLoop(conn)
    client = get_client()
    items = load_items()
    if args.limit:
        items = items[: args.limit]

    ctx: dict = {"ddl": ddl_text(conn)}
    if "B" in groups:
        ctx["annotated"] = annotated_ddl_text(conn)
    if "C" in groups:
        ctx["ontology"] = ontology_dump()
    if any(g in groups for g in ("A", "B", "C")) and not client.available:
        print("❌ LLM 组需要 LLM_API_KEY（.env）")
        sys.exit(1)

    print("=" * 76)
    print(f"W2 实验矩阵 | {len(items)} 题 | 组：D(语枢) + {groups} | LLM 采样 {samples} | 模型 {client.model if client.available else '-'}")
    print("=" * 76)

    rows = []
    for it in items:
        gold = None
        if it.get("gold_sql"):
            try:
                gold = run_sql(conn, it["gold_sql"]).iloc[0, 0]
            except Exception:
                gold = None

        # D 组：语枢（确定性）
        d_ans = loop.ask(it["question"], auto_resolve=True)
        d_type = "clarify" if isinstance(d_ans, Clarification) else d_ans.type
        d_val = None if isinstance(d_ans, Clarification) else getattr(d_ans, "value", None)
        d_v = verdict(it, d_type, d_val, gold)
        row = {"id": it["id"], "category": it["category"], "question": it["question"],
               "d_verdict": d_v, "d_value": str(d_val)}
        line = f"D:{d_v}"

        # LLM 组：多次采样取多数
        for g in groups:
            attempts = []
            for _ in range(samples):
                r = llm_attempt(client, build_user(g, it["question"], ctx), conn)
                v = verdict(it, "answer" if not r["error"] else "error", r["value"], gold)
                attempts.append((v, r))
            cnt = Counter(v for v, _ in attempts)
            mv, mc = cnt.most_common(1)[0]
            rep = next((r for v, r in attempts if v == mv), attempts[0][1])
            row[f"{g.lower()}_verdict"] = mv
            row[f"{g.lower()}_agree"] = f"{mc}/{len(attempts)}"
            row[f"{g.lower()}_value"] = str(rep["value"])
            row[f"{g.lower()}_sql"] = rep["sql"].replace("\n", " ").replace("\r", " ")[:400]
            line += f" | {g}:{mv}({mc}/{len(attempts)})"
        rows.append(row)
        print(f"  {it['id']:<4} {line}")

    conn.close()

    # ---------------- 汇总 ----------------
    auto = [r for r in rows if r["d_verdict"] in ("PASS", "FAIL")]
    all_groups = ["d"] + [g.lower() for g in groups]

    def rate(col: str, sub: list[dict]) -> tuple[int, int]:
        ok = sum(1 for r in sub if r.get(f"{col}_verdict") == "PASS")
        tot = sum(1 for r in sub if r.get(f"{col}_verdict") in ("PASS", "FAIL"))
        return ok, tot

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    EVAL.mkdir(exist_ok=True)
    csv_path = EVAL / f"matrix_{ts}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    header = "| 组 | 自动判定通过率 | 采样自洽率(均值) |"
    sep = "|---|---|---|"
    md = [f"# W2 实验矩阵汇总 · {ts}", "",
          f"- 题数：{len(items)}（自动判定 {len(auto)} / 人工复核 {len(rows) - len(auto)}）",
          f"- LLM 组采样：{samples} 次/题（取多数票）；D 组为离线确定性系统", "",
          header, sep]
    for g in all_groups:
        ok, tot = rate(g, auto)
        agree = "-"
        if g != "d":
            fracs = []
            for r in rows:
                a = r.get(f"{g}_agree")
                if a:
                    x, y = a.split("/")
                    fracs.append(int(x) / int(y))
            agree = f"{sum(fracs) / len(fracs):.0%}" if fracs else "-"
        md.append(f"| {g.upper()} | {ok}/{tot} = {ok / max(1, tot):.1%} | {agree} |")

    md += ["", "## 分类战绩", "", "| 类别 | " + " | ".join(g.upper() for g in all_groups) + " |",
           "|---" * (len(all_groups) + 1) + "|"]
    for cat in sorted({r["category"] for r in rows}):
        sub = [r for r in rows if r["category"] == cat and r["d_verdict"] != "MANUAL"]
        cells = []
        for g in all_groups:
            ok, tot = rate(g, sub)
            cells.append(f"{ok}/{tot}")
        md.append(f"| {cat} | " + " | ".join(cells) + " |")

    md += ["", "## 逐题明细", "",
           "| id | 问题 | " + " | ".join(g.upper() for g in all_groups) + " |",
           "|---" * (len(all_groups) + 2) + "|"]
    for r in rows:
        cells = " | ".join(r.get(f"{g}_verdict", "-") for g in all_groups)
        md.append(f"| {r['id']} | {r['question']} | {cells} |")

    md_path = EVAL / f"matrix_summary_{ts}.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    print("-" * 76)
    for g in all_groups:
        ok, tot = rate(g, auto)
        print(f"{g.upper()} 组：{ok}/{tot} = {ok / max(1, tot):.1%}")
    print(f"明细：{csv_path}")
    print(f"汇总：{md_path}")


if __name__ == "__main__":
    main()
