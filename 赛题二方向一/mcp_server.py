"""Typed aggregate tools with explicit clarification and versioned evidence."""
from __future__ import annotations
import json
from datetime import date
import pandas as pd
from mcp.server.mcpserver import MCPServer
from src.alignment import Alignment, ClarifyPoint, TimeRange
from src.contracts import QueryGateway, answer_payload, clarification_payload, json_safe, revisions
from src.db import connect
from src.loop import Clarification, QueryLoop

mcp = MCPServer("语枢 Semantica", version="0.2.0")
_conn = connect()
_loop = QueryLoop(_conn)
_gateway = QueryGateway(_loop)

@mcp.resource("ontology://metrics")
def metrics_catalog() -> str:
    """指标定义与执行同源。"""
    _loop.aligner.maybe_reload()
    return json.dumps(_loop.aligner.metrics, ensure_ascii=False, indent=2)

@mcp.resource("data://cards")
def data_cards() -> str:
    return json.dumps({"data_origin": "synthetic, seed=42",
        "revisions": revisions(_conn, _loop.aligner.ontology_dir),
        "table_rows": {t: _conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                       for t in ("orders", "shipments", "products", "customers", "carriers")},
        "limits": "Aggregate tools only; authentication belongs to the host."}, ensure_ascii=False, indent=2)

@mcp.tool()
def align_terms(question: str) -> dict:
    """只对齐、不执行；检查指标、时间、筛选、歧义和未支持操作。"""
    a = _loop.aligner.align(question)
    return {"metric": a.metric_id, "variant": a.variant_id, "filters": a.filters,
        "time": a.time.label if a.time else None, "clarify": [p.id for p in a.clarify],
        "unsupported": a.unsupported, "ranking": a.ranking, "threshold_hours": a.threshold_hours}

@mcp.tool()
def nl_query(question: str, auto_resolve: bool = False, choices: dict[str, int] | None = None) -> dict:
    """自然语言聚合查询。歧义默认先澄清；choices包含用户明确选择的全部点。
    auto_resolve只用于实验，证据明确标记未经用户确认。
    """
    ans = _loop.ask(question, auto_resolve=auto_resolve)
    if isinstance(ans, Clarification):
        if choices is None:
            return clarification_payload(ans)
        ans = _loop.resolve(ans, choices)
    return answer_payload(ans)

@mcp.tool()
def preview_query(question: str, choices: dict[str, int] | None = None) -> dict:
    """执行前预览语义契约：指标/口径/粒度/时间/版本/来源。只EXPLAIN，不运行结果查询。"""
    return _gateway.preview(question, choices)

@mcp.tool()
def execute_contract(contract: dict) -> dict:
    """执行已确认契约，核对版本与服务端策略，重新编译；不执行传入的SQL。"""
    return _gateway.execute(contract)

@mcp.tool()
def replay_evidence(receipt: dict) -> dict:
    """同一本地数据和语义环境下重放证据，核对完整结果；版本改变会阻断。"""
    return _gateway.replay(receipt)

@mcp.tool()
def run_metric(metric: str, variant: str | None = None,
               start_date: str | None = None, end_date: str | None = None,
               region: str | None = None, carrier: str | None = None) -> dict:
    """类型化指标直查。日期YYYY-MM-DD含始含终；缺失时间或多口径返回澄清。"""
    _loop.aligner.maybe_reload()
    if metric not in _loop.aligner.metrics:
        return {"type": "error", "text": f"未知指标 {metric!r}"}
    mdef = _loop.aligner.metrics[metric]
    a = Alignment(question=f"<metric:{metric}>", metric_id=metric, variant_id=variant)
    if start_date is not None or end_date is not None:
        if not start_date or not end_date:
            return {"type": "error", "text": "必须同时提供开始和结束日期。"}
        try:
            start, end = pd.Timestamp(date.fromisoformat(start_date)), pd.Timestamp(date.fromisoformat(end_date))
            if end < start:
                raise ValueError("结束日期早于开始日期。")
            a.time = TimeRange(start, end + pd.Timedelta(days=1), f"{start_date}–{end_date}")
        except (ValueError, OverflowError) as exc:
            return {"type": "error", "text": f"无效日期：{exc}"}
    else:
        a.clarify.append(ClarifyPoint("time", "请明确时间范围：", _loop.aligner._time_options()))
    if not variant and mdef.get("default_variant") is None:
        a.clarify.append(ClarifyPoint("variant", f"请明确{mdef['zh']}口径：",
            [{"label": v["zh"], "payload": {"metric": metric, "variant": v["id"]}} for v in mdef["variants"]]))
    if region:
        a.filters["region"] = region
    if carrier:
        a.filters["carrier"] = carrier
    ans = _loop.answer(a)
    if isinstance(ans, Clarification):
        return clarification_payload(ans)
    result = answer_payload(ans)
    result.update(metric=metric, variant=variant or mdef.get("default_variant"))
    return result

@mcp.tool()
def diagnose_logistics(start_date: str, end_date: str, region: str | None = None,
                       min_sample: int = 30, coverage: float = 0.5, effectiveness: float = 0.3,
                       cost_per_covered_shipment: float = 5.0, budget: float = 1000.0) -> dict:
    """承运商风险诊断和条件情景模拟。效力/成本来自用户假设，不是因果预测或调度指令。"""
    from src.decision_lab import diagnose_carriers
    return json_safe(diagnose_carriers(_conn, start_date, end_date, region=region,
        min_sample=min_sample, coverage=coverage, effectiveness=effectiveness,
        cost_per_covered_shipment=cost_per_covered_shipment, budget=budget))

@mcp.prompt()
def query_guide() -> str:
    return ("1. preview_query获取契约。clarification时必须向用户确认所有点，禁止代选。\n"
        "2. 用户核对口径、时间和筛选后execute_contract。版本改变后重新预览。\n"
        "3. 回答附上disclosure、trust与evidence；insufficient/error如实报告。\n"
        "4. diagnose_logistics只做给定假设下模拟，不承诺真实改善，不自动下单。\n"
        "5. 哈希只检测本地一致性，当前数据是合成数据，不代表业务实测。")

if __name__ == "__main__":
    mcp.run(transport="stdio")
