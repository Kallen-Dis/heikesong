# -*- coding: utf-8 -*-
"""澄清回流挖掘：读 feedback_log.jsonl → 聚合偏好 → 产出**建议草案**。

用法：
    python scripts/mine_feedback.py                     # 分析默认日志
    python scripts/mine_feedback.py --demo              # 用样例数据演示（不依赖已有日志）
    python scripts/mine_feedback.py --min-support 2

产出：eval/feedback_mining.md（含 YAML 建议草案）
设计原则：只给建议，不自动改本体；建议需人工确认后走三关校验入库。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.feedback import (DEFAULT_PATH, feedback_path, load_feedback, log_resolution,  # noqa: E402
                          summarize)

EVAL_DIR = ROOT / "eval"


def _demo_records() -> list[dict]:
    """示例：同一批问题里 8/10 的人选了「净实付」口径，另 4 次问了「最近」。"""
    from src.feedback import FeedbackRecord

    out: list[dict] = []
    for i in range(10):
        rec = FeedbackRecord(ts=f"2026-10-08T10:{i:02d}:00", question="上个月的金额是多少？",
                             point_id="variant", prompt="「成交总额」有多种口径，请选择：",
                             chosen_label="毛额（吊牌金额，未扣折扣、含取消订单）" if i < 8 else "实付（已扣折扣，含取消订单）",
                             payload={"metric": "GMV"}, metric_id="GMV", source="demo")
        out.append(rec.__dict__)
    for i in range(4):
        rec = FeedbackRecord(ts=f"2026-10-08T11:{i:02d}:00", question="最近的订单量是多少？",
                             point_id="time", prompt="未指明时间范围，请选择：",
                             chosen_label="近7天（09/14–09/20）", payload={}, metric_id="OrderCount",
                             source="demo")
        out.append(rec.__dict__)
    for i in range(3):
        rec = FeedbackRecord(ts=f"2026-10-08T12:{i:02d}:00", question="8月苹果的订单量是多少？",
                             point_id="entity", prompt="「苹果」指商品品牌还是客户？",
                             chosen_label="商品品牌「苹果」", payload={"brand": "苹果"},
                             metric_id="OrderCount", source="demo")
        out.append(rec.__dict__)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="澄清回流挖掘")
    ap.add_argument("--path", default=None, help="反馈日志路径（默认 ontology/feedback_log.jsonl）")
    ap.add_argument("--min-support", type=int, default=3, help="最少样本数才给建议")
    ap.add_argument("--demo", action="store_true", help="用内置样例数据演示（不读真实日志）")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.demo:
        records = _demo_records()
        source_note = "内置样例数据（`--demo`）"
    else:
        target = feedback_path(args.path)
        records = load_feedback(target)
        source_note = f"`{target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}`"

    summary = summarize(records, min_support=args.min_support)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# 澄清回流分析报告",
        "",
        f"- 生成时间：{stamp}　｜　样本来源：{source_note}",
        f"- 样本总数：**{summary['total']}** 条澄清交互",
        "",
        "> 澄清卡是平台唯一能免费拿到的人类标注：它记录「用户的词 → 真正想要的口径/实体/时间窗」。",
        "> 本报告只产出**建议草案**，不自动改本体。",
        "",
        "## 1. 口径偏好（按指标）",
        "",
    ]
    if summary["variant_preference"]:
        lines += ["| 指标 | 选择分布 |", "|---|---|"]
        for mid, dist in summary["variant_preference"].items():
            pairs = "、".join(f"{k}×{v}" for k, v in sorted(dist.items(), key=lambda kv: -kv[1]))
            lines.append(f"| `{mid}` | {pairs} |")
    else:
        lines.append("（无口径类澄清样本）")

    lines += ["", "## 2. 时间范围偏好", ""]
    if summary["time_preference"]:
        lines += [f"- {k}×{v}" for k, v in sorted(summary["time_preference"].items(), key=lambda kv: -kv[1])]
    else:
        lines.append("（无时间类澄清样本）")

    lines += ["", "## 3. 实体歧义热点", ""]
    if summary["entity_hotspots"]:
        lines += [f"- {k}×{v}" for k, v in sorted(summary["entity_hotspots"].items(), key=lambda kv: -kv[1])]
    else:
        lines.append("（无实体类澄清样本）")

    lines += ["", "## 4. 最常触发澄清的问题", ""]
    if summary["top_questions"]:
        lines += [f"- {q} × {n}" for q, n in summary["top_questions"]]
    else:
        lines.append("（无）")

    lines += ["", f"## 5. 建议草案（支持度 ≥ {args.min_support}）", ""]
    if summary["suggestions"]:
        for s in summary["suggestions"]:
            lines.append(f"- **[{s['kind']}]** {s['suggest']}（{s['support']}）—— {s['reason']}")
        lines += ["", "```yaml",
                  "# 待人工确认的建议（示例结构，非自动写入）",
                  "metrics:"]
        for s in summary["suggestions"]:
            if s["kind"] == "default_variant":
                lines += [f"  {s['metric']}:", f"    # default_variant: <对应 variant id>"
                          "   # 依据：用户多选偏好",
                          "    # default_rationale: 统计显示多数用户期望该口径（需业务确认）"]
        lines += ["```"]
    else:
        lines.append("样本不足以形成建议（继续积累澄清交互后再挖掘）。")

    lines += ["", "---", "",
              "> 复现：`python scripts/mine_feedback.py --demo`（样例）或 `python scripts/mine_feedback.py`（真实日志）"]

    out = Path(args.out) if args.out else EVAL_DIR / "feedback_mining.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"样本 {summary['total']} 条　建议 {len(summary['suggestions'])} 条")
    for s in summary["suggestions"]:
        print(f"  · [{s['kind']}] {s['suggest']}（{s['support']}）")
    print(f"报告：{out.relative_to(ROOT)}（默认日志：{DEFAULT_PATH.relative_to(ROOT)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
