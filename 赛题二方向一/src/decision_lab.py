"""Read-only carrier diagnosis and explicit-assumption intervention arithmetic.

No model API, mutation, causal inference or dispatch is performed here.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_FLOOR

from src.semantic_guard import validate_relationships


LIMITATIONS = [
    "演示数据为合成物流数据，不代表真实承运商表现。",
    "历史关联不能证明承运商导致超时；总体差异未控制路线、货物和客户构成。",
    "只以已妥投运单作分母；未完成运单可能产生选择偏差，不可将运输中当作准时。",
    "Wilson 95% 区间假设独立伯努利样本；订单聚集和非随机合成过程会影响解释。",
    "情景是假设未来存在相同规模和历史超时率的可比队列，不是预测或实际收益。",
    "覆盖在每组内随机发生；有效率为用户假设的相对风险降低，不是估计出的因果效应。",
    "预算只含用户输入的单位干预成本，没有固定成本、实施损耗或其他费用。",
    "系统只分析和模拟，不更新数据库、不下单、不执行调度。",
]


def wilson_interval(delayed: int, delivered: int) -> list[float] | None:
    """Two-sided Wilson score interval using z=1.959963984540054."""
    if delivered < 0 or delayed < 0 or delayed > delivered:
        raise ValueError("计数必须满足 0 <= delayed <= delivered")
    if delivered == 0:
        return None
    z = 1.959963984540054
    p = delayed / delivered
    denominator = 1 + z * z / delivered
    center = (p + z * z / (2 * delivered)) / denominator
    radius = z * math.sqrt(p * (1 - p) / delivered + z * z / (4 * delivered**2)) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _day(value: object) -> date:
    if isinstance(value, datetime):
        raise ValueError("日期仅支持 YYYY-MM-DD，不支持带时间的值")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("日期仅支持 YYYY-MM-DD")
    parsed = date.fromisoformat(value)
    if value != parsed.isoformat():
        raise ValueError("日期仅支持 YYYY-MM-DD")
    return parsed


def _number(value: object, name: str, upper: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为有限非负数")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (upper is not None and number > upper):
        raise ValueError(f"{name} 必须为有限数且在 0..{upper if upper is not None else '无穷'} 范围内")
    return number


def _totals(groups: list[dict]) -> dict:
    total = {key: sum(g[key] for g in groups) for key in
             ("shipment_count", "delivered_count", "delayed_count", "in_transit_count")}
    n = total["delivered_count"]
    total["delay_rate"] = total["delayed_count"] / n if n else None
    total["wilson95"] = wilson_interval(total["delayed_count"], n)
    total["in_transit_share"] = total["in_transit_count"] / total["shipment_count"] if total["shipment_count"] else None
    return total


def simulate_intervention(groups: list[dict], *, coverage: float, effectiveness: float,
                          cost_per_covered_shipment: float, budget: float) -> dict:
    """Allocate a shared budget by expected avoided delays per covered shipment.

    Only sample-qualified groups are eligible. Counts covered are whole shipments;
    avoided delays remain fractional expectations. A zero unit cost is allowed.
    """
    coverage = _number(coverage, "coverage", 1)
    effectiveness = _number(effectiveness, "effectiveness", 1)
    cost = _number(cost_per_covered_shipment, "cost_per_covered_shipment")
    budget = _number(budget, "budget")
    eligible = [g for g in groups if g["eligible_for_intervention"]]
    # Common unit cost/effect across groups: per-yuan benefit ordering equals rate
    # ordering. Total delayed volume remains a separate diagnostic priority.
    eligible.sort(key=lambda g: (-g["delay_rate"] * effectiveness,
                                 -g["delayed_count"], str(g["carrier_id"]), str(g.get("region"))))
    remaining = Decimal(str(budget))
    decimal_cost = Decimal(str(cost))
    allocations = []
    for group in eligible:
        desired = math.floor(group["delivered_count"] * coverage)
        affordable = desired if cost == 0 else int((remaining / decimal_cost).to_integral_value(rounding=ROUND_FLOOR))
        # Zero budget means no funded intervention, including the zero-cost edge.
        covered = min(desired, affordable) if budget > 0 else 0
        exact_spent = covered * decimal_cost
        spent = float(exact_spent)
        remaining = max(Decimal(0), remaining - exact_spent)
        allocations.append({"carrier_id": group["carrier_id"], "carrier_name": group["carrier_name"],
                            "region": group.get("region"), "covered_shipments": covered,
                            "estimated_cost": spent, "historical_delay_rate": group["delay_rate"]})
    covered = sum(a["covered_shipments"] for a in allocations)
    spent = sum(a["estimated_cost"] for a in allocations)
    baseline = sum(g["delayed_count"] for g in groups)
    scenarios = {}
    for label, effect in (("worst", effectiveness * 0.8), ("base", effectiveness),
                          ("best", min(1.0, effectiveness * 1.2))):
        avoided = sum(a["covered_shipments"] * a["historical_delay_rate"] * effect for a in allocations)
        scenarios[label] = {"effectiveness": effect, "covered_shipments": covered,
                            "expected_avoided_delays": avoided, "estimated_cost": spent,
                            "expected_remaining_delays": max(0.0, baseline - avoided),
                            "breakeven_value_per_avoided_delay": spent / avoided if avoided > 0 else None}
    return {"budget": budget, "unspent_budget": float(remaining),
            "allocation_strategy": "合格组按单票预期避免超时收益降序分配统一预算；当前同单位成本和同有效率，等价于超时率降序。诊断规模排序另按超时量。",
            "eligible_delivered_count": sum(g["delivered_count"] for g in eligible),
            "excluded_small_sample_delivered_count": sum(g["delivered_count"] for g in groups if not g["eligible_for_intervention"]),
            "baseline_delayed_count": baseline, "allocations": allocations, "scenarios": scenarios}


def diagnose_carriers(conn, start_date, end_date, region=None, group_by_region=False,
                      min_sample=30, coverage=0.5, effectiveness=0.3,
                      cost_per_covered_shipment=5.0, budget=1000.0) -> dict:
    """Return JSON-native evidence, diagnosis and conditional scenarios; fail closed."""
    result = {"status": "blocked", "reason": None, "asof": None, "groups": [],
              "executed_queries": [], "limitations": list(LIMITATIONS)}
    try:
        start, end = _day(start_date), _day(end_date)
        if start > end:
            raise ValueError("开始日期不能晚于结束日期")
        if not isinstance(group_by_region, bool):
            raise ValueError("group_by_region 必须为布尔值")
        if isinstance(min_sample, bool) or not isinstance(min_sample, int) or min_sample < 1:
            raise ValueError("min_sample 必须为正整数")
        if region is not None and (not isinstance(region, str) or not region.strip()):
            raise ValueError("区域必须为非空字符串或 None（全部区域）")
        coverage = _number(coverage, "coverage", 1)
        effectiveness = _number(effectiveness, "effectiveness", 1)
        cost = _number(cost_per_covered_shipment, "cost_per_covered_shipment")
        budget = _number(budget, "budget")
        violations = validate_relationships(conn)
        if violations:
            result["relationship_violations"] = violations
            result["reason"] = "关联完整性校验未通过，停止诊断，避免重复计数或漏行"
            return result

        def query(sql, params):
            rows = conn.execute(sql, params).fetchall()
            result["executed_queries"].append({"sql": sql, "parameters": list(params)})
            return rows

        meta = query("SELECT value FROM meta WHERE key = ?", ["dataset_end"])
        if len(meta) != 1:
            raise ValueError("缺少唯一数据截止日")
        asof = _day(str(meta[0][0]))
        result["asof"] = asof.isoformat()
        if end > asof:
            raise ValueError("结束日期超出数据截止日，不能视为完整观察")
        stop = (end + timedelta(days=1)).isoformat()
        snapshot_stop = (asof + timedelta(days=1)).isoformat()
        if region is not None and not query("SELECT 1 FROM customers WHERE region = ? LIMIT 1", [region]):
            raise ValueError("区域不存在")
        region_expr = "c.region" if group_by_region else "CAST(NULL AS VARCHAR)"
        sql = f"""SELECT k.carrier_id, k.carrier_name, {region_expr} AS customer_region,
COUNT(*) AS shipment_count,
COUNT(*) FILTER (WHERE s.delivery_time IS NOT NULL AND s.delivery_time < CAST(? AS TIMESTAMP)) AS delivered_count,
COUNT(*) FILTER (WHERE s.delivery_time IS NOT NULL AND s.delivery_time < CAST(? AS TIMESTAMP) AND s.delivery_time > s.promised_time) AS delayed_count,
COUNT(*) FILTER (WHERE s.delivery_time IS NULL OR s.delivery_time >= CAST(? AS TIMESTAMP)) AS in_transit_count
FROM shipments s
JOIN carriers k ON s.carrier_id = k.carrier_id
JOIN orders o ON s.order_id = o.order_id
JOIN customers c ON o.customer_id = c.customer_id
WHERE s.ship_time >= CAST(? AS TIMESTAMP) AND s.ship_time < CAST(? AS TIMESTAMP)
AND (? IS NULL OR c.region = ?)
GROUP BY k.carrier_id, k.carrier_name, {region_expr}
ORDER BY delayed_count DESC, k.carrier_id, customer_region"""
        params = [snapshot_stop, snapshot_stop, snapshot_stop, start.isoformat(), stop, region, region]
        rows = query(sql, params)
        for carrier_id, name, customer_region, total, delivered, delayed, transit in rows:
            group = {"carrier_id": str(carrier_id), "carrier_name": str(name), "region": customer_region,
                     "shipment_count": int(total), "delivered_count": int(delivered),
                     "delayed_count": int(delayed), "in_transit_count": int(transit),
                     "delay_rate": delayed / delivered if delivered else None,
                     "wilson95": wilson_interval(delayed, delivered),
                     "in_transit_share": transit / total if total else None,
                     "eligible_for_intervention": delivered >= min_sample,
                     "expected_reducible_delayed_count": delayed * coverage * effectiveness,
                     "caution": "小样本：仅观察，不自动纳入干预" if delivered < min_sample else None}
            result["groups"].append(group)
        overall = _totals(result["groups"])
        result["overall"] = overall
        if overall["delivered_count"] == 0:
            result["reason"] = "选择范围内没有已妥投运单，超时率分母为零，停止情景计算"
            return result
        for group in result["groups"]:
            group["rate_gap_vs_overall"] = group["delay_rate"] - overall["delay_rate"] if group["delay_rate"] is not None else None
        ranked = sorted((g for g in result["groups"] if g["eligible_for_intervention"]),
                        key=lambda g: (-g["expected_reducible_delayed_count"], -g["delayed_count"], g["carrier_id"], str(g["region"])))
        result["priority"] = [{"carrier_id": g["carrier_id"], "carrier_name": g["carrier_name"],
                               "region": g["region"], "expected_reducible_delayed_count": g["expected_reducible_delayed_count"]}
                              for g in ranked]
        result["assumptions"] = {"coverage": coverage, "effectiveness": effectiveness,
                                 "cost_per_covered_shipment_yuan": cost, "budget_yuan": budget,
                                 "min_sample": min_sample, "sensitivity": "effectiveness × 0.8 / 1.0 / 1.2，最大为 1",
                                 "allocation": "合格组按单票期望避免超时收益降序，共享预算顺序覆盖；同单位成本和有效率时等价于超时率降序。仅固定成本/固定效力线性模型，不声称真实最优调度。"}
        result["scope"] = {"start_date": start.isoformat(), "end_date": end.isoformat(), "region": region,
                           "group_by_region": group_by_region, "time_basis": "shipments.ship_time",
                           "denominator": "delivery_time 非空且截至 asof 已妥投（含有签收时间的异常状态）",
                           "overall_comparator": "同日期、同区域筛选内总体；按已妥投数量加权，不是组率的平均"}
        result["formula"] = {"delay_rate": "已妥投且 delivery_time > promised_time 数量 / 已妥投数量",
                             "covered_shipments": "min(floor(delivered_count × coverage), floor(remaining_budget / unit_cost))；预算0则覆盖0；单位成本0且预算>0则覆盖目标量",
                             "expected_avoided_delays": "Σ covered_shipments × historical_delay_rate × assumed_effectiveness",
                             "estimated_cost": "Σ covered_shipments × assumed_unit_cost",
                             "breakeven_value_per_avoided_delay": "estimated_cost / expected_avoided_delays；零效果时为空（无法确定盈亏平衡）"}
        result["simulation"] = simulate_intervention(result["groups"], coverage=coverage, effectiveness=effectiveness,
                                                    cost_per_covered_shipment=cost, budget=budget)
        result["warnings"] = ["超时量表示问题规模，超时率表示已妥投中的比例，两者不能互相替代。"]
        if overall["in_transit_count"]:
            result["warnings"].append(f"未完成占比 {overall['in_transit_share']:.1%}，最终超时率可能变化。")
        if not ranked:
            result["warnings"].append("没有达到小样本阈值的组，情景覆盖量为 0。")
        result["status"] = "ok"
    except Exception as exc:
        result["reason"] = f"数据或输入校验未通过：{type(exc).__name__}: {exc}"
    return result
