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
        st.caption("语义编译器 · 演示")
        st.markdown(
            "同一批含糊的账务问题，裸 LLM 直连答对 **21.7%**，"
            "语枢先澄清歧义再查询，**120 题全对**。"
        )
        st.divider()
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
