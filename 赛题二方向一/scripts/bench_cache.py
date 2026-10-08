# -*- coding: utf-8 -*-
"""语义缓存基准：冷启动 vs 热命中，量化"同一个问题只算一次"。

用法：
    python scripts/bench_cache.py [--repeat 3] [--profile full]

输出：eval/cache_bench.md（含命中率、耗时、加速比、逐题命中明细）
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.benchmark import load_items  # noqa: E402
from src.cache import SemanticCache  # noqa: E402
from src.db import connect  # noqa: E402
from src.loop import QueryLoop  # noqa: E402

EVAL_DIR = ROOT / "eval"


def _run(loop: QueryLoop, questions: list[str]) -> tuple[float, list[str]]:
    t0 = time.perf_counter()
    answers = []
    for q in questions:
        ans = loop.ask(q, auto_resolve=True)
        answers.append(getattr(ans, "type", "clarification"))
    return time.perf_counter() - t0, answers


def main() -> int:
    ap = argparse.ArgumentParser(description="语义缓存基准")
    ap.add_argument("--repeat", type=int, default=3, help="每个问题重复提问次数")
    ap.add_argument("--profile", default="full")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    items = load_items()
    questions = [it.question for it in items] * args.repeat
    conn = connect()

    answerable = sum(1 for it in items if it.expected_outcome == "answer")

    cold = QueryLoop(conn, profile=args.profile)                        # 无缓存（基线）
    cold_time, _ = _run(cold, questions)

    warm = QueryLoop(conn, profile=args.profile, cache=SemanticCache(maxsize=512))
    first_time, _ = _run(warm, questions[:len(items)])                   # 首次填缓存
    warm_time, _ = _run(warm, questions)                                 # 含重复提问
    stats = warm.cache.stats.as_dict()

    speedup = cold_time / warm_time if warm_time else float("inf")
    lines = [
        "# 语义缓存基准",
        "",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}　｜　档位：`{args.profile}`",
        f"- 题目：AmbiQuery {len(items)} 题 × 重复 {args.repeat} 次 = {len(questions)} 次提问"
        f"（其中可答 {answerable} 题）",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 无缓存总耗时 | {cold_time * 1000:.0f} ms |",
        f"| 有缓存总耗时 | {warm_time * 1000:.0f} ms |",
        f"| **加速比** | **{speedup:.2f}×** |",
        f"| 首次填充缓存耗时 | {first_time * 1000:.0f} ms |",
        f"| 缓存命中 / 未命中 | {stats['hits']} / {stats['misses']} |",
        f"| 命中率 | {stats['hit_rate']:.1%} |",
        f"| 淘汰数 | {stats['evictions']} |",
        "",
        "## 语义版本",
        "",
        f"- 当前版本号：`{warm.version()}`（本体 mtime + 数据仓库指纹）",
        "- 本体热加载（现场教学写 learned.yaml）或换数据集 → 版本号变化 → 旧缓存自动失效，",
        "  不会出现「改了口径还在答旧值」。",
        "",
        "## 设计取舍",
        "",
        "- **只缓存确定答案**：澄清分支与「数据不足」不入缓存，避免把一次用户选择固化成默认行为；",
        "- 命中时返回 Answer 副本，调用方修改不会污染缓存；",
        "- LRU 淘汰 + 命中率统计，便于在生产环境做容量与命中率的权衡。",
        "",
        "---",
        "",
        "> 复现：`python scripts/bench_cache.py`",
    ]
    out = Path(args.out) if args.out else EVAL_DIR / "cache_bench.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"无缓存 {cold_time * 1000:.0f} ms ｜ 有缓存 {warm_time * 1000:.0f} ms ｜ "
          f"加速 {speedup:.2f}× ｜ 命中率 {stats['hit_rate']:.1%}（{stats['hits']}/{stats['lookups']}）")
    print(f"报告：{out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
