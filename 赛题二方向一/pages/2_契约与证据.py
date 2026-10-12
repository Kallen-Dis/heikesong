"""A reviewable two-phase data interface for people and agents."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st
from src.contracts import QueryGateway
from src.db import connect
from src.loop import QueryLoop
from src.llm import get_client
from src.agent_workflow import propose_query
from ui_helpers import inject_theme

st.set_page_config(page_title="契约与证据 · 语枢", page_icon="🔎", layout="wide")
inject_theme()
st.title("每个答案，都有使用条件")
st.caption("先确认语义契约，再读取数据；证据包保存完整结果，可在同一环境下重放。数据为合成账本。")

@st.cache_resource
def runtime():
    return QueryLoop(connect())

loop = runtime()
role = st.selectbox("演示数据范围", ["全区域聚合", "华东区域分析员"])
st.caption("区域范围由服务端配置执行；此处是本地角色演示，企业身份认证仍需对接。")
gateway = QueryGateway(loop, ("华东",) if role == "华东区域分析员" else None)

with st.expander("可选：让大模型提出查询计划"):
    st.caption("模型负责规划；下方契约负责校验与执行。规划文本必须核对，可能遗漏条件。需要已配置的 LLM API。")
    goal = st.text_input("想解决的业务目标", value="了解8月华东区成交情况", key="agent_goal")
    if st.button("让数据 Agent 提出草案"):
        st.session_state.agent_proposal = propose_query(get_client(), goal, loop.aligner.metrics)
    proposal = st.session_state.get("agent_proposal")
    if proposal:
        if proposal["type"] == "proposal":
            st.json(proposal)
            st.caption("核对原始目标与草案是否一致，再将 query 填入下面的业务问题；草案没有执行。")
        else:
            st.info(proposal["text"])

with st.form("prepare"):
    question = st.text_input("业务问题", value="8月华东区的GMV是多少？")
    prepare = st.form_submit_button("生成契约", type="primary")
if prepare:
    st.session_state.contract_ack = False
    st.session_state.contract_nonce = st.session_state.get("contract_nonce", 0) + 1
    st.session_state.contract_preview = gateway.preview(question)
    st.session_state.contract_question = question
    st.session_state.contract_role = role
    st.session_state.pop("contract_answer", None)
    st.session_state.pop("contract_replay", None)

preview = st.session_state.get("contract_preview")
if preview and st.session_state.get("contract_role") != role:
    st.info("角色范围发生变化，请重新生成契约。")
    preview = None
if preview and preview["type"] == "clarification":
    st.subheader("先确定业务含义")
    with st.form("contract_choices"):
        choices = {}
        for point in preview["points"]:
            labels = [opt["label"] for opt in point["options"]]
            choices[point["id"]] = st.radio(point["prompt"], range(len(labels)),
                index=None, format_func=lambda i, labels=labels: labels[i],
                key=f"contract_choice_{st.session_state.get('contract_nonce', 0)}_{point['id']}")
        resolve = st.form_submit_button("按已选口径生成", disabled=any(i is None for i in choices.values()))
    if resolve:
        st.session_state.contract_preview = gateway.preview(st.session_state.contract_question, choices)
        st.rerun()
elif preview and preview["type"] == "ready":
    contract = preview["contract"]
    meaning = contract["meaning"]
    c1, c2, c3 = st.columns(3)
    c1.metric("指标", meaning["metric"] or "时长阈值")
    c2.metric("统计粒度", meaning["grain"])
    c3.metric("数据截止日", contract["revisions"]["dataset_end"])
    with st.container(border=True):
        st.markdown("**本次使用条件**")
        for line in contract["disclosure"]:
            st.write(line)
        st.caption("授权范围：" + str(contract["policy"]["allowed_regions"] or "所有区域聚合") +
                   " · 契约 " + contract["contract_id"][:12])
    with st.expander("查看完整契约和来源"):
        st.json(contract)
    acknowledged = st.checkbox("我已核对口径、时间与筛选条件", key="contract_ack")
    if st.button("执行已确认契约", type="primary", disabled=not acknowledged):
        st.session_state.contract_answer = gateway.execute(contract)
        st.session_state.pop("contract_replay", None)
elif preview:
    st.warning(preview.get("text", "计划被阻断"))
    with st.expander("阻断详情"):
        st.json(preview)

answer = st.session_state.get("contract_answer") if preview else None
if answer:
    if answer["type"] == "answer":
        st.subheader(answer["text"])
        receipt = answer["evidence"]
        st.dataframe(pd.DataFrame(receipt["result"]["rows"]), hide_index=True, width="stretch")
        left, right = st.columns(2)
        left.download_button("下载完整证据包", json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False),
                             file_name="semantica-evidence.json", mime="application/json")
        if right.button("在当前环境重放证据"):
            st.session_state.contract_replay = gateway.replay(receipt)
        replay = st.session_state.get("contract_replay")
        if replay:
            (st.success if replay.get("matches") else st.warning)(replay["text"])
        with st.expander("证据包：结果、版本、SQL参数与限制"):
            st.json(receipt)
        st.caption("证据包不包含原始数据快照；哈希用于检测一致性，不代表数字签名或来源真实性。")
    else:
        st.warning(answer.get("text", "执行被阻断"))

st.divider()
st.subheader("试试边界")
st.markdown("选择华东分析员后，查询华南会被阻断；未定义的退货率会拒答；增长或多时间窗口不会被偷换成一个总量。")
st.caption("MCP 客户端同样调用 preview_query → execute_contract → replay_evidence。")
