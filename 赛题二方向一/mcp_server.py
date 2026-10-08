# -*- coding: utf-8 -*-
"""语枢 MCP Server —— "第三接口定律"的工程落地。

任何支持 MCP 的 Agent（VS Code Copilot / Claude Desktop 等）均可即插即用：

    Resources : ontology://metrics（指标口径目录） / data://cards（数据卡片）
    Tools     : align_terms（仅对齐不查询）/ nl_query（完整五步闭环）/ run_metric（按指标直查）
    Prompt    : query_guide（给外部 Agent 的行为指引：先对齐、再澄清、后查询）

启动（stdio）：
    python mcp_server.py

Agent 端配置示例（VS Code / Claude Desktop 的 mcpServers 配置）：
    {"mcpServers": {"semantica": {
        "command": "python",
        "args": ["d:/黑客松/semantica/mcp_server.py"]}}}

自测：python scripts/test_mcp_client.py
"""
from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from src.db import ONTOLOGY_DIR, connect
from src.loop import Clarification, QueryLoop

mcp = MCPServer("语枢 Semantica", version="0.1.0")
_conn = connect()
_loop = QueryLoop(_conn)


def _clarification_json(clar: Clarification) -> dict:
    return {
        "type": "clarification",
        "question": clar.question,
        "points": [
            {"id": p.id, "prompt": p.prompt,
             "options": [{"index": i, "label": o["label"]} for i, o in enumerate(p.options)]}
            for p in clar.points
        ],
        "hint": "请让用户选择后，用 choices={'点id': 选项index} 重新调用 nl_query 的 question 追加说明，或直接根据选项重构问题再次查询。",
    }


# ---------------------------------------------------------------- Resources

@mcp.resource("ontology://metrics")
def metrics_catalog() -> str:
    """指标口径目录：每个指标的正式别名、多口径定义与 SQL 语义（JSON）。"""
    return json.dumps(_loop.aligner.metrics, ensure_ascii=False, indent=2)


@mcp.resource("data://cards")
def data_cards() -> str:
    """数据卡片：数据截止日与各表行数（供 Agent 自检数据新鲜度）。"""
    end = _conn.execute("SELECT value FROM meta WHERE key = 'dataset_end'").fetchone()[0]
    tables = ["orders", "shipments", "products", "customers", "carriers"]
    rows = {t: _conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    return json.dumps({"dataset_end": end, "table_rows": rows}, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- Tools

@mcp.tool()
def align_terms(question: str) -> str:
    """把自然语言问题对齐到本体概念/指标（仅对齐，不执行查询）。

    返回：识别出的指标、筛选条件、时间范围、以及需澄清的歧义点。
    Agent 可先用本工具判断问题是否足够明确。
    """
    a = _loop.aligner.align(question)
    return json.dumps({
        "metric": a.metric_id,
        "filters": a.filters,
        "time": a.time.label if a.time else None,
        "clarify": [p.id for p in a.clarify],
        "unsupported": a.unsupported,
        "ranking": a.ranking,
        "threshold_hours": a.threshold_hours,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def nl_query(question: str, auto_resolve: bool = True) -> str:
    """自然语言数据查询（完整五步闭环：对齐→澄清→编译→执行→披露）。

    auto_resolve=True 时对歧义自动取默认口径；False 时返回澄清卡 JSON，
    由调用方选择后再以更明确的问题重新查询（推荐生产用法：不猜测）。
    """
    try:
        ans = _loop.ask(question, auto_resolve=auto_resolve)
    except Exception as e:
        return json.dumps({"type": "error", "error": str(e)}, ensure_ascii=False)
    if isinstance(ans, Clarification):
        return json.dumps(_clarification_json(ans), ensure_ascii=False, indent=2)
    return json.dumps({
        "type": ans.type,
        "text": ans.text,
        "value": ans.value if not hasattr(ans.value, "item") else ans.value.item(),
        "sql": ans.sql,
        "disclosure": ans.disclosure,
        "trust": ans.trust,
    }, ensure_ascii=False, indent=2, default=str)


@mcp.tool()
def run_metric(metric: str, variant: str | None = None,
               start_date: str | None = None, end_date: str | None = None,
               region: str | None = None, carrier: str | None = None) -> str:
    """按指标 ID 直查（跳过自然语言对齐，供确定性流水线使用）。

    metric: 指标 ID（见 metrics_catalog）；variant: 口径 ID；
    start_date/end_date: 时间范围（含始、含终，格式 YYYY-MM-DD）；
    region/carrier: 简单筛选。
    """
    from src.alignment import Alignment, ClarifyPoint, TimeRange
    import pandas as pd

    if metric not in _loop.aligner.metrics:
        return json.dumps({"type": "error", "error": f"未知指标 {metric!r}，可用："
                           f"{sorted(_loop.aligner.metrics)}"}, ensure_ascii=False, indent=2)

    mdef = _loop.aligner.metrics[metric]
    variants = mdef.get("variants") or []
    if not variant and mdef.get("default_variant") is None and len(variants) > 1:
        # 多口径且未指定 → 不猜、返回澄清选项（与自然语言路径同一原则）
        clar = Clarification(f"<metric:{metric}>", [ClarifyPoint(
            "variant", f"「{mdef['zh']}」有多种口径，请选择：",
            [{"label": v["zh"], "payload": {"metric": metric, "variant": v["id"]}}
             for v in variants])], Alignment(question=f"<metric:{metric}>"))
        return json.dumps(_clarification_json(clar), ensure_ascii=False, indent=2)

    a = Alignment(question=f"<metric:{metric}>")
    a.metric_id = metric
    a.variant_id = variant
    if start_date and end_date:
        a.time = TimeRange(pd.Timestamp(start_date), pd.Timestamp(end_date) + pd.Timedelta(days=1),
                           f"{start_date}–{end_date}")
    else:
        a.time = _loop.aligner._last_n_days(30)
    if region:
        a.filters["region"] = region
    if carrier:
        a.filters["carrier"] = carrier

    try:
        _loop.aligner.maybe_reload()
        ans = _loop.answer(a)      # 复用闭环：披露 / 信任标签 / 参数化执行同源
    except Exception as e:  # noqa: BLE001
        return json.dumps({"type": "error", "error": str(e)}, ensure_ascii=False)
    if isinstance(ans, Clarification):
        return json.dumps(_clarification_json(ans), ensure_ascii=False, indent=2)
    return json.dumps({
        "type": ans.type,
        "metric": metric,
        "variant": variant or mdef.get("default_variant"),
        "text": ans.text,
        "value": ans.value if not hasattr(ans.value, "item") else ans.value.item(),
        "sql": ans.sql,
        "disclosure": ans.disclosure,
        "trust": ans.trust,
    }, ensure_ascii=False, indent=2, default=str)


@mcp.prompt()
def query_guide() -> str:
    """给外部 Agent 的查询行为指引（不猜测原则）。"""
    return (
        "你是数据查询助手。使用语枢工具时的原则：\n"
        "1. 先调用 align_terms 检查问题是否明确；\n"
        "2. 出现 clarifications 时（口径/时间/实体歧义），必须先向用户确认，禁止自行假设；\n"
        "3. 确认后用明确措辞调用 nl_query 获得结果；\n"
        "4. 回答用户时，必须附上 disclosure（口径披露）与 trust（信任标签）中的关键信息；\n"
        "5. 若返回 unsupported/insufficient，如实告知数据不足，禁止编造。"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
