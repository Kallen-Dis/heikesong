# -*- coding: utf-8 -*-
"""战绩看板 · AmbiQuery 实验与消融可视化。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from tour import dash_spotlight, render_dash_coach
from ui_helpers import inject_theme

ROOT = Path(__file__).resolve().parents[1]
CHARTS = ROOT / "eval" / "charts"

st.set_page_config(page_title="战绩看板 · 语枢", page_icon="📊", layout="wide")
inject_theme()
render_dash_coach()

with st.sidebar:
    st.markdown("### 📖 这页在证明什么")
    st.markdown(
        '<div class="sem-sidebar-tip">'
        "主页面演示「怎么问」。这一页回答「为什么不能只把表丢给大模型」。"
        "柱子越高，答对的题越多。请先看最矮的那根：把公司词典整段塞进提示词，成绩最差。"
        "</div>",
        unsafe_allow_html=True,
    )
    with st.expander("四组实验，用大白话", expanded=True):
        st.markdown(
            """
同一批故意写得很含糊的题，换四种做法：

- **A 组 · 只给表结构**：告诉模型有哪些表、哪些列，让它自己写 SQL。这是现在很多「问数」产品的默认做法。
- **B 组 · 再加中文注释**：列名旁边写上「这是实付金额」。想证明「注释写清楚就够了」。结果不够。
- **C 组 · 把整本词典贴进提示词**：本体、指标、同义词全部塞给模型，指望它自己读懂再用。这组成绩最差。
- **D 组 · 语枢**：词典不交给模型自由发挥，而是由程序按规则翻译、必要时问人、再生成 SQL。

A/B/C 用的是大模型，每题问 3 次，取出现最多的结果。D 组不靠模型碰运气，同一题每次结果相同。
            """
        )
    with st.expander("拆掉零件的实验（消融）", expanded=False):
        st.markdown(
            """
把语枢的零件一个个拿掉，看会坏掉多少题：

- **拿掉同义词表**：听不懂「单量」「大盘」这类口语，大量题对不上指标。
- **拿掉规则和表关系**：不会判断「超时」，也不会把订单、运单、承运商连起来。
- **拿掉澄清**：分数看起来还是满分，因为标准答案碰巧就是默认选项。
  但大约三分之一的题，系统是在**没问你的情况下自己选了一种算法**。
  你要的若不是那个默认算法，这些题就会全部算错。
            """
        )
    st.caption("另外有一套 120 题的完整考试，语枢离线跑下来是 120/120。明细在 eval/iso_selfcheck.md。")

with dash_spotlight("why"):
    st.title("📊 实验战绩看板")
    st.caption("用同一套含糊问题，比较「直接问大模型」和「先翻译再查询」。柱子越高表示答对越多。")

with dash_spotlight("cards"):
    st.info(
        "如果只记一句话：把公司词典贴进对话框，并不能让模型用对数据；"
        "词典要交给固定的翻译程序，遇到歧义先问人。下面 C 组只有 4.3%，就是这条结论的证据。",
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


with dash_spotlight("fig1"):
    show(
        CHARTS / "fig1_headline.png",
        "图 1 · 四种做法，谁答对更多",
        "从左到右大致是：只给表、加注释、把词典塞进提示词、用语枢翻译后再查。最右边应明显更高。",
    )

with dash_spotlight("rest"):
    left, right = st.columns(2)
    with left:
        show(
            CHARTS / "fig3_ablation.png",
            "图 3 · 拿掉一个零件会怎样",
            "看同义词、计算规则、澄清这三样分别撑起多少题。澄清那一栏分数不一定掉，原因写在侧边栏。",
        )
    with right:
        show(
            CHARTS / "fig2_category.png",
            "图 2 · 哪一类题最容易翻车",
            "横轴是六类考题：黑话、口径、指代、时间、跨表、不该答的题。看大模型在哪一类掉得最狠。",
        )
    show(
        CHARTS / "fig4_ablation_cat.png",
        "图 4 · 每个零件负责哪一类题",
        "例如拿掉同义词后，黑话类会大面积失败；拿掉表关系后，跨表和超时类会失败。",
    )

st.divider()
st.subheader("三条核心结论")
st.markdown(
    """
1. **把整本词典贴给大模型，是四种做法里最差的（只对了 4.3%）**。模型上下文里堆了太多规则，反而更容易用错。词典应该由程序按步骤使用。
2. **两样东西最撑得分**：口语对照表（拿掉后错 43 题），以及「超时怎么判定、表怎么连」的规则（拿掉后错 31 题）。
3. **先问再算，主要是为了不猜**。关掉提问后，分数可以仍然好看，因为标准答案刚好等于默认选项；一旦你要的不是那个默认算法，大约 37% 的题会在你不知情时算错。

想自己重跑这些图的人，可以用下面的命令。只是来看演示，可以忽略。

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
