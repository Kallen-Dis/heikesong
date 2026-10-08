# -*- coding: utf-8 -*-
"""五步闭环演示脚本（离线可用，无需 LLM API Key）。

演示内容：对齐过程 → 澄清卡 → 编译 SQL → 结果 → 口径披露。
用法：
    python scripts/smoke_test.py                # 自动选择澄清卡第 1 项
    python scripts/smoke_test.py --interactive  # 交互模式：自己回答澄清卡
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import connect
from src.loop import Clarification, QueryLoop

CASES = [
    ("口径澄清：金额三选一", "8月的金额是多少？"),
    ("双口径澄清：超时率", "上个月的履约超时率是多少？"),
    ("时间模糊：最近=？", "最近的订单量是多少？"),
    ("实体歧义：苹果是谁?", "8月苹果的订单量是多少？"),
    ("复合排名：多跳关系", "8月超时运单最多的承运商是谁？"),
    ("阈值类：超过 N 小时", "8月从发货到签收超过72小时的运单有多少？"),
    ("多品牌对比", "8月苹果和华为的订单量对比"),
    ("陷阱题：不瞎编", "上个月华东区的退货率是多少？"),
]


def print_clarification(c: Clarification) -> None:
    print("  ┌─ 澄清卡 ─────────────────────────────")
    for p in c.points:
        print(f"  │ [{p.id}] {p.prompt}")
        for i, opt in enumerate(p.options):
            print(f"  │   {i}) {opt['label']}")
    print("  └──────────────────────────────────────")


def main() -> None:
    interactive = "--interactive" in sys.argv
    conn = connect()
    loop = QueryLoop(conn)

    print("=" * 72)
    print("语枢 Semantica · 五步闭环演示（v0 离线版）")
    print("=" * 72)

    for label, q in CASES:
        print(f"\n### {label}")
        print(f"🔍 提问：{q}")
        ans = loop.ask(q)
        if isinstance(ans, Clarification):
            print_clarification(ans)
            if interactive:
                choices = {}
                for p in ans.points:
                    raw = input(f"  请选择 [{p.id}] 的选项编号（直接回车=0）：").strip()
                    choices[p.id] = int(raw) if raw.isdigit() else 0
            else:
                choices = {p.id: 0 for p in ans.points}
                print("  →（演示：自动选择每个澄清点的第 1 项）")
            ans = loop.resolve(ans, choices)

        if ans.type == "answer":
            print(f"🧩 编译 SQL：\n{ans.sql}")
            print(f"✅ 结果：{ans.text}")
            print("📎 口径披露：")
            for line in ans.disclosure:
                print(f"   · {line}")
        elif ans.type == "insufficient":
            print(f"🛑 {ans.text}")
        else:
            print(f"⚠️ {ans.text}")

    conn.close()
    print("\n" + "=" * 72)
    print("演示结束。下一站：python scripts/pre_experiment.py（预实验）")


if __name__ == "__main__":
    main()
