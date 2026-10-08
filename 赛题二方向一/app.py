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
from tour import is_clarification, render_coach
from ui_helpers import (
    EXAMPLE_ITEMS,
    STARTER_CARDS,
    cat_badge,
    inject_theme,
    render_hero,
    render_now_banner,
    render_trust,
    section_title,
)

ROOT = Path(__file__).resolve().parent

st.set_page_config(
    page_title="语枢 Semantica",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_theme()


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

if "history" not in st.session_state:
    st.session_state.history = []
if "pending" not in st.session_state:
    st.session_state.pending = None
# 旧会话里可能把「还没选完的澄清」写进了历史，渲染时会报错。这里拆回待澄清。
_kept = []
for _entry in st.session_state.history:
    _ans = _entry.get("ans")
    if is_clarification(_ans):
        if st.session_state.pending is None:
            st.session_state.pending = {"question": _entry.get("q") or _ans.question, "clar": _ans}
        continue
    _kept.append(_entry)
st.session_state.history = _kept
st.session_state.setdefault("baseline_on", False)
st.session_state.auto_demo_on = False
st.session_state.tour_step = None
render_coach()

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


# ---------------------------------------------------------------- 页头（结论先行）

render_hero()

with st.expander("关于这套演示账本", expanded=False):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("账本截止日", meta["dataset_end"])
    c2.metric("词典里的事物", meta["concepts"])
    c3.metric("已经会算的指标", meta["metrics"])
    c4.metric("订单笔数", f"{meta['orders']:,}")

pending = st.session_state.pending
last = st.session_state.history[-1] if st.session_state.history else None
if pending and is_clarification(pending.get("clar")):
    render_now_banner("ask", "这句话有歧义，需要先确认口径再查询。")
elif last and getattr(last.get("ans"), "type", None) == "insufficient":
    render_now_banner("refuse", "账本中没有这项数据，因此拒绝回答。")
elif last:
    render_now_banner("done", "已查询完成，结果与口径说明如下。")


def make_entry(q: str, ans) -> dict:
    entry = {"q": q, "ans": ans, "baseline": None, "clarified": False}
    if st.session_state.get("baseline_on") and client.available:
        entry["baseline"] = runner.ask(q)
    return entry


def render_answer(ans) -> None:
    if is_clarification(ans) or not hasattr(ans, "type"):
        return
    if ans.type == "answer":
        st.markdown(f"### ✅ {ans.text}")
        render_trust(ans.trust)
        if ans.disclosure:
            with st.expander("📎 这个数是怎么来的（口径披露）", expanded=True):
                st.markdown(
                    "把下面几条和你心里的算法对一下："
                    "统计的是哪几天、用的是哪种金额或比率、有没有限定地区或品牌。"
                    "对得上，这个数才算数。"
                )
                for line in ans.disclosure:
                    st.markdown(f"- {line}")
        if ans.sql:
            with st.expander("🧩 它实际执行的查询语句（SQL）", expanded=False):
                st.caption(
                    "这是翻译后的查账语句，给会 SQL 的人核对用。"
                    "真正执行时，日期和筛选值是单独绑定的，不会把原文直接拼进去。"
                )
                st.code(ans.sql, language="sql")
    elif ans.type == "insufficient":
        st.warning(f"🛑 {ans.text}")
        st.caption(
            "系统拒绝回答。这套账本里没有对应的数据（例如没有退货、成本或库存）。"
            "编一个数字看起来更「有用」，但那个数字是假的。说「算不了」才是这里要展示的能力。"
        )
    else:
        st.error(f"⚠️ {ans.text}")


def render_entry(entry: dict) -> None:
    st.markdown(f"#### 🔍 {entry['q']}")
    if entry.get("clarified"):
        st.caption("✍️ 你已确认澄清选项，以下结果对应该口径")
    bl = entry.get("baseline")
    if st.session_state.get("baseline_on") and bl is not None:
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
            st.caption(
                "右边只看表结构就写 SQL：经常用错列、连错表，或把不存在的状态写成英文。"
                "而且它不会告诉你用的是哪种算法。"
            )
    else:
        render_answer(entry["ans"])


def handle_query(q: str) -> None:
    ans = loop.ask(q)
    st.session_state.clar_nonce = st.session_state.get("clar_nonce", 0) + 1
    if is_clarification(ans):
        st.session_state.pending = {"question": q, "clar": ans}
        st.session_state.tour_just_asked = True
        return
    st.session_state.pending = None
    st.session_state.history.append(make_entry(q, ans))
    st.session_state.tour_just_asked = True


# ---------------------------------------------------------------- 示例

section_title("示例")
cols = st.columns(3)
for i, card in enumerate(STARTER_CARDS):
    with cols[i]:
        with st.container(border=True):
            st.markdown(f"**{card['will']}**")
            st.caption(card["why"])
            if st.button(card["q"], key=f"start_{i}", width="stretch", type="primary" if i == 0 else "secondary"):
                handle_query(card["q"])
                st.rerun()

with st.expander("更多例题", expanded=False):
    for i, item in enumerate(EXAMPLE_ITEMS):
        st.markdown(f"{cat_badge(item['cat'])} {item['hint']}", unsafe_allow_html=True)
        if st.button(item["q"], key=f"ex_{i}", width="stretch"):
            handle_query(item["q"])
            st.rerun()

pending = st.session_state.pending
if pending and is_clarification(pending.get("clar")):
    clar: Clarification = pending["clar"]
    st.markdown(f"#### 你刚才问：{pending['question']}")
    st.markdown(
        '<div class="sem-clarify-box">'
        "这句话里有说不清的地方，所以<strong>先问你再查</strong>。"
        "下面每一项都是合法算法，不是对错题。你选哪一个，就按哪一个算。"
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
        if st.button("按这个去查", type="primary"):
            ans = loop.resolve(clar, choices)
            if is_clarification(ans):
                st.session_state.pending = {"question": pending["question"], "clar": ans}
                st.session_state.clar_nonce = clar_nonce + 1
            else:
                entry = make_entry(pending["question"], ans)
                entry["clarified"] = True
                st.session_state.history.append(entry)
                st.session_state.pending = None
            st.rerun()
elif pending:
    st.session_state.pending = None

st.divider()

if st.session_state.history:
    section_title("结果")
    for entry in st.session_state.history:
        with st.container(border=True):
            render_entry(entry)

section_title("更多功能")
mode_col, hint_col = st.columns([1.2, 2.8])
with mode_col:
    st.session_state["baseline_on"] = st.toggle(
        "🐒 裸 LLM 对照模式",
        value=st.session_state["baseline_on"],
        help="同一问题左右对比：语枢 vs 把 DDL 直接给大模型",
    )
with hint_col:
    baseline_on = st.session_state["baseline_on"]
    if baseline_on and not client.available:
        st.warning("对照模式需要 LLM_API_KEY（复制 .env.example 为 .env 并填写后重启）", icon="⚠️")
    elif baseline_on:
        st.success(f"对照已开：右侧为 {client.model} 裸 SQL 生成", icon="🤖")
    else:
        st.caption("含糊会先问你；没有的数据会拒答。对照模式需要 API Key。")
with st.expander("🧪 现场教学：教平台认识一个新词（需要大模型密钥）", expanded=False):
            st.info(
                "给平台一个新说法 + 一句定义，通过校验后写入词典，马上可问。需要 LLM API Key。",
                icon="💡",
            )
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

q = st.chat_input("用一句人话问数据，例如：上个月的履约超时率是多少？")
if q:
    handle_query(q.strip())
    st.rerun()
