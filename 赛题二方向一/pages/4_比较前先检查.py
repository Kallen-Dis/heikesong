"""A reproducible composition reversal; no API, warehouse writes or causal advice."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import altair as alt
import pandas as pd
import streamlit as st

from src.comparability import SYNTHETIC_EXAMPLE, compare_carriers
from ui_helpers import inject_theme, section_title

st.set_page_config(page_title="比较前先检查 · 语枢", page_icon="⚖️", layout="wide")
inject_theme()
st.title("SQL 算对了，结论仍会错")
st.caption("显式合成反例 · A/B 不对应真实承运商 · 所有比例由原始计数计算 · 未调用 SQL 或模型 API")
st.info("两个承运商的区域业务占比不同。正确的汇总数字，仍可能给出与分层观察相反的排名。语枢先检查是否可比，再说明权重，并阻断因果建议。")

records = copy.deepcopy(SYNTHETIC_EXAMPLE)
raw = compare_carriers(records)
carriers = raw['carriers']
pooled = raw['raw_pooled_rates']
low, high = sorted(carriers, key=lambda c: pooled[c])
st.warning(f"只看总体：{low} 的超时率 {pooled[low]:.1%}，低于 {high} 的 {pooled[high]:.1%}。"
           "这描述了不同业务构成下的汇总结果，不能据此决定更换承运商。")

section_title("第一眼看到的总体，混入了不同的区域占比")
chart_frame = pd.DataFrame([{'承运商': c, '总体超时率': pooled[c],
                             '已妥投': raw['pooled_counts'][c]['delivered'],
                             '超时量': raw['pooled_counts'][c]['delayed']} for c in carriers])
bars = alt.Chart(chart_frame).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, size=85).encode(
    x=alt.X('承运商:N', title=None), y=alt.Y('总体超时率:Q', axis=alt.Axis(format='.0%')),
    color=alt.Color('承运商:N', scale=alt.Scale(range=['#1b8a5a', '#64748b']), legend=None),
    tooltip=['承运商:N', alt.Tooltip('总体超时率:Q', format='.1%'), '已妥投:Q', '超时量:Q'])
labels = bars.mark_text(dy=-10, color='#334155').encode(text=alt.Text('总体超时率:Q', format='.1%'))
st.altair_chart((bars + labels).properties(height=210), use_container_width=True)

section_title("拆开区域，比较的是怎样的业务？")
layered = []
for row in raw['by_region']:
    display = {'区域': row['region']}
    for c in carriers:
        display[f'{c} 已妥投'] = row['counts'][c]['delivered']
        display[f'{c} 超时量'] = row['counts'][c]['delayed']
        display[f'{c} 超时率'] = f"{row['rates'][c]:.1%}"
        display[f'{c} 区域占比'] = f"{row['observed_mix'][c]:.0%}"
    layered.append(display)
st.dataframe(pd.DataFrame(layered), hide_index=True, use_container_width=True)
first, second = carriers
first_higher = all(row['rates'][first] > row['rates'][second] for row in raw['by_region'])
if first_higher:
    st.write(f"在每一个共同区域，{first} 的观察超时率都高于 {second}。"
             "但两者分布在高风险区域的业务量不同，总体顺序因此可以相反。这是构成差异，不是因果结论。")
st.caption("检查通过：恰好两个承运商、每个承运商-区域唯一、区域共同支持、每组正分母。没有默认采用等权。")

section_title("声明目标构成，才计算标准化比较")
st.caption("滑块先给出候选权重。选择业务理由并提交后，两个承运商才使用同一套权重。")
with st.form('common_region_weight_declaration'):
    east_weight = st.slider("公共权重：华东", min_value=0.0, max_value=1.0, value=.5, step=.05)
    st.caption("华南使用 1 − 华东权重。0 权重也必须保留完整共同区域支持。")
    reason = st.selectbox('使用这套权重的业务理由', [
        '假设下一阶段发货按此区域构成分配',
        '固定公共构成，描述性隔离区域占比差异',
        '对不同目标业务构成做敏感性检查',
    ], index=None, placeholder='请选择权重理由')
    submitted = st.form_submit_button('按声明权重比较', type='primary')

if submitted:
    if reason is None:
        st.session_state.pop('carrier_comparability_evidence', None)
        st.error('需要声明权重理由，候选权重尚未应用。')
    else:
        evidence = compare_carriers(records, {'华东': east_weight, '华南': 1.0 - east_weight})
        evidence['weight_declaration'] = {'reason': reason, 'source': '用户对合成示例的显式业务构成假设',
                                         'is_observed_future_mix': False}
        st.session_state['carrier_comparability_evidence'] = evidence

evidence = st.session_state.get('carrier_comparability_evidence', raw)
if evidence['status'] == 'needs_weights':
    st.info('目前只展示分层观察。标准化结论等待权重声明；系统不会自行猜测目标业务构成。')
elif evidence['status'] == 'blocked':
    st.error(evidence['reason'])
else:
    common_weights = evidence['weights']
    weighted = evidence['weighted_rates']
    st.caption('已应用的声明：' + '；'.join(f'{r} {w:.0%}' for r, w in common_weights.items())
               + '。理由：' + evidence['weight_declaration']['reason'])
    col1, col2, col3 = st.columns(3)
    col1.metric(f'{first} · 公共权重超时率', f"{weighted[first]:.1%}")
    col2.metric(f'{second} · 公共权重超时率', f"{weighted[second]:.1%}")
    col3.metric('总体与标准化顺序反转', '是' if evidence['reversal'] else '否')
    if evidence['reversal']:
        st.success('同一套计数，改变为声明的公共构成后，描述性顺序反转。汇总计算正确，不代表比较结论充分。')
    else:
        st.info('当前公共构成下没有顺序反转；这仍不能证明因果或支持自动更换承运商。')
    st.error('因果建议已阻断：区域标准化不能回答“换成另一承运商会改善多少”。路线、货物、客户和时间等因素仍未控制。')
    st.page_link('pages/3_决策实验室.py', label='继续任务：声明成本和效力，比较有条件的方案', icon='🧪')

with st.expander('公式、权重、检查与边界 · 可复核'):
    st.json({k: evidence[k] for k in ('status', 'code', 'reason', 'weights', 'formula', 'recommendation') if k in evidence})
    for limitation in evidence['limitations']:
        st.write(f'• {limitation}')
    st.caption('这里演示的是可比性检查及计算方法；不是真实承运商评估，也没有数据库执行记录。')
st.download_button('导出比较证据 JSON', json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False),
                   file_name='semantica-comparability-evidence.json', mime='application/json')
