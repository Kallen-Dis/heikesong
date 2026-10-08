# -*- coding: utf-8 -*-
"""题库 schema 规范化（一次性维护工具，幂等）。

背景：题库在不同批次生成，F 类陷阱题曾写成 `expect: insufficient` 且缺
`expected_clarification`，与其余 100 题字段不一致 —— 下游脚本必须写兼容分支。
本脚本把它们统一为规范字段，并用**指纹校验**保证只改字段名、不动内容。

统一后的字段：
    id / category / question / expected_clarification / expected_outcome /
    gold_sql / compare / notes

用法：
    python scripts/normalize_benchmark.py [--file ...] [--check]
        --check  只检查是否需要规范化，不写回（CI 用）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.benchmark import BENCHMARK_PATH, dump_item, normalize  # noqa: E402

FINGERPRINT_FIELDS = ("id", "category", "question", "gold_sql", "compare", "notes",
                      "expected_clarification")


def fingerprint(raw: dict) -> tuple:
    it = normalize(raw)
    return tuple(str(getattr(it, f)) for f in FINGERPRINT_FIELDS)


def main() -> int:
    ap = argparse.ArgumentParser(description="题库 schema 规范化")
    ap.add_argument("--file", default=str(BENCHMARK_PATH))
    ap.add_argument("--check", action="store_true", help="只检查，不写回")
    args = ap.parse_args()

    path = Path(args.file)
    raw_items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    legacy = [r for r in raw_items if tuple(sorted(r)) != ("category", "compare",
              "expected_clarification", "expected_outcome", "gold_sql", "id", "notes", "question")]
    if not legacy:
        print(f"✅ 题库已是规范 schema（{len(raw_items)} 题），无需处理。")
        return 0

    before = [fingerprint(r) for r in raw_items]
    print(f"发现 {len(legacy)} 题字段不规范，示例：{legacy[0]['id']} "
          f"（缺失 {sorted({'expected_outcome', 'expected_clarification'} - set(legacy[0]))}）")
    if args.check:
        return 1

    payload = [dump_item(normalize(r)) for r in raw_items]
    after = [fingerprint(p) for p in payload]   # normalize 对规范 schema 是幂等的
    if before != after:  # 内容指纹必须逐题一致
        raise SystemExit("❌ 指纹校验失败：规范化改变了题目内容，已中止写入")

    path.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in payload) + "\n",
                    encoding="utf-8")
    print(f"✅ 已规范化 {len(payload)} 题并写回 {path}（指纹校验通过：题目/答案/标注零变化）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
