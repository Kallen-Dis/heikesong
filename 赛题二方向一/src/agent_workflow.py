"""An optional LLM planner. Model proposals always go through visible human review.

The planner never receives raw customer rows and cannot execute arbitrary SQL.
The offline UI continues to work without an API key; it is not represented as an LLM.
"""
from __future__ import annotations
import json
import re


def propose_query(client, goal: str, metrics: dict) -> dict:
    if not client.available:
        return {"type": "unavailable", "text": "未配置大模型；可直接使用下方确定性查询入口。"}
    catalogue = {mid: {"name": m["zh"], "variants": [{"id": v["id"], "definition": v["zh"]}
                 for v in m["variants"]]} for mid, m in metrics.items()}
    system = (
        "你是数据Agent的规划器。只能提出一个聚合查询草案，不执行，不生成SQL，不选择用户未明确的口径。"
        "保留原始目标的时间和筛选；无法表达的比较、因果、成本或库存请求必须指出限制，不能偷换问题。"
        "只返回JSON对象：{query:拟查询的一句话,rationale:理由,limitations:字符串列表}。"
        "query如无法忠实表达应为null。需要用户核对你做的翻译。")
    try:
        raw = client.chat(system, json.dumps({"goal": goal, "catalogue": catalogue}, ensure_ascii=False))
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
        proposal = json.loads(raw)
        if not isinstance(proposal, dict) or set(proposal) != {"query", "rationale", "limitations"}:
            raise ValueError("规划器输出结构无效")
        if proposal["query"] is not None and (not isinstance(proposal["query"], str)
                                              or not 0 < len(proposal["query"]) <= 1000):
            raise ValueError("查询草案必须为短字符串或null")
        if not isinstance(proposal["rationale"], str) or not isinstance(proposal["limitations"], list) \
                or any(not isinstance(s, str) for s in proposal["limitations"]):
            raise ValueError("理由和限制格式无效")
        return {"type": "proposal", "original_goal": goal, "model": client.model, **proposal,
                "review_required": True, "execution": "not_executed"}
    except Exception as exc:
        return {"type": "error", "text": f"规划草案失败：{type(exc).__name__}；请直接输入业务查询。"}


def evidence_facts(receipt: dict) -> dict:
    """Facts for a consuming agent, without asking a language model to recalculate."""
    result = receipt["result"]
    return {"receipt_id": receipt["receipt_id"], "facts": result["rows"],
            "meaning": receipt["contract"]["meaning"], "conditions": receipt["contract"]["disclosure"],
            "allowed_use": "描述指定口径下的历史聚合；因果判断或业务行动需要额外验证。",
            "limits": receipt["contract"]["limitations"]}
