# -*- coding: utf-8 -*-
"""现场教学：把一个新术语"教"给平台（活体本体生长，30 秒内生效并立即验证）。

用法：
    python scripts/teach.py "快时效占比" --desc "承诺时效不超过24小时的运单占全部运单的比例"
    python scripts/teach.py "半日达占比" --desc "..." --dry-run    # 只看草稿不落盘
    python scripts/teach.py "专区成交" --desc "..." --syn "专区销售额,专区GMV"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from src.db import connect, ddl_text
from src.llm import get_client
from src.loop import Clarification, QueryLoop
from src.ontology_pipeline import apply_metric, draft_metric, validate_metric


def main() -> None:
    ap = argparse.ArgumentParser(description="现场教学：新术语 → 指标定义 → 即刻可查")
    ap.add_argument("term", help="新术语（自然语言）")
    ap.add_argument("--desc", required=True, help="业务定义（一句话）")
    ap.add_argument("--id", dest="metric_id", help="指定英文指标 ID（默认由 LLM 生成）")
    ap.add_argument("--syn", default="", help="附加同义词（逗号分隔）")
    ap.add_argument("--dry-run", action="store_true", help="只生成草稿与校验，不写入")
    ap.add_argument("--force", action="store_true", help="校验失败或 ID 冲突时仍写入")
    args = ap.parse_args()

    conn = connect()
    loop = QueryLoop(conn)
    client = get_client()
    if not client.available:
        print("❌ 需要 LLM_API_KEY（.env）才能生成草稿")
        sys.exit(1)

    syn = [s.strip() for s in args.syn.split(",") if s.strip()]
    print(f"📚 现场教学：{args.term}")
    print(f"   定义：{args.desc}")

    # ① 草稿
    mid, defn = draft_metric(client, args.term, args.desc, syn, ddl_text(conn), loop.aligner.metrics)
    if args.metric_id:
        mid = args.metric_id
    if mid in loop.aligner.metrics and not args.force:
        print(f"❌ 指标 ID「{mid}」已存在（--force 可覆盖）")
        sys.exit(1)
    print("\n🧾 LLM 草稿：")
    print(yaml.safe_dump({mid: defn}, allow_unicode=True, sort_keys=False))

    # ② 三关校验
    ok, info = validate_metric(mid, defn, conn, loop.aligner.metrics)
    if ok:
        print(f"✅ 三关校验通过（结构 / 安全 / 可执行）\n   试跑 SQL：{info}")
    else:
        print(f"⚠️ 校验未通过：{info}")
        if not args.force:
            print("（未写入。可补充定义后重试，或 --force 强制执行）")
            sys.exit(1)

    if args.dry_run:
        print("🧪 dry-run：未写入 learned.yaml")
        return

    # ③ 发布 + 即时验证
    path = apply_metric(mid, defn)
    print(f"💾 已写入 {path.name}（活体本体热加载中…）")

    q = f"8月{args.term}是多少？"
    ans = loop.ask(q, auto_resolve=True)
    print(f"\n🎯 即时验证：「{q}」")
    if isinstance(ans, Clarification):
        print("（触发了澄清卡，建议调整术语表述或补 --syn）")
        return
    if ans.type == "answer":
        print(f"✅ 答案：{ans.text}")
        for line in ans.disclosure or []:
            print(f"   · {line}")
    else:
        print(f"⚠️ {ans.text}")


if __name__ == "__main__":
    main()
