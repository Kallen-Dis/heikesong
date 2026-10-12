"""Evidence scope comes before impressive percentages."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st
from ui_helpers import inject_theme

ROOT = Path(__file__).resolve().parents[1]
st.set_page_config(page_title="验证范围 · 语枢", page_icon="📊", layout="wide")
inject_theme()
st.title("数字有范围，结论有边界")
st.caption("开发期回归与反例只证明这里列出的能力，不等于国际榜单、真实业务收益或企业规模性能。")
report_path = ROOT / "eval" / "adversarial_v2.json"
if report_path.exists():
    report = json.loads(report_path.read_text(encoding="utf-8"))
    latest = report['latest_run']
    st.subheader("独立作者编写的 24 条业务反例")
    st.caption("先记录首次暴露的问题，再保留修复后结果。这套题参与了开发反馈，不能称为严格盲测。")
    st.json(latest['metrics'], expanded=False)
    with st.expander("首次发现与后续修订记录"):
        st.json(report, expanded=False)
else:
    st.info("尚未生成独立业务反例报告。")
st.subheader("已有回归证据")
st.markdown("AmbiQuery-120 为自建合成数据回归集，当前比较全部行、列和单元格。歧义题的实验选择不能视作用户确认。真实耗时口径已从整点边界计数修订为实际秒数。")
with st.expander("查看当前 120 题报告"):
    source = ROOT / "eval" / "iso_selfcheck.md"
    if source.exists():
        st.markdown(source.read_text(encoding="utf-8"))
st.subheader("历史 LLM 小样本实验")
st.caption("2026-10-08 的 A/B/C 组使用种子集，其中 23 题自动判定；D 组的 120 题回归来自另一规模。不能把它们当作同规模比较，也不能推出本体提示普遍无效。以下仅保留历史档案。")
with st.expander("历史图表 · 不作为泛化或获奖承诺"):
    for filename in ("fig1_headline.png", "fig3_ablation.png", "fig2_category.png", "fig4_ablation_cat.png"):
        path = ROOT / "eval" / "charts" / filename
        if path.exists():
            st.image(str(path), width="stretch")
st.info("当前核心价值：明确语义 → 约束执行 → 附带证据 → 检查比较条件。演示重点在完整推理链。")
