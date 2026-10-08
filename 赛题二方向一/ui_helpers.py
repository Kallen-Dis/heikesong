# -*- coding: utf-8 -*-
"""Streamlit 演示界面：统一样式、五步闭环说明、示例题分类。"""
from __future__ import annotations

import streamlit as st

# 品牌色（与 eval/charts 一致）
C_PRIMARY = "#1b8a5a"
C_MUTED = "#5c6778"
C_ACCENT = "#2563eb"
C_WARN = "#c1443c"
C_AMBER = "#e0a458"

PIPELINE_STEPS = [
    ("① 解析", "理解自然语言问句", "你用人话提问，系统保留原问题与上下文。"),
    ("② 对齐", "术语 → 本体概念/指标", "「GMV」「单量」映射到指标库；识别区域、品牌等筛选。"),
    ("③ 澄清", "歧义先问清，再计算", "口径/时间/实体有多个合法含义时弹出选项，避免静默猜错。"),
    ("④ 编译", "语义计划 → 安全 SQL", "按选定口径生成参数化 SQL，不把数值拼进字符串。"),
    ("⑤ 披露", "可信答案 + 审计信息", "结果附带数据截止、口径说明、编译 SQL，便于复核。"),
]

EXAMPLE_ITEMS = [
    {"q": "上个月的履约超时率是多少？", "cat": "B", "name": "口径+时间", "hint": "相对时间 + 超时率默认口径"},
    {"q": "8月华东区的GMV是多少？", "cat": "B", "name": "口径歧义", "hint": "GMV 有三种金额算法，应弹澄清卡"},
    {"q": "8月苹果的订单量是多少？", "cat": "C", "name": "实体歧义", "hint": "「苹果」可能是品牌或客户公司名"},
    {"q": "最近的订单量是多少？", "cat": "D", "name": "模糊时间", "hint": "「最近」需澄清或约定默认窗口"},
    {"q": "8月超时运单最多的承运商是谁？", "cat": "E", "name": "多跳关系", "hint": "订单→运单→承运商 多表路径"},
    {"q": "上个月华东区的退货率是多少？", "cat": "F", "name": "陷阱题", "hint": "无退货数据，应诚实拒答"},
]

CAT_LEGEND = {
    "A": ("同义词", "#64748b"),
    "B": ("口径", C_AMBER),
    "C": ("实体", C_ACCENT),
    "D": ("时间", "#7c3aed"),
    "E": ("多跳", C_PRIMARY),
    "F": ("陷阱", C_WARN),
}


def inject_theme() -> None:
    st.markdown(
        f"""
<style>
    /* 主内容区略增行距 */
    .main .block-container {{ padding-top: 1.2rem; max-width: 1100px; }}
    /* 顶栏英雄区 */
    .sem-hero {{
        background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 55%, {C_PRIMARY} 120%);
        border-radius: 12px;
        padding: 1.25rem 1.5rem 1.1rem;
        margin-bottom: 1rem;
        color: #f8fafc;
        border: 1px solid rgba(255,255,255,0.08);
    }}
    .sem-hero h1 {{ color: #fff !important; font-size: 1.75rem !important; margin: 0 0 0.35rem 0 !important; }}
    .sem-hero p {{ color: #cbd5e1; margin: 0; font-size: 0.95rem; line-height: 1.5; }}
    /* 五步流水线 */
    .sem-pipeline {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 0.75rem 0 0.25rem; }}
    .sem-step {{
        flex: 1 1 140px;
        background: rgba(255,255,255,0.08);
        border-radius: 8px;
        padding: 0.55rem 0.65rem;
        border-left: 3px solid {C_PRIMARY};
    }}
    .sem-step strong {{ display: block; color: #e2e8f0; font-size: 0.82rem; }}
    .sem-step span {{ color: #94a3b8; font-size: 0.72rem; line-height: 1.35; }}
    /* 示例题标签 */
    .sem-tag {{
        display: inline-block;
        font-size: 0.68rem;
        padding: 0.12rem 0.45rem;
        border-radius: 999px;
        margin-right: 0.35rem;
        font-weight: 600;
        color: #fff;
    }}
    .sem-example-hint {{
        color: {C_MUTED};
        font-size: 0.78rem;
        margin-top: -0.35rem;
        margin-bottom: 0.5rem;
    }}
    /* 澄清卡 */
    .sem-clarify-box {{
        background: #fffbeb;
        border: 1px solid #fcd34d;
        border-radius: 10px;
        padding: 0.25rem 0.5rem;
    }}
    /* 信任标签 */
    .sem-trust-row {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.5rem 0; }}
    .sem-trust-pill {{
        background: #ecfdf5;
        color: #065f46;
        border: 1px solid #a7f3d0;
        border-radius: 6px;
        padding: 0.25rem 0.55rem;
        font-size: 0.8rem;
    }}
    /* 侧边栏教程 */
    section[data-testid="stSidebar"] .block-container {{ padding-top: 1rem; }}
    .sem-sidebar-tip {{
        background: #f1f5f9;
        border-radius: 8px;
        padding: 0.65rem 0.75rem;
        font-size: 0.85rem;
        line-height: 1.55;
        color: #334155;
        margin-bottom: 0.75rem;
    }}
</style>
        """,
        unsafe_allow_html=True,
    )


def render_pipeline_bar() -> None:
    """标题下方：五步闭环可视化条。"""
    steps_html = "".join(
        f'<div class="sem-step"><strong>{title}</strong><span>{sub}</span></div>'
        for title, sub, _ in PIPELINE_STEPS
    )
    st.markdown(f'<div class="sem-pipeline">{steps_html}</div>', unsafe_allow_html=True)


def render_sidebar_guide(*, show_teaching: bool = True) -> None:
    with st.sidebar:
        st.markdown("### 📖 使用教学")
        st.markdown(
            '<div class="sem-sidebar-tip">'
            "<b>第一次来？</b> 建议顺序：① 看上方五步 → "
            "② 点一条<b>示例问题</b> → ③ 若有黄框澄清卡则选口径再点确认 → "
            "④ 展开「口径披露 / 编译 SQL」理解系统如何作答。"
            "</div>",
            unsafe_allow_html=True,
        )
        with st.expander("五步闭环详解", expanded=False):
            for title, subtitle, detail in PIPELINE_STEPS:
                st.markdown(f"**{title} · {subtitle}**")
                st.caption(detail)
        with st.expander("六类示例题说明", expanded=False):
            for code, (name, color) in CAT_LEGEND.items():
                st.markdown(
                    f'<span class="sem-tag" style="background:{color}">{code}</span> **{name}**',
                    unsafe_allow_html=True,
                )
            st.caption("A 同义词 · B 口径 · C 实体 · D 时间 · E 多跳 · F 陷阱（应拒答）")
        if show_teaching:
            with st.expander("现场教学怎么用", expanded=False):
                st.markdown(
                    "1. 填写**新术语**和**一句人话定义**（或点预设示例）\n\n"
                    "2. 需配置 `.env` 中的 `LLM_API_KEY` 才能生成草稿\n\n"
                    "3. 系统自动：**LLM 草稿 → 三关校验 → 写入 learned.yaml → 立刻可问**"
                )
        with st.expander("裸 LLM 对照模式", expanded=False):
            st.markdown(
                "打开开关后，同一问题会**左右对比**：\n\n"
                "- **左**：语枢（本体 + 澄清 + 披露）\n\n"
                "- **右**：把 DDL 直接给大模型写 SQL\n\n"
                "用于路演展示「瓶颈在语义，不在写 SQL」。"
            )
        st.divider()
        st.caption("战绩与实验图表请点左侧导航 **战绩看板**")


def render_trust(trust: dict) -> None:
    if not trust:
        return
    pills = "".join(
        f'<span class="sem-trust-pill"><b>{k}</b>：{v}</span>' for k, v in trust.items()
    )
    st.markdown(f'<div class="sem-trust-row">{pills}</div>', unsafe_allow_html=True)


def cat_badge(cat: str) -> str:
    name, color = CAT_LEGEND.get(cat, ("", C_MUTED))
    return f'<span class="sem-tag" style="background:{color}">{cat} {name}</span>'
