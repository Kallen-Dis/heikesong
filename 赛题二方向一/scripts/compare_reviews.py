# -*- coding: utf-8 -*-
"""合并两份复核记录：统计一致率，生成仲裁清单。

用法：
    python scripts/compare_reviews.py eval/review_小明.jsonl eval/review_小红.jsonl

产出：eval/review_agreement.md（一致率 + 仲裁清单 + 逐题对照）
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[str, dict]:
    recs = {}
    for l in path.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            recs[r["id"]] = r
    return recs


def main() -> None:
    if len(sys.argv) != 3:
        print("用法：python scripts/compare_reviews.py eval/review_甲.jsonl eval/review_乙.jsonl")
        sys.exit(1)
    p1, p2 = Path(sys.argv[1]), Path(sys.argv[2])
    r1, r2 = load(p1), load(p2)

    common = sorted(set(r1) & set(r2))
    agreed, disputes = [], []
    for qid in common:
        a, b = r1[qid], r2[qid]
        if a["verdict"] == "confirm" and b["verdict"] == "confirm":
            agreed.append(qid)
        elif a["verdict"] == "skip" or b["verdict"] == "skip":
            continue
        else:
            disputes.append(qid)

    only1 = sorted(set(r1) - set(r2))
    only2 = sorted(set(r2) - set(r1))
    rate = len(agreed) / max(1, len(agreed) + len(disputes))

    lines = [
        f"# 复核一致性报告 · {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
        f"- 复核人甲：`{p1.name}`（{len(r1)} 题）；复核人乙：`{p2.name}`（{len(r2)} 题）",
        f"- 共同复核：{len(common)} 题；**一致确认：{len(agreed)} 题；待仲裁：{len(disputes)} 题**",
        f"- **一致率：{rate:.1%}**（一致 / (一致 + 待仲裁)）",
        f"- 仅甲完成：{len(only1)} 题；仅乙完成：{len(only2)} 题（补齐后重跑本脚本）",
        "", "## 仲裁清单（两人结论不一致，需开会定夺）", "",
    ]
    if disputes:
        lines += ["| id | 甲判定 | 甲备注 | 乙判定 | 乙备注 |", "|---|---|---|---|---|"]
        for qid in disputes:
            a, b = r1[qid], r2[qid]
            lines.append(f"| {qid} | {a['verdict']} | {a['comment']} | {b['verdict']} | {b['comment']} |")
    else:
        lines.append("（无分歧 🎉）")

    out = ROOT / "eval" / "review_agreement.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"共同复核 {len(common)} 题｜一致 {len(agreed)}｜待仲裁 {len(disputes)}｜一致率 {rate:.1%}")
    print("报告：", out)


if __name__ == "__main__":
    main()
