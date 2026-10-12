# -*- coding: utf-8 -*-
"""侧栏说明 + 战绩看板高亮。主页面不再做自动翻页。"""
from __future__ import annotations

import streamlit as st

DEMO_Q = "8月华东区的GMV是多少？"

DASH_STEPS = [
    {"id": "why", "target": "why", "title": "这页在证明什么"},
    {"id": "cards", "target": "cards", "title": "四个成绩"},
    {"id": "fig1", "target": "fig1", "title": "总览图"},
    {"id": "rest", "target": "rest", "title": "细分图"},
]


def _init() -> None:
    st.session_state.setdefault("dash_tour", None)
    st.session_state.setdefault("auto_demo_on", False)
    st.session_state.tour_step = None


def is_clarification(obj: object) -> bool:
    return type(obj).__name__ == "Clarification" or (
        hasattr(obj, "points") and hasattr(obj, "alignment") and not hasattr(obj, "type")
    )


def render_coach() -> None:
    _init()
    with st.sidebar:
        st.markdown("### 语枢 Semantica")
        st.caption("Agent 语义执行网关 · 合成数据演示")
        st.markdown(
            "AI 使用数据，需要共同的业务含义，还需要可执行的使用条件。"
            "从口径澄清、证据重放，到分层比较与情景推演。"
        )
        st.divider()
        st.page_link("pages/4_比较前先检查.py", label="01 · SQL正确，结论反转")
        st.page_link("pages/2_契约与证据.py", label="02 · 契约与证据")
        st.page_link("pages/3_决策实验室.py", label="03 · 条件决策实验室")
        if st.button("📊 实验战绩", width="stretch", type="primary"):
            st.switch_page("pages/1_战绩看板.py")


def render_dash_coach() -> None:
    _init()
    with st.sidebar:
        st.markdown("### 实验战绩")
        st.caption("四组做法 × 同一批含糊问题，柱子越高答对越多。")
        if st.button("← 返回主页", width="stretch"):
            st.switch_page("app.py")


def dash_targeting(target: str) -> bool:
    return False


def dash_spotlight(target: str):
    return st.container()
