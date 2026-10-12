# -*- coding: utf-8 -*-
"""Streamlit 界面冒烟测试（基于 streamlit.testing.v1.AppTest）。

模拟一次完整交互：提问歧义问题 → 出现澄清卡 → 确认执行 → 渲染答案。
用法：python scripts/test_ui.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["SEMANTICA_UI_TEST"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest


def main() -> None:
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception, f"初始渲染异常: {at.exception}"
    print("✅ 初始渲染 OK")
    brand = [m.value for m in at.markdown if m.value and "语枢 Semantica" in m.value]
    assert brand, "页头应包含语枢 Semantica"
    print("   页头 OK | metric 卡片数:", len(at.metric))

    # 提问：口径歧义（金额三口径）
    at.chat_input[0].set_value("8月的金额是多少？").run()
    assert not at.exception, f"提问异常: {at.exception}"
    print("\n✅ 歧义提问 OK —— 澄清卡（radio）数:", len(at.radio))
    assert len(at.radio) >= 1, "应出现口径澄清卡"
    for r in at.radio:
        print("   ·", r.label, "->", [str(o) for o in r.options][:4])

    # 点击"确认并执行"
    for radio in at.radio:
        radio.set_value(0)
    at.run()
    btn = [b for b in at.button if "按这个去查" in b.label or "确认并执行" in b.label]
    assert btn, f"找不到确认按钮: {[b.label for b in at.button]}"
    btn[0].click().run()
    assert not at.exception, f"确认执行异常: {at.exception}"
    print("\n✅ 澄清确认并执行 OK")

    md_all = [m.value for m in at.markdown]
    hits = [m for m in md_all if m.startswith("###") and ("✅" in m or "无结果" in m)]
    print("   答案区渲染:", hits[:2])
    assert hits, "应有答案渲染"

    print("\n🎉 主流程冒烟测试通过")

    # 现场教学：独立 AppTest，避免澄清卡 widget 状态污染
    at2 = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at2.run()
    assert not at2.exception, f"教学面板渲染异常: {at2.exception}"
    at2.session_state["tour_step"] = None
    at2.run()
    assert not at2.exception, f"关闭导览后渲染异常: {at2.exception}"
    assert any("现场教学" in e.label for e in at2.expander), "应渲染现场教学面板"
    teach_btn = [b for b in at2.button if "教会平台" in b.label]
    assert teach_btn, "应有『教会平台』按钮"
    preset_btns = [b for b in at2.button if b.label.startswith("示例：")]
    assert preset_btns, "应有预设示例按钮"
    preset_btns[0].click().run()
    assert not at2.exception, f"预设填充异常: {at2.exception}"
    print("✅ 现场教学面板 OK | 预设已填充：", at2.session_state["teach_term"])
    print("\n🎉 UI 冒烟测试全部通过")


if __name__ == "__main__":
    main()
