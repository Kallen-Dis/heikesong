# -*- coding: utf-8 -*-
"""双人独立复核工具（交互式，离线可用，无需 API Key）。

复核人逐题检查：① 题目读得通吗；② 标准答案（gold）是否正确回答了题目；
③ 期望澄清点是否合理。每题输入一个判定 + 备注，自动存档、支持中断续跑。

用法：
    python scripts/review_benchmark.py --name 小明                # 复核全部 120 题
    python scripts/review_benchmark.py --name 小明 --only B       # 只复核 B 类
    python scripts/review_benchmark.py --name 小明 --limit 5      # 先试 5 题
    python scripts/review_benchmark.py --name 小明                # 再跑自动续跑（跳过已完成）

产出：eval/review_<name>.jsonl（每行一条判定记录）
判定：y=确认  n=有问题（必须写备注）  s=跳过（回头再看）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db import connect, run_sql

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "benchmark" / "ambiquery_v1_draft.jsonl"
OUT_DIR = ROOT / "eval"

VERDICT_MAP = {"y": "confirm", "n": "doubt", "s": "skip"}


def humanize_sql(sql: str) -> tuple[list[str], str]:
    """把 gold SQL 翻译成中文“对照清单”（供非技术复核人快速核对）。"""
    if not sql:
        return [], ""
    sel = sql.split(" FROM ", 1)[0]
    tail = sql.split(" FROM ", 1)[1] if " FROM " in sql else sql
    where = tail.split("WHERE", 1)[1] if "WHERE" in tail else ""
    upper = sql.upper()
    is_rank = "LIMIT 1" in upper
    is_group = "GROUP BY" in upper

    if "AVG(date_diff" in sel:
        metric = "平均耗时（小时）"
    elif "SUM(o.order_amount)" in sel:
        metric = "吊牌金额加总（毛额）"
    elif "SUM(o.pay_amount) FILTER" in sel:
        metric = "实付金额加总（剔除已取消）"
    elif "SUM(o.pay_amount)" in sel:
        metric = "实付金额加总"
    elif "/" in sel and "delivery_time IS NOT NULL" in sel:
        metric = "已签收运单 ÷ 全部运单（比率）"
    elif "/" in sel and "promised_time" in sel:
        metric = "超时运单 ÷ 已签收运单（比率）"
    elif "promised_time" in sel and "COUNT(*)" in sel:
        metric = "超时运单计数（条数）"
    elif "COUNT(*)" in sel:
        metric = "计数（条数）"
    else:
        metric = "（未识别，请直接阅读 SQL）"

    lines: list[str] = []
    if is_rank:
        lines.append(f"算法：按维度分组排名（指标：{metric}）→ 取第 1 名（结果是一个名称）")
    elif is_group:
        lines.append("算法：按维度分组列出各组（多行结果 → 人工对比大小）")
    else:
        lines.append(f"算法：{metric}")

    starts = re.findall(r">=\s*TIMESTAMP\s*'([\d-]+)'", where)
    ends = re.findall(r"<\s*TIMESTAMP\s*'([\d-]+)'", where)
    if starts and ends:
        try:
            last = (datetime.fromisoformat(ends[0]) - timedelta(days=1)).date().isoformat()
            lines.append(f"时间：{starts[0]} ～ {last}（含首尾）")
        except ValueError:
            lines.append(f"时间：{starts[0]} 起")
    elif starts:
        lines.append(f"时间：{starts[0]} 起")

    filters = [
        (r"c\.region = '([^']+)'", "地区 = {}"),
        (r"p\.brand IN \(([^)]+)\)", "品牌属于 {}"),
        (r"p\.brand = '([^']+)'", "品牌 = {}"),
        (r"p\.category = '([^']+)'", "品类 = {}"),
        (r"k\.carrier_name = '([^']+)'", "承运商 = {}"),
        (r"c\.customer_name = '([^']+)'", "指定客户 = {}"),
        (r"c\.customer_name LIKE '([^']+)'", "客户名包含 {}"),
        (r"o\.channel = '([^']+)'", "渠道 = {}"),
        (r"o\.status <> '([^']+)'", "剔除「{}」状态订单"),
        (r"s\.delivery_time IS NOT NULL", "只看已签收的运单"),
        (r"s\.delivery_time > s\.promised_time", "只看超时的运单（签收晚于承诺时间）"),
        (r"date_diff\('hour', s\.ship_time, s\.delivery_time\) > ([\d.]+)", "耗时超过 {} 小时"),
    ]
    for pat, fmt in filters:
        for m in re.finditer(pat, where):
            args = tuple(x[:-2] if x.endswith(".0") else x for x in m.groups())
            lines.append(fmt.format(*args))

    if "比率" in metric:
        hint = "0~1 之间的小数"
    elif is_rank:
        hint = "一个名称（如某快递公司 / 区域 / 品类）"
    elif is_group:
        hint = "多行数字，对比各组大小"
    elif "金额" in metric:
        hint = "金额数字（通常较大）"
    elif "耗时" in metric:
        hint = "小时数（一般几十左右）"
    else:
        hint = "整数（条数）"
    return lines, hint


def render_question(idx: int, total: int, it: dict, conn) -> None:
    """打印一道题的完整信息（题目 / 标准答案 / 中文对照清单 / 澄清点 / 备注）。"""
    print(f"\n[{idx}/{total}] {it['id']}｜{it['category']}")
    print(f"❓ 题目：{it['question']}")
    if it.get("gold_sql"):
        try:
            gold = run_sql(conn, it["gold_sql"]).iloc[0, 0]
        except Exception as e:  # noqa: BLE001
            gold = f"（SQL 执行出错：{e}）"
        print(f"📏 标准答案：{gold}")
        hlines, hint = humanize_sql(it["gold_sql"])
        print("🧭 快速对照清单（逐条核对，不用重算数字）：")
        for line in hlines:
            print(f"   · {line}")
        if hint:
            print(f"   · 量级提示：结果应为{hint}")
        print("   · 判读：题目里每个限定词（时间/地区/品牌/指标）都能对上 → y")
    else:
        print("🛑 期望行为：诚实拒绝（说\"数据不足\"），不允许编数字")
        print("   · 检查：题目问的数据（如退款/毛利/成本）确实不在本数据集里 → y")
    exp = it.get("expected_clarification") or []
    print(f"🔔 期望澄清点：{exp if exp else '无（应直接作答）'}")
    print(f"📝 出题备注：{it.get('notes', '')}")


def main() -> None:
    ap = argparse.ArgumentParser(description="AmbiQuery-120 双人独立复核")
    ap.add_argument("--name", required=True, help="复核人名字（用于存档，如：小明）")
    ap.add_argument("--only", default="", help="只复核某类（A/B/C/D/E/F）")
    ap.add_argument("--limit", type=int, default=0, help="只复核前 N 题（试跑用）")
    ap.add_argument("--preview", type=int, default=0,
                    help="预览模式：只展示前 N 题（含对照清单），不做判定直接退出")
    args = ap.parse_args()

    items = [json.loads(l) for l in DRAFT.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.only:
        items = [it for it in items if it["category"].startswith(args.only.strip().upper())]
    if args.limit:
        items = items[: args.limit]

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"review_{args.name}.jsonl"
    done: set[str] = set()
    if out.exists():
        for l in out.read_text(encoding="utf-8").splitlines():
            if l.strip():
                done.add(json.loads(l)["id"])

    todo = [it for it in items if it["id"] not in done]
    print("=" * 72)
    print(f"复核人：{args.name}｜本次待复核 {len(todo)} 题（已完成 {len(done)} 题）")
    print("判定说明：y=确认 n=有问题（写备注） s=跳过")
    print("💡 方法：不用自己重算数字（这是自建数据库，网上搜不到）；"
          "照每题下方的中文对照清单逐条核对即可。")
    print("=" * 72)

    conn = connect()

    if args.preview:
        n = min(args.preview, len(todo))
        print(f"（预览模式：展示前 {n} 题，不做判定、不记录）")
        for j, it in enumerate(todo[:n], 1):
            render_question(j, n, it, conn)
        conn.close()
        print("\n（预览结束。正式复核请运行：python scripts/review_benchmark.py --name 你的名字）")
        return

    for i, it in enumerate(todo, 1):
        render_question(i, len(todo), it, conn)

        v = input("\n判定 [y/n/s]：").strip().lower()
        while v not in VERDICT_MAP:
            v = input("请输入 y / n / s：").strip().lower()
        comment = ""
        if v == "n":
            comment = input("请写明问题（数字不对？该澄清没列？题目读不通？）：").strip()
        rec = {
            "id": it["id"], "reviewer": args.name, "verdict": VERDICT_MAP[v],
            "comment": comment, "time": datetime.now().isoformat(timespec="seconds"),
        }
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    conn.close()
    print(f"\n✅ 本次完成 {len(todo)} 题｜累计记录：{out}")
    print("   两人都完成后，运行 compare_reviews.py 生成一致性报告。")


if __name__ == "__main__":
    main()
