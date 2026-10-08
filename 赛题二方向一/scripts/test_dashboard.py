# -*- coding: utf-8 -*-
"""看板页面冒烟测试（AppTest）。

用法：python scripts/test_dashboard.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest


def main() -> None:
    pages = sorted((ROOT / "pages").glob("*.py"))
    assert pages, "pages/ 目录下应有看板页面"
    page = pages[0]
    at = AppTest.from_file(str(page), default_timeout=90)
    at.run()
    assert not at.exception, f"看板渲染异常: {at.exception}"
    print(f"✅ 看板页面渲染 OK：{page.name}")
    print(f"   metric 卡片：{len(at.metric)}｜markdown 块：{len(at.markdown)}")
    charts = sorted((ROOT / "eval" / "charts").glob("*.png"))
    print(f"   图表文件：{len(charts)} 张 " + "、".join(p.name for p in charts))


if __name__ == "__main__":
    main()
