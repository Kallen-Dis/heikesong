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

STARTER_CARDS = [
    {
        "q": "8月华东区的GMV是多少？",
        "will": "需要澄清",
        "why": "GMV 有三种口径，先确认再查询。",
        "tone": "ask",
    },
    {
        "q": "上个月华东区的退货率是多少？",
        "will": "拒绝回答",
        "why": "账本中没有退货数据。",
        "tone": "refuse",
    },
    {
        "q": "8月超时运单最多的承运商是谁？",
        "will": "直接回答",
        "why": "问题明确，可直接查询。",
        "tone": "ok",
    },
]

PIPELINE_SHORT = [
    ("① 听懂", "拆成算什么、哪段时间"),
    ("② 词典", "黑话对上指标"),
    ("③ 提问", "含糊就先问"),
    ("④ 编译", "写成安全 SQL"),
    ("⑤ 披露", "数字 + 算法说明"),
]

PIPELINE_STEPS = [
    (
        "① 听懂你在问什么",
        "把人话拆成「算什么、什么范围、什么时间」",
        "例如「8月华东区的 GMV」会被拆成：指标是成交额、地区是华东、时间是 8 月。"
        "这一步还不查数，只是把句子读懂。",
    ),
    (
        "② 对照公司词典",
        "黑话要翻译成账本里真实存在的东西",
        "「GMV」「单量」「妥投率」在每家公司含义不同。语枢用一份叫「本体」的词典："
        "指标怎么算、表和表怎么连、哪些词根本没有数据。对不上词典的，不会瞎编。",
    ),
    (
        "③ 听不清就先问",
        "同一个词有好几种合法算法时，先让你选",
        "「金额」可以是吊牌价、实付、或去掉取消单后的净额。系统弹一张澄清卡，"
        "你点选之后才去算。这不是它不会，而是故意不替你猜。",
    ),
    (
        "④ 写成能查账的语句",
        "把你确认过的意思编译成 SQL",
        "SQL 是数据库的查询语言。语枢按你选的口径自动写出查询，"
        "数字走安全绑定，不会把你输入的内容直接拼进语句里。",
    ),
    (
        "⑤ 交出数字，并说明怎么来的",
        "答案旁边附带口径、时间和可核对的 SQL",
        "你看到的不只是一个数，还有：用了哪种算法、统计到哪一天、"
        "筛了哪些条件。这样别人可以复核，而不是只能相信模型。",
    ),
]

EXAMPLE_ITEMS = [
    {
        "q": "上个月的履约超时率是多少？",
        "cat": "B",
        "name": "口径+时间",
        "hint": "「上个月」要换成具体日期；「超时率」有不止一种算法。看系统会不会先问清楚。",
    },
    {
        "q": "8月华东区的GMV是多少？",
        "cat": "B",
        "name": "口径歧义",
        "hint": "GMV 听起来像一个数，其实有三种算法。正确做法是弹出澄清卡，让你选一种再算。",
    },
    {
        "q": "8月苹果的订单量是多少？",
        "cat": "C",
        "name": "实体歧义",
        "hint": "「苹果」可能是手机品牌，也可能是一家叫苹果的客户公司。系统应让你指明是哪一个。",
    },
    {
        "q": "最近的订单量是多少？",
        "cat": "D",
        "name": "模糊时间",
        "hint": "「最近」没有统一含义：近 7 天、近 30 天都可以。不能自己默默选一个时间窗。",
    },
    {
        "q": "8月超时运单最多的承运商是谁？",
        "cat": "E",
        "name": "多跳关系",
        "hint": "答案不在一张表里：订单连到运单，运单再连到承运商，还要按「超时」的定义去数。",
    },
    {
        "q": "上个月华东区的退货率是多少？",
        "cat": "F",
        "name": "陷阱题",
        "hint": "这套数据里没有退货表。正确表现是直接说「算不了」，而不是编一个 0 或随便一个百分比。",
    },
]

CAT_STORIES = {
    "A": "公司里的黑话。别人说「单量」「大盘」「妥投率」，系统要知道它们对应哪一个正式指标。",
    "B": "同一个词有多种合法算法。例如「金额」可以含取消单，也可以不含。必须先问你要哪一种。",
    "C": "一个词指向两个东西。例如「苹果」既是品牌，也是客户名。",
    "D": "时间说得含糊。「上月」「最近」「近 7 天」都要落到固定的起止日期上。本演示的「今天」固定为 2026-09-20，所以每次结果一样。",
    "E": "一句话要串好几张表。比如从订单找到运单，再找到承运商。",
    "F": "问了数据里根本没有的东西，比如退货率、毛利、库存。这时拒绝回答才是对的。",
}

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
    .sem-brand {{
        background: linear-gradient(135deg, #0f172a 0%, #134e4a 48%, {C_PRIMARY} 100%);
        border-radius: 14px;
        padding: 1.1rem 1.35rem 1rem;
        margin: 0 0 1rem 0;
        color: #f8fafc;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
    }}
    .sem-brand h2 {{ margin: 0; font-size: 1.55rem; font-weight: 700; color: #fff !important; }}
    .sem-brand p {{ margin: 0.35rem 0 0; color: #cbd5e1; font-size: 0.92rem; line-height: 1.55; }}
    .sem-pipeline {{ display: flex; flex-wrap: wrap; gap: 0.45rem; margin: 0.85rem 0 0.15rem; }}
    .sem-step {{
        flex: 1 1 118px;
        background: var(--secondary-background-color, #ffffff);
        border-radius: 10px;
        padding: 0.5rem 0.6rem;
        border: 1px solid rgba(100, 116, 139, 0.35);
        border-top: 3px solid {C_PRIMARY};
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
    }}
    .sem-step strong {{
        display: block;
        color: var(--text-color, #0f172a);
        font-size: 0.8rem;
    }}
    .sem-step span {{
        color: #64748b;
        font-size: 0.72rem;
        line-height: 1.35;
    }}
    /* 指标卡：背景与文字必须同色体系，避免深色主题下「白底 + 浅字」 */
    div[data-testid="stMetric"] {{
        background: var(--secondary-background-color, #ffffff) !important;
        border: 1px solid rgba(100, 116, 139, 0.35);
        border-radius: 10px;
        padding: 0.45rem 0.55rem 0.35rem;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
    }}
    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] label p,
    div[data-testid="stMetric"] [data-testid="stMetricLabel"],
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] p {{
        color: #64748b !important;
    }}
    div[data-testid="stMetric"] [data-testid="stMetricValue"],
    div[data-testid="stMetric"] [data-testid="stMetricValue"] div {{
        color: var(--text-color, #0f172a) !important;
    }}
    div[data-testid="stMetric"] [data-testid="stMetricDelta"] {{
        color: #64748b !important;
    }}
    .sem-section {{
        font-size: 1.08rem;
        font-weight: 600;
        color: var(--text-color, #0f172a);
        margin: 0.35rem 0 0.55rem;
        padding-left: 0.55rem;
        border-left: 4px solid {C_PRIMARY};
    }}
    /* 首页结论先行 hero */
    .hero {{
        background: linear-gradient(135deg, #0f172a 0%, #134e4a 55%, {C_PRIMARY} 115%);
        border-radius: 16px;
        padding: 1.4rem 1.6rem 1.3rem;
        margin: 0 0 1.1rem;
        color: #f8fafc;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.16);
    }}
    .hero .hero-brand {{
        display: inline-block;
        background: rgba(255, 255, 255, 0.14);
        border: 1px solid rgba(255, 255, 255, 0.22);
        border-radius: 999px;
        padding: 0.25rem 0.7rem;
        font-size: 0.82rem;
        font-weight: 700;
        color: #ffffff;
        letter-spacing: 0.02em;
        margin-bottom: 0.7rem;
    }}
    .hero h1 {{
        color: #ffffff !important;
        font-size: 1.65rem !important;
        line-height: 1.3 !important;
        margin: 0 0 0.4rem 0 !important;
        font-weight: 800 !important;
    }}
    .hero .hero-sub {{
        color: #cbd5e1;
        font-size: 1rem;
        line-height: 1.55;
        margin: 0 0 1rem;
    }}
    .hero .hero-sub b {{ color: #ffffff; }}
    .hero-compare {{
        display: flex;
        flex-direction: column;
        gap: 0.6rem;
        margin: 0.4rem 0 1rem;
        max-width: 640px;
    }}
    .hero-row {{
        display: flex;
        align-items: center;
        gap: 0.7rem;
    }}
    .hero-row .lbl {{
        flex: 0 0 96px;
        font-size: 0.92rem;
        font-weight: 700;
        color: #e2e8f0;
        text-align: right;
    }}
    .hero-row .track {{
        flex: 1;
        height: 26px;
        background: rgba(255, 255, 255, 0.14);
        border-radius: 999px;
        overflow: hidden;
    }}
    .hero-row .fill {{
        height: 100%;
        border-radius: 999px;
        display: flex;
        align-items: center;
        justify-content: flex-end;
        padding-right: 0.6rem;
        font-size: 0.8rem;
        font-weight: 800;
        color: #fff;
        min-width: 46px;
    }}
    .hero-row .fill.bad {{ background: linear-gradient(90deg, #64748b, #94a3b8); }}
    .hero-row .fill.good {{ background: linear-gradient(90deg, #059669, #34d399); }}
    .hero-row .val {{
        flex: 0 0 58px;
        font-size: 1.15rem;
        font-weight: 800;
        color: #fff;
    }}
    .hero-why {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.6rem;
        margin-top: 0.2rem;
    }}
    .hero-why .chip {{
        background: rgba(255, 255, 255, 0.10);
        border: 1px solid rgba(255, 255, 255, 0.18);
        border-radius: 999px;
        padding: 0.4rem 0.85rem;
        font-size: 0.9rem;
        color: #e2e8f0;
    }}
    .hero-why .chip b {{ color: #ffffff; }}
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
        background: linear-gradient(90deg, #fffbeb, #fef3c7);
        border: 1px solid #fbbf24;
        border-radius: 12px;
        padding: 0.75rem 1rem;
        margin: 0.5rem 0 0.75rem;
        font-size: 0.9rem;
        line-height: 1.55;
        color: #78350f;
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
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.tour-pin) {{
        box-shadow: 0 0 0 3px #f59e0b;
        border-radius: 12px;
        animation: tourPulse 1.3s ease-in-out infinite;
    }}
    @keyframes tourPulse {{
        0%, 100% {{ box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.7); }}
        50% {{ box-shadow: 0 0 0 5px rgba(245, 158, 11, 0.15); }}
    }}
    .sem-tour-strip {{
        background: linear-gradient(90deg, #ecfdf5, #f0fdf4);
        border: 1px solid #6ee7b7;
        border-radius: 12px;
        padding: 0.7rem 1rem;
        margin: 0.25rem 0 1rem;
        font-size: 0.92rem;
        line-height: 1.5;
        color: #334155;
        box-shadow: 0 2px 8px rgba(27, 138, 90, 0.08);
    }}
    .sem-tour-badge {{
        display: inline-block;
        background: {C_PRIMARY};
        color: #fff;
        font-size: 0.72rem;
        font-weight: 700;
        padding: 0.2rem 0.55rem;
        border-radius: 999px;
        margin-right: 0.45rem;
    }}
    .sem-tour-hint {{ color: #64748b; font-size: 0.85rem; margin-left: 0.25rem; }}
    .sem-tour-where {{
        margin-top: 0.45rem;
        font-size: 0.88rem;
        color: #0f766e;
        line-height: 1.45;
    }}
    .tour-focus-banner {{
        background: linear-gradient(90deg, #fff7ed, #ffedd5);
        border: 1px solid #fb923c;
        border-radius: 10px;
        padding: 0.65rem 0.85rem;
        margin-bottom: 0.65rem;
    }}
    .tour-focus-row {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.45rem; margin-bottom: 0.35rem; }}
    .tour-focus-step {{
        background: #ea580c;
        color: #fff;
        font-size: 0.72rem;
        font-weight: 700;
        padding: 0.15rem 0.5rem;
        border-radius: 999px;
    }}
    .tour-focus-title {{ font-size: 1.05rem; font-weight: 700; color: #9a3412; }}
    .tour-focus-where, .tour-focus-action {{
        font-size: 0.88rem;
        line-height: 1.5;
        color: #431407;
        margin-top: 0.25rem;
    }}
    .tour-focus-where b, .tour-focus-action b {{ color: #c2410c; }}
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.tour-pin) {{
        background: linear-gradient(
            180deg,
            rgba(255, 251, 235, 0.95) 0%,
            var(--secondary-background-color, #ffffff) 100%
        );
    }}
    /* 深色主题（Streamlit 设置里选了 Dark 时） */
    .stApp[data-theme="dark"] .sem-step {{
        background: #1e293b;
        border-color: rgba(148, 163, 184, 0.35);
    }}
    .stApp[data-theme="dark"] .sem-step strong {{ color: #f1f5f9; }}
    .stApp[data-theme="dark"] .sem-step span {{ color: #94a3b8; }}
    .stApp[data-theme="dark"] div[data-testid="stMetric"] {{
        background: #1e293b !important;
        border-color: rgba(148, 163, 184, 0.35);
    }}
    .stApp[data-theme="dark"] div[data-testid="stMetric"] label,
    .stApp[data-theme="dark"] div[data-testid="stMetric"] label p,
    .stApp[data-theme="dark"] div[data-testid="stMetric"] [data-testid="stMetricLabel"],
    .stApp[data-theme="dark"] div[data-testid="stMetric"] [data-testid="stMetricLabel"] p {{
        color: #94a3b8 !important;
    }}
    .stApp[data-theme="dark"] div[data-testid="stMetric"] [data-testid="stMetricValue"],
    .stApp[data-theme="dark"] div[data-testid="stMetric"] [data-testid="stMetricValue"] div {{
        color: #f8fafc !important;
    }}
    .stApp[data-theme="dark"] .sem-section {{ color: #f1f5f9; }}
    .stApp[data-theme="dark"] .sem-tour-strip {{ color: #e2e8f0; }}
    .stApp[data-theme="dark"] .sem-tour-hint {{ color: #94a3b8; }}
    .demo-stage-bar {{
        display: flex;
        gap: 0.35rem;
        margin: 0.35rem 0 0.5rem;
        flex-wrap: wrap;
    }}
    .demo-stage {{
        flex: 1 1 72px;
        text-align: center;
        padding: 0.45rem 0.35rem;
        border-radius: 10px;
        background: #e2e8f0;
        color: #64748b;
        border: 2px solid transparent;
        transition: all 0.35s ease;
    }}
    .demo-stage span {{ display: block; font-weight: 800; font-size: 0.95rem; }}
    .demo-stage small {{ font-size: 0.68rem; }}
    .demo-stage-done {{
        background: #d1fae5;
        color: #065f46;
    }}
    .demo-stage-active {{
        background: #ffedd5;
        color: #9a3412;
        border-color: #ea580c;
        box-shadow: 0 0 0 2px rgba(234, 88, 12, 0.25);
    }}
    .demo-stage-cap {{
        font-size: 1.15rem;
        font-weight: 700;
        color: #0f172a;
        margin: 0.15rem 0 0.35rem;
        line-height: 1.45;
    }}
    .demo-story {{
        background: #ecfdf5;
        border: 1px solid #6ee7b7;
        border-radius: 12px;
        padding: 0.7rem 0.95rem;
        margin-bottom: 0.7rem;
        color: #064e3b;
        font-size: 0.95rem;
        line-height: 1.5;
    }}
    .demo-story b {{ color: #047857; }}
    .demo-typing {{
        background: #ecfdf5;
        border: 1px dashed {C_PRIMARY};
        border-radius: 10px;
        padding: 0.65rem 0.85rem;
        font-size: 0.95rem;
        color: #0f172a;
    }}
</style>
        """,
        unsafe_allow_html=True,
    )


def render_brand_header() -> None:
    st.markdown(
        '<div class="sem-brand">'
        "<h2>🧭 语枢 Semantica</h2>"
        "<p>用一句话查账。听不清就先问你；账里没有就说算不了；给出的数字能核对。</p>"
        "</div>",
        unsafe_allow_html=True,
    )


def render_hero() -> None:
    """Flagship positioning: data with explicit conditions for agent use."""
    st.markdown(
        """
        <div class="hero">
          <div class="hero-brand">🧭 语枢 Semantica</div>
          <h1>SQL 算对了，AI 的决策仍然可能错。</h1>
          <div class="hero-sub">
            语枢为现有数仓增加 <b>Agent 语义执行网关</b>：
            AI 取得的不只是数字，还有它的口径、版本、证据和使用条件。
          </div>
          <div class="hero-why">
            <span class="chip">① 确认意义</span>
            <span class="chip">② 携带证据</span>
            <span class="chip">③ 检查结论的使用条件</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_now_banner(kind: str, text: str) -> None:
    colors = {
        "idle": ("#ecfdf5", "#047857", "#6ee7b7"),
        "ask": ("#fff7ed", "#9a3412", "#fdba74"),
        "done": ("#eff6ff", "#1e40af", "#93c5fd"),
        "refuse": ("#fef2f2", "#991b1b", "#fca5a5"),
    }
    bg, fg, bd = colors.get(kind, colors["idle"])
    st.markdown(
        f'<div style="background:{bg};color:{fg};border:1px solid {bd};'
        f'border-radius:12px;padding:0.85rem 1rem;margin:0.4rem 0 1rem;'
        f'font-size:1.05rem;font-weight:600;line-height:1.5;">{text}</div>',
        unsafe_allow_html=True,
    )


def render_pipeline_bar() -> None:
    steps_html = "".join(
        f'<div class="sem-step"><strong>{a}</strong><span>{b}</span></div>'
        for a, b in PIPELINE_SHORT
    )
    st.markdown(f'<div class="sem-pipeline">{steps_html}</div>', unsafe_allow_html=True)


def section_title(text: str) -> None:
    st.markdown(f'<p class="sem-section">{text}</p>', unsafe_allow_html=True)


def render_beginner_intro() -> None:
    """主页面顶部：用日常比喻讲清这个演示在做什么。"""
    with st.expander("👋 导览结束后，文字版说明还在这里", expanded=False):
        st.markdown(
            """
想象你走进一家物流公司的财务室，想问一句人话：

> 「8 月华东区的 GMV 是多少？」

账本在数据库里，但你不会写查询语句（SQL）。把这句话直接丢给大模型，它常常会**猜**：
金额用哪一列、华东在哪张表、取消的订单算不算。猜错了，它仍会很自信地给你一个数字。

**语枢做的事，就是当这个翻译官：**

1. 先用公司词典（本体）把黑话翻译成明确的指标和筛选条件；
2. 遇到多种合法算法，先弹卡片问你，而不是自己挑一个；
3. 按你确认的意思写出 SQL，查出数字；
4. 把「这个数怎么来的」一起给你，方便核对。

下面这套数据是**虚构的电商履约账本**（约 5 万笔订单），「今天」固定为 **2026-09-20**。
所以你问「上个月」，系统永远理解为 2026 年 8 月，结果可以重复验证。

**建议你现在就试一次：** 往下找到「8月华东区的GMV是多少？」点一下。
黄框出现后随便选一种金额算法，再点「确认并执行」。然后打开「口径披露」，看它有没有把算法和时间写清楚。
            """
        )


def render_sidebar_guide(*, show_teaching: bool = True) -> None:
    with st.sidebar:
        st.markdown("### 📖 使用教学")
        st.markdown(
            '<div class="sem-sidebar-tip">'
            "<b>三分钟走一遍：</b><br>"
            "① 读主页面「新手先看」<br>"
            "② 点一条带颜色标签的示例题<br>"
            "③ 若出现黄框，选一个选项再点确认<br>"
            "④ 打开「口径披露」，看这个数是怎么算出来的"
            "</div>",
            unsafe_allow_html=True,
        )
        with st.expander("五个词，先认一下", expanded=False):
            st.markdown(
                """
- **数据库 / 数仓**：公司的电子账本。这里有订单、运单、商品、客户、承运商。
- **SQL**：查账本的语句。人很难手写，大模型会写，但经常写错口径。
- **本体**：公司词典。规定「超时」怎么判定、「金额」有哪几种算法、表和表怎么连接。
- **口径**：同一种业务问题的不同算法。选错口径，数字可以差很远，但看起来都很像正确答案。
- **澄清卡**：系统不确定时弹出的选择题。你选完，它才去算。
                """
            )
        with st.expander("五步分别在干什么", expanded=False):
            for title, subtitle, detail in PIPELINE_STEPS:
                st.markdown(f"**{title}**")
                st.caption(subtitle)
                st.markdown(detail)
        with st.expander("六类示例题在考什么", expanded=False):
            st.caption("这些题故意写得含糊，用来检查系统会不会乱猜。")
            for code, (name, color) in CAT_LEGEND.items():
                st.markdown(
                    f'<span class="sem-tag" style="background:{color}">{code}</span> **{name}**',
                    unsafe_allow_html=True,
                )
                st.markdown(CAT_STORIES[code])
        if show_teaching:
            with st.expander("现场教学是什么", expanded=False):
                st.markdown(
                    """
词典里一开始没有某个新词，比如「已取消订单占比」。

现场教学就是：你用一句话告诉平台这个词是什么意思，平台尝试把它变成一条可查询的指标。
它不会直接相信大模型写的公式，而要过三关：

1. **结构**：定义是否完整（叫什么、怎么算、用到哪些表）；
2. **安全**：公式里不能夹带删数据之类的危险语句；
3. **能跑**：在真实账本上试算一次，失败就拒绝入库。

通过后写入 `learned.yaml`，不用重启，马上可以再问这个词。
这一步需要在 `.env` 里配置大模型密钥；普通提问不需要密钥。
                    """
                )
        with st.expander("对照模式在比什么", expanded=False):
            st.markdown(
                """
打开「裸 LLM 对照」后，同一个问题会左右并排：

- **左边 · 语枢**：先对齐词典，必要时问你，再给数字和口径说明。
- **右边 · 裸模型**：只把表结构交给大模型，让它直接写 SQL。没有词典，也不会问你。

两边数字经常不一样。这就是这个项目想说明的事：
**模型会写 SQL，但不知道你们公司这句话到底指什么。**
对照需要配置 `LLM_API_KEY`。
                """
            )
        st.divider()
        st.caption("左侧导航「战绩看板」用实验图说明：为什么不能把词典直接塞给模型。")


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
