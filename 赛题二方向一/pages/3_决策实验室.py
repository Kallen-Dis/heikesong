"""物流诊断及有限情景推演：不调用模型 API，不执行业务操作。"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import altair as alt
import pandas as pd
import streamlit as st

from src.db import connect
from src.decision_lab import diagnose_carriers, simulate_intervention
from ui_helpers import inject_theme, section_title

st.set_page_config(page_title="决策实验室 · 语枢", page_icon="🧪", layout="wide")
inject_theme()
st.title("从超时诊断，到有边界的方案比较")
st.caption("合成物流数据 · 已妥投口径 · 无需 API · 只读分析，未执行调度或下单")
st.info("先比较超时量与超时率，再讨论预算。情景假设未来有相同规模、相同历史超时率的可比队列；结果是条件模拟，不是预测，也不能证明因果。")

try:
    conn = connect()
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    asof = date.fromisoformat(meta['dataset_end'])
    dataset_start = date.fromisoformat(meta.get('dataset_start', meta['dataset_end']))
    regions = [row[0] for row in conn.execute("SELECT DISTINCT region FROM customers ORDER BY region").fetchall() if row[0]]
except Exception as exc:
    st.error(f"无法读取演示数据：{exc}")
    st.stop()

with st.sidebar:
    st.subheader("观察范围")
    st.caption(f"数据截止日：{asof}；发货日期包含起止两天。")
    default_start = max(dataset_start, date(asof.year, max(1, asof.month - 1), 1))
    start = st.date_input("发货开始日期", default_start, min_value=dataset_start, max_value=asof)
    end = st.date_input("发货结束日期", asof, min_value=dataset_start, max_value=asof)
    selected_region = st.selectbox("客户区域", ["全部区域"] + regions,
                                   index=(["全部区域"] + regions).index('华东') if '华东' in regions else 0)
    by_region = st.checkbox("承运商 × 客户区域分组", value=False)
    threshold = st.number_input("自动纳入干预的最少已妥投数量", min_value=1, value=30, step=1)
    st.divider()
    st.subheader("干预假设 · 由你提供")
    coverage = st.slider("覆盖比例", min_value=0.0, max_value=1.0, value=0.5, step=0.05)
    effectiveness = st.slider("有效率：相对降低超时风险", min_value=0.0, max_value=1.0, value=0.3, step=0.05)
    unit_cost = st.number_input("每覆盖一票成本（元）", min_value=0.0, value=5.0, step=1.0)
    budget = st.number_input("可用预算（元）", min_value=0.0, value=1000.0, step=100.0)
    st.caption("成本和有效率来自你的假设，数据库没有提供或验证这些值。")

try:
    result = diagnose_carriers(conn, start, end,
                              region=None if selected_region == '全部区域' else selected_region,
                              group_by_region=by_region, min_sample=int(threshold), coverage=coverage,
                              effectiveness=effectiveness, cost_per_covered_shipment=unit_cost, budget=budget)
finally:
    conn.close()

if result['status'] != 'ok':
    st.error(result['reason'])
    with st.expander("查看阻断证据"):
        st.json(result)
    st.download_button("导出阻断证据 JSON", json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
                       file_name="semantica-decision-blocked.json", mime="application/json")
    st.stop()

overall = result['overall']
base = result['simulation']['scenarios']['base']
priority = result['priority']
if priority and base['expected_avoided_delays'] > 0:
    funded = next(a for a in result['simulation']['allocations'] if a['covered_shipments'] > 0)
    name = funded['carrier_name']
    qualifier = f" · {funded['region']}" if funded['region'] else ''
    st.success(f"在当前假设的单位收益排序中，预算优先覆盖 {name}{qualifier}。预算共覆盖 {base['covered_shipments']:,} 票，"
               f"模型期望减少 {base['expected_avoided_delays']:.1f} 次超时；这是待验证的方案，不是改善承诺。")
else:
    st.warning("当前条件没有可计算的改善效果：检查预算、覆盖率、有效率及样本阈值。观察结果仍可复核。")

c1, c2, c3, c4 = st.columns(4)
c1.metric("已妥投运单", f"{overall['delivered_count']:,}")
c2.metric("已妥投超时率", f"{overall['delay_rate']:.1%}")
c3.metric("运输未完成", f"{overall['in_transit_count']:,}", f"占全部 {overall['in_transit_share']:.1%}", delta_color="off")
c4.metric("条件模拟：期望避免超时", f"{base['expected_avoided_delays']:.1f} 次")
for warning in result['warnings']:
    st.caption(warning)

section_title("先看规模，也看比例")
records = []
for g in result['groups']:
    interval = g['wilson95']
    records.append({"分组": g['carrier_name'] + (f" · {g['region']}" if g['region'] else ''),
                    "已妥投": g['delivered_count'], "超时量": g['delayed_count'],
                    "超时率": g['delay_rate'], "下界": interval[0] if interval else None,
                    "上界": interval[1] if interval else None,
                    "样本判断": "可纳入干预" if g['eligible_for_intervention'] else "小样本：仅观察",
                    "未完成": g['in_transit_count']})
frame = pd.DataFrame(records)
order = frame['分组'].tolist()
rates = alt.Chart(frame).encode(y=alt.Y('分组:N', sort=order, title=None))
points = rates.mark_circle(size=90).encode(x=alt.X('超时率:Q', axis=alt.Axis(format='.0%'), title='已妥投中的超时比例'),
    color=alt.Color('样本判断:N', scale=alt.Scale(domain=['可纳入干预', '小样本：仅观察'], range=['#1b8a5a', '#d97706'])),
    tooltip=['分组:N', '已妥投:Q', alt.Tooltip('超时率:Q', format='.1%'), '样本判断:N'])
intervals = rates.mark_rule(color='#64748b').encode(x='下界:Q', x2='上界:Q')
reference = alt.Chart(pd.DataFrame([{'总体': overall['delay_rate']}])).mark_rule(strokeDash=[4, 4], color='#475569').encode(x='总体:Q')
bars = alt.Chart(frame).mark_bar(color='#1b8a5a').encode(
    y=alt.Y('分组:N', sort=order, title=None), x=alt.X('超时量:Q', title='超时运单数量'),
    tooltip=['分组:N', '超时量:Q', '已妥投:Q', '未完成:Q'])
height = max(200, len(records) * 29)
st.altair_chart(alt.hconcat((intervals + points + reference).properties(width=340, height=height),
                          bars.properties(width=300, height=height)).resolve_scale(color='independent'),
                use_container_width=True)
st.caption("左图横线为 Wilson 95% 区间，虚线为所选范围加权总体率。高率小样本仅展示，不自动纳入干预；区间重叠或差异均不构成因果证明。")
st.caption("诊断按超时量观察问题规模；有限预算按单票期望收益分配。当前同成本、同有效率假设下，分配顺序为合格组超时率降序。")
st.dataframe(frame[['分组', '已妥投', '超时量', '超时率', '未完成', '样本判断']], hide_index=True,
             use_container_width=True, column_config={'超时率': st.column_config.NumberColumn(format='%.3f')})

section_title("预算变化，方案的条件结果怎样变化")
curve = []
maximum = max(budget * 2, sum(g['delivered_count'] for g in result['groups']) * coverage * unit_cost, 1)
for amount in sorted(set([maximum * i / 20 for i in range(21)] + [budget])):
    sim = simulate_intervention(result['groups'], coverage=coverage, effectiveness=effectiveness,
                                cost_per_covered_shipment=unit_cost, budget=amount)
    for scenario_name, label in [('worst', '有效率 -20%'), ('base', '基准假设'), ('best', '有效率 +20%（上限100%）')]:
        curve.append({'预算（元）': amount, '期望避免超时（次）': sim['scenarios'][scenario_name]['expected_avoided_delays'], '情景': label})
chart = alt.Chart(pd.DataFrame(curve)).mark_line().encode(
    x=alt.X('预算（元）:Q'), y=alt.Y('期望避免超时（次）:Q'),
    color=alt.Color('情景:N', scale=alt.Scale(range=['#1b8a5a', '#94a3b8', '#d97706'])),
    tooltip=[alt.Tooltip('预算（元）:Q', format='.0f'), alt.Tooltip('期望避免超时（次）:Q', format='.2f'), '情景:N']).properties(height=250)
st.altair_chart(chart, use_container_width=True)
st.caption("这是有效率假设的 ±20% 敏感性范围，不是预测区间。覆盖量按整票向下取整；多个组共享预算。")
left, middle, right = st.columns(3)
left.metric("预算内预计成本", f"¥{base['estimated_cost']:,.2f}")
middle.metric("未使用预算", f"¥{result['simulation']['unspent_budget']:,.2f}")
breakeven = base['breakeven_value_per_avoided_delay']
right.metric("每避免一次超时的盈亏平衡价值", f"¥{breakeven:,.2f}" if breakeven is not None else "无法确定")
st.caption("盈亏平衡价值 = 成本 / 模型期望避免次数。只有每次避免超时的实际价值高于它，且假设成立，才可能覆盖输入成本。")

with st.expander("公式、假设与限制 · 可复核"):
    st.json({'scope': result['scope'], 'assumptions': result['assumptions'], 'formula': result['formula']})
    for limitation in result['limitations']:
        st.write(f"• {limitation}")
    st.write("预算分配是优先级启发式，不声称最优调度。")
with st.expander("已执行 SQL 与绑定参数"):
    for query in result['executed_queries']:
        st.code(query['sql'], language='sql')
        st.json(query['parameters'])
st.download_button("导出完整决策证据 JSON", json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
                   file_name='semantica-carrier-decision.json', mime='application/json', type='primary')
