# -*- coding: utf-8 -*-
"""语枢 Semantica · 演示界面（Streamlit）。

运行：streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml
import streamlit as st

from src.baseline import BaselineRunner
from src.cache import SemanticCache
from src.db import ONTOLOGY_DIR, connect, ddl_text
from src.llm import get_client
from src.loop import Clarification, QueryLoop
from src.ontology_pipeline import apply_metric, draft_metric, validate_metric
from ui_helpers import (
    EXAMPLE_ITEMS,
    cat_badge,
    inject_theme,
    render_pipeline_bar,
    render_sidebar_guide,
    render_trust,
)

ROOT = Path(__file__).resolve().parent

st.set_page_config(
    page_title="语枢 Semantica",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_theme()
render_sidebar_guide(show_teaching=True)


@st.cache_resource
def get_runtime():
    conn = connect()
    loop = QueryLoop(
        conn,
        cache=SemanticCache(),
        feedback_path=ROOT / "ontology" / "feedback_log.jsonl",
    )
    client = get_client()
    runner = BaselineRunner(conn, client)
    meta = {
        "dataset_end": conn.execute("SELECT value FROM meta WHERE key = 'dataset_end'").fetchone()[0],
        "orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "shipments": conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0],
        "metrics": len(loop.aligner.metrics),
        "concepts": len(
            yaml.safe_load((ONTOLOGY_DIR / "ontology.yaml").read_text(encoding="utf-8"))["concepts"]
        ),
    }
    return conn, loop, client, runner, meta


conn, loop, client, runner, meta = get_runtime()

PRESETS = [
    ("已取消订单占比", "已取消状态的订单占全部订单的比例"),
    ("高评分承运商占比", "服务评分不低于 4.5 的承运商承运的运单占全部运单的比例"),
    ("华东区订单占比", "下单客户位于华东区域的订单占全部订单的比例"),
]


def teach_term(term: str, desc: str) -> None:
    if not client.available:
        st.error("需要配置 LLM_API_KEY（.env）才能生成草稿")
        return
    with st.status(f"正在教「{term}」…", expanded=True) as status:
        try:
            st.write("① LLM 正在生成指标草稿（含 SQL 口径）…")
            mid, defn = draft_metric(client, term, desc, [], ddl_text(conn), loop.aligner.metrics)
        except Exception as e:  # noqa: BLE001
            status.update(label="草稿生成失败", state="error")
            st.error(str(e))
            return
        st.write(f"→ 生成指标 ID：`{mid}`")
        st.write("② 三关校验（结构 / 安全 / 可执行）…")
        ok, info = validate_metric(mid, defn, conn, loop.aligner.metrics)
        if not ok:
            status.update(label="校验未通过（可修改定义后重试）", state="error")
            st.warning(info)
            st.code(yaml.safe_dump({mid: defn}, allow_unicode=True, sort_keys=False), language="yaml")
            return
        st.write("→ ✅ 校验通过（已在真库上试跑）")
        st.code(info, language="sql")
        if mid in loop.aligner.metrics:
            st.write("③ 指标已在本体中，跳过发布，直接进入验证")
        else:
            apply_metric(mid, defn)
            st.write("③ 已写入 learned.yaml —— 热加载生效（无需重启）")
        st.write("④ 即时验证…")
        q = f"8月{term}是多少？"
        ans = loop.ask(q, auto_resolve=True)
        if isinstance(ans, Clarification):
            st.write(f"⚠️「{q}」触发了澄清卡：建议补充同义词或调整术语表述")
        elif ans.type == "answer":
            st.write(f"🎯「{q}」→ **{ans.text}**")
            for line in ans.disclosure or []:
                st.write(f"　· {line}")
        else:
            st.write(f"⚠️ {ans.text}")
        status.update(label=f"教学完成 ✅：{term}", state="complete")
    with st.expander("查看生成的指标定义（YAML）"):
        st.code(yaml.safe_dump({mid: defn}, allow_unicode=True, sort_keys=False), language="yaml")


# ---------------------------------------------------------------- 页头

st.title("🧭 语枢 Semantica")
st.caption(
    "语义编译器演示 · 左侧 **📖 使用教学** 有分步说明 · "
    "数据基准日固定为 **2026-09-20**，保证评测可复现"
)
render_pipeline_bar()

m1, m2, m3, m4 = st.columns(4)
m1.metric("数据截止", meta["dataset_end"], help="相对时间（上月/近7天）均以此日为锚")
m2.metric("本体概念", meta["concepts"], help="ontology.yaml 中的业务实体")
m3.metric("指标口径", meta["metrics"], help="metrics.yaml + 现场教学的 learned 指标")
m4.metric("订单规模", f"{meta['orders']:,} 行", help=f"运单 {meta['shipments']:,} 行")

# ---------------------------------------------------------------- 现场教学

with st.expander("🧪 现场教学（活体本体：新术语 30 秒内可查）", expanded=False):
    st.info(
        "**教学讲解**：企业里总有新黑话。把「术语 + 一句定义」交给平台，"
        "LLM 生成指标草稿后必须通过**结构 / 注入安全 / 真库试跑**三关，"
        "才写入 `learned.yaml` 并热加载——避免「随口编一个 SQL 就上线」。",
        icon="💡",
    )
    st.caption("流程：新术语 + 定义 → LLM 草稿 → 三关校验 → 热加载发布 → 即时提问验证")
    st.session_state.setdefault("teach_term", "")
    st.session_state.setdefault("teach_desc", "")
    pc = st.columns(len(PRESETS))
    for i, (t, d) in enumerate(PRESETS):
        if pc[i].button(f"示例：{t}", key=f"preset_{i}", width="stretch"):
            st.session_state["teach_term"] = t
            st.session_state["teach_desc"] = d
            st.rerun()
    tc1, tc2 = st.columns([1, 2])
    term_in = tc1.text_input("新术语", key="teach_term", placeholder="例如：已取消订单占比")
    desc_in = tc2.text_area(
        "业务定义（一句人话）",
        key="teach_desc",
        height=68,
        placeholder="例如：已取消状态的订单占全部订单的比例",
    )
    if st.button(
        "🚀 教会平台（生成 → 校验 → 发布 → 验证）",
        type="primary",
        disabled=not (term_in.strip() and desc_in.strip()),
    ):
        teach_term(term_in.strip(), desc_in.strip())
    _learned = ONTOLOGY_DIR / "learned.yaml"
    if _learned.exists():
        _data = yaml.safe_load(_learned.read_text(encoding="utf-8")) or {}
        _names = [v.get("zh", k) for k, v in (_data.get("metrics") or {}).items()]
        if _names:
            st.caption("已教会术语：" + "、".join(_names))

# ---------------------------------------------------------------- 查询模式

st.subheader("💬 向数据提问")
mode_col, hint_col = st.columns([1.2, 2.8])
with mode_col:
    baseline_on = st.toggle(
        "🐒 裸 LLM 对照模式",
        value=False,
        help="同一问题左右对比：语枢 vs 把 DDL 直接给大模型",
    )
with hint_col:
    if baseline_on and not client.available:
        st.warning("对照模式需要 LLM_API_KEY（复制 .env.example 为 .env 并填写后重启）", icon="⚠️")
    elif baseline_on:
        st.success(f"对照已开：右侧为 {client.model} 裸 SQL 生成（无澄清、无披露）", icon="🤖")
    else:
        st.info(
            "**语枢模式**（默认）：离线可用，无需 API Key。"
            "歧义会先出澄清卡；陷阱题会拒答而非瞎编数字。",
            icon="🧭",
        )

if "history" not in st.session_state:
    st.session_state.history = []
if "pending" not in st.session_state:
    st.session_state.pending = None


def make_entry(q: str, ans) -> dict:
    entry = {"q": q, "ans": ans, "baseline": None, "clarified": False}
    if baseline_on and client.available:
        entry["baseline"] = runner.ask(q)
    return entry


def render_answer(ans) -> None:
    if ans.type == "answer":
        st.markdown(f"### ✅ {ans.text}")
        render_trust(ans.trust)
        if ans.disclosure:
            with st.expander("📎 口径披露（为什么是这个数？）", expanded=True):
                st.markdown("**教学提示**：核对时间窗口、指标口径、筛选条件是否与你的业务理解一致。")
                for line in ans.disclosure:
                    st.markdown(f"- {line}")
        if ans.sql:
            with st.expander("🧩 编译 SQL（语义计划 → 可执行 SQL）", expanded=False):
                st.caption("展示 SQL 仅便于审计；执行时使用参数绑定，避免注入风险。")
                st.code(ans.sql, language="sql")
    elif ans.type == "insufficient":
        st.warning(f"🛑 {ans.text}")
        st.caption("这是**陷阱题/缺数据**的正确行为：诚实拒答比编造数字更值得信任。")
    else:
        st.error(f"⚠️ {ans.text}")


def render_entry(entry: dict) -> None:
    st.markdown(f"#### 🔍 {entry['q']}")
    if entry.get("clarified"):
        st.caption("✍️ 你已确认澄清选项，以下结果对应该口径")
    bl = entry.get("baseline")
    if baseline_on and bl is not None:
        left, right = st.columns(2, gap="medium")
        with left:
            st.markdown("**🧭 语枢（语义编译器）**")
            render_answer(entry["ans"])
        with right:
            st.markdown(f"**🐒 裸 LLM 直连（{client.model}）**")
            if bl.get("error"):
                st.error(bl["error"])
                if bl.get("sql"):
                    st.code(bl["sql"], language="sql")
            else:
                st.markdown(f"### {bl['value']}")
                st.code(bl.get("sql", ""), language="sql")
            st.caption("无本体 → 常出现口径错误、JOIN 缺失或幻觉枚举，且**无披露**")
    else:
        render_answer(entry["ans"])


def handle_query(q: str) -> None:
    ans = loop.ask(q)
    if isinstance(ans, Clarification):
        st.session_state.pending = {"question": q, "clar": ans}
        st.session_state.clar_nonce = st.session_state.get("clar_nonce", 0) + 1
        return
    st.session_state.pending = None
    st.session_state.history.append(make_entry(q, ans))


# ---------------------------------------------------------------- 示例题

st.markdown("**一键示例（AmbiQuery 六类考点）**")
cols = st.columns(2)
for i, item in enumerate(EXAMPLE_ITEMS):
    with cols[i % 2]:
        st.markdown(f"{cat_badge(item['cat'])} {item['hint']}", unsafe_allow_html=True)
        if st.button(item["q"], key=f"ex_{i}", width="stretch"):
            handle_query(item["q"])
            st.rerun()

st.divider()

for entry in st.session_state.history:
    with st.container(border=True):
        render_entry(entry)

pending = st.session_state.pending
if pending:
    clar: Clarification = pending["clar"]
    st.markdown(f"#### ❓ 待澄清：{pending['question']}")
    st.markdown(
        '<div class="sem-clarify-box">'
        "<b>教学讲解</b>：这不是系统「不会」，而是<strong>主动避免猜错</strong>。"
        "企业数据里同一词常有多种合法口径；选一项后，编译器才按你的选择生成 SQL。"
        "</div>",
        unsafe_allow_html=True,
    )
    clar_nonce = st.session_state.get("clar_nonce", 0)
    with st.container(border=True):
        choices: dict[str, int] = {}
        for point in clar.points:
            labels = [o["label"] for o in point.options]
            st.markdown(f"**{point.prompt}**")
            idx = st.radio(
                "选项",
                options=range(len(labels)),
                format_func=lambda i, ls=labels: ls[i],
                key=f"clar_{clar_nonce}_{point.id}",
                label_visibility="collapsed",
            )
            choices[point.id] = idx
        if st.button("✅ 确认并执行", type="primary"):
            ans = loop.resolve(clar, choices)
            entry = make_entry(pending["question"], ans)
            entry["clarified"] = True
            st.session_state.history.append(entry)
            st.session_state.pending = None
            st.rerun()

q = st.chat_input("用一句人话问数据，例如：上个月的履约超时率是多少？")
if q:
    handle_query(q.strip())
    st.rerun()
