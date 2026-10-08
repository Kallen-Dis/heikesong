# -*- coding: utf-8 -*-
"""战绩看板 · AmbiQuery 实验与消融可视化。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from ui_helpers import inject_theme, render_sidebar_guide

ROOT = Path(__file__).resolve().parents[1]
CHARTS = ROOT / "eval" / "charts"

st.set_page_config(page_title="战绩看板 · 语枢", page_icon="📊", layout="wide")
inject_theme()

with st.sidebar:
    st.markdown("### 📖 如何读这张看板")
    st.markdown(
        '<div class="sem-sidebar-tip">'
        "<b>主战绩图</b>：同一套 24 道种子题上，四种 LLM 路线 vs 语枢离线编译器。"
        "重点看 <b>C 组（本体进提示词）只有 4.3%</b>——比裸 DDL 更差。"
        "</div>",
        unsafe_allow_html=True,
    )
    with st.expander("四组实验分别是什么", expanded=True):
        st.markdown(
            "| 组 | 含义 |\n|---|---|\n"
            "| **A** | 裸 DDL 给 LLM |\n"
            "| **B** | DDL + 中文列注释 |\n"
            "| **C** | DDL + 本体 YAML 全文塞进提示词 |\n"
            "| **D** | **语枢**（本体由编译器消费，非 prompt） |"
        )
    with st.expander("消融实验怎么读", expanded=False):
        st.markdown(
            "- **去同义词**：黑话/口语映射失效 → 大量题听不懂\n\n"
            "- **去公理/关系**：超时、多跳类指标编译失败\n\n"
            "- **去澄清**：准确率不变，但 **36.8% 题会静默猜口径**（风险面）"
        )
    st.caption("全量 120 题离线自检：语枢 120/120 · 见 eval/iso_selfcheck.md")

st.title("📊 实验战绩看板")
st.caption(
    "AmbiQuery 评测 · 矩阵实验为种子 24 题 × LLM 三组各 3 次采样取多数 · "
    "语枢 D 组为离线确定性编译 · 原始数据：`eval/`"
)

st.info(
    "**读图口诀**：柱越高越好（通过率）。若只能记住一件事——"
    "「把本体塞进 prompt」是四条 LLM 路线里最差的；语义应交给**编译器**。"
    "完整 120 题门禁见 `python scripts/eval_iso.py`。",
    icon="💡",
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("语枢 D 组", "100%", "120/120 全量", help="离线语义编译 + 澄清 + 验证")
c2.metric("裸 DDL A 组", "21.7%", "种子题矩阵", help="DeepSeek-chat，3 次采样多数")
c3.metric("+注释 B 组", "17.4%", "种子题矩阵", help="证明「加注释」不够")
c4.metric("本体进 prompt C 组", "4.3%", "种子题矩阵", help="反直觉：最差路线")

st.divider()


def show(path: Path, caption: str, tip: str) -> None:
    st.markdown(f"**{caption}**")
    st.caption(tip)
    if path.exists():
        st.image(str(path), width="stretch")
    else:
        st.warning(f"图表未生成，请在项目根运行：`python scripts/make_charts.py`")


left, right = st.columns(2)
with left:
    show(
        CHARTS / "fig1_headline.png",
        "图 1 · 主战绩",
        "四组通过率对比——路演主视觉，建议放 PPT 第一页。",
    )
with right:
    show(
        CHARTS / "fig3_ablation.png",
        "图 3 · 消融边际贡献",
        "拆掉同义词 / 公理 / 澄清器各损失多少题。",
    )

left2, right2 = st.columns(2)
with left2:
    show(
        CHARTS / "fig2_category.png",
        "图 2 · 六类考点 × 四组",
        "看哪类题最拉开差距（口径、多跳通常最明显）。",
    )
with right2:
    show(
        CHARTS / "fig4_ablation_cat.png",
        "图 4 · 消融 × 分类",
        "哪个构件撑起哪类考点（例如同义词撑起 A 类）。",
    )

st.divider()
st.subheader("三条核心结论")
st.markdown(
    """
1. **「把本体塞给 LLM」是最差路线（4.3%）** —— 语义应由**编译器**消费，而不是当提示词附件。
2. **同义词表与公理/关系是准确率双支柱** —— 消融中分别损失 43 题 / 31 题（种子题集上）。
3. **澄清器不只为提分，更为消风险** —— 无澄清时 36.8% 歧义题会静默默认口径；用户若与默认不一致，即为错误率上限。

**复现命令**

```powershell
python scripts/make_charts.py
python scripts/run_experiment.py --samples 3
python scripts/run_ablation.py
python scripts/validate_draft.py
python scripts/eval_iso.py
```
"""
)
