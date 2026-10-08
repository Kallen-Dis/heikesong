# -*- coding: utf-8 -*-
"""本体一致性校验入口。

用法：
    python scripts/check_ontology.py            # 静态检查
    python scripts/check_ontology.py --execute  # 追加 EXPLAIN 可执行性检查
    python scripts/check_ontology.py --out eval/ontology_lint.md

退出码：0 = 无 error（允许 warning）；1 = 存在 error（可用于 CI 门禁）。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ontology_lint import format_report, has_errors, lint_executable, lint_ontology  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="本体一致性校验（ontology lint）")
    ap.add_argument("--dir", default=None, help="本体目录（默认 ontology/）")
    ap.add_argument("--execute", action="store_true", help="追加 EXPLAIN 可执行性检查")
    ap.add_argument("--out", default=None, help="把报告写入指定路径")
    args = ap.parse_args()

    issues = lint_ontology(args.dir) if args.dir else lint_ontology()
    if args.execute:
        issues += lint_executable(args.dir) if args.dir else lint_executable()

    report = format_report(issues)
    print(report)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# 本体校验报告\n\n- 生成时间：{datetime.now():%Y-%m-%d %H:%M}\n\n"
                       f"```\n{report}\n```\n", encoding="utf-8")
        print(f"\n报告已写入：{out}")

    return 1 if has_errors(issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
