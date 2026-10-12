"""Descriptive carrier comparisons under explicit common regional weights.

Correct aggregation is insufficient for choosing a carrier. This module demonstrates
composition reversal without estimating causal effects or recommending procurement.
"""
from __future__ import annotations

import math


SYNTHETIC_EXAMPLE = [
    {"carrier": "A", "region": "华东", "delivered": 900, "delayed": 18},
    {"carrier": "A", "region": "华南", "delivered": 100, "delayed": 10},
    {"carrier": "B", "region": "华东", "delivered": 100, "delayed": 1},
    {"carrier": "B", "region": "华南", "delivered": 900, "delayed": 81},
]

LIMITATIONS = [
    "内置示例完全合成，A/B 不对应真实承运商。",
    "总体率按各承运商实际区域占比加权；业务构成不同，不能直接比较能力。",
    "公共权重必须明确声明目标业务构成和理由；标准化结果依赖这项选择。",
    "共同区域支持和正分母只是可计算条件，不保证随机样本、代表性或充分混杂控制。",
    "区域标准化只调整已观察区域的构成，未控制路线、货物、客户、时间等差异。",
    "描述性差异和顺序反转都不是因果效应，不支持自动更换承运商或下单。",
]


def _direction(difference: float) -> int:
    if abs(difference) <= 1e-12:
        return 0
    return 1 if difference > 0 else -1


def compare_carriers(records, weights=None) -> dict:
    """Validate joint support, then describe pooled and explicitly standardized rates.

    Counts must be JSON integers, excluding booleans. Every carrier-region pair
    must occur once, both carriers must cover the same >=2 regions with positive
    delivered counts, and explicit weights must sum to 1 within absolute 1e-9.
    Near-one weights are used as declared, never silently replaced by equal weights.
    """
    result = {
        "status": "blocked", "code": None, "reason": None,
        "raw_pooled_rates": {}, "by_region": [], "weights": None,
        "reversal": False, "reversal_evaluated": False,
        "recommendation": {
            "action": "blocked_causal_recommendation",
            "reason": "这些是观察计数；即使区域标准化可计算，也不足以推断干预效果或决定更换承运商。",
        },
        "limitations": list(LIMITATIONS),
    }

    def block(code, reason):
        result.update(status="blocked", code=code, reason=reason)
        return result

    if not isinstance(records, list) or not records:
        return block("invalid_records", "records 必须为非空记录列表")
    normalized = []
    seen = set()
    for record in records:
        if not isinstance(record, dict) or not {"carrier", "region", "delivered", "delayed"}.issubset(record):
            return block("invalid_record", "每条记录必须包含 carrier、region、delivered、delayed")
        carrier, region = record["carrier"], record["region"]
        if not isinstance(carrier, str) or not carrier.strip() or not isinstance(region, str) or not region.strip():
            return block("invalid_identifier", "carrier 和 region 必须是非空字符串")
        delivered, delayed = record["delivered"], record["delayed"]
        if type(delivered) is not int or type(delayed) is not int or not 0 <= delayed <= delivered:
            return block("invalid_counts", "计数必须是整数且满足 0 <= delayed <= delivered；布尔值不是计数")
        if (carrier, region) in seen:
            return block("duplicate_pair", "同一 carrier-region 组合必须唯一，禁止隐式重复汇总")
        seen.add((carrier, region))
        normalized.append({"carrier": carrier, "region": region, "delivered": delivered, "delayed": delayed})

    carriers = sorted({r["carrier"] for r in normalized})
    regions = sorted({r["region"] for r in normalized})
    if len(carriers) != 2:
        return block("carrier_count", "仅支持恰好两个承运商的可比性检查")
    if len(regions) < 2:
        return block("region_count", "至少需要两个区域，才能检查业务构成差异")
    if any((carrier, region) not in seen for carrier in carriers for region in regions):
        return block("missing_joint_support", "两个承运商必须在全部公共区域都有观测，不填补缺失区域")
    if any(r["delivered"] == 0 for r in normalized):
        return block("zero_denominator", "至少一个承运商-区域的已妥投分母为零，标准化比较被阻断")

    lookup = {(r["carrier"], r["region"]): r for r in normalized}
    rates = {}
    totals = {}
    try:
        for carrier in carriers:
            delivered = sum(r["delivered"] for r in normalized if r["carrier"] == carrier)
            delayed = sum(r["delayed"] for r in normalized if r["carrier"] == carrier)
            totals[carrier] = {"delivered": delivered, "delayed": delayed}
            rates[carrier] = delayed / delivered
        for region in regions:
            region_rates = {c: lookup[c, region]["delayed"] / lookup[c, region]["delivered"] for c in carriers}
            result["by_region"].append({
                "region": region, "rates": region_rates,
                "counts": {c: {"delivered": lookup[c, region]["delivered"], "delayed": lookup[c, region]["delayed"]} for c in carriers},
                "observed_mix": {c: lookup[c, region]["delivered"] / totals[c]["delivered"] for c in carriers},
            })
    except (OverflowError, ValueError, ZeroDivisionError) as exc:
        return block("arithmetic_error", f"计数无法安全计算：{type(exc).__name__}")
    result.update(carriers=carriers, regions=regions, records=normalized,
                  raw_pooled_rates=rates, pooled_counts=totals)
    result["formula"] = {
        "pooled_rate": "Σ 各区域 delayed / Σ 各区域 delivered（使用各承运商实际业务占比）",
        "standardized_rate": "Σ 公共区域权重 × 该承运商在该区域的 delayed / delivered",
        "reversal": "标准化 A-B 差值与总体 A-B 差值异号（比较容差 1e-12）；相等不记为反转",
    }
    if weights is None:
        result.update(status="needs_weights", code="explicit_weights_required",
                      reason="分层描述可查看；比较前必须声明公共区域权重及业务理由，不默认等权。")
        return result
    if not isinstance(weights, dict) or set(weights) != set(regions):
        return block("invalid_weight_regions", "权重必须恰好覆盖相同公共区域集合，不接受缺项或额外区域")
    validated_weights = {}
    try:
        for region in regions:
            value = weights[region]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return block("invalid_weight", "权重必须为非负有限数，不接受布尔值或字符串")
            value = float(value)
            if not math.isfinite(value) or value < 0:
                return block("invalid_weight", "权重必须为非负有限数")
            validated_weights[region] = value
        weight_sum = math.fsum(validated_weights.values())
    except (OverflowError, ValueError):
        return block("invalid_weight", "权重无法安全求和")
    if not math.isfinite(weight_sum) or not math.isclose(weight_sum, 1.0, rel_tol=0, abs_tol=1e-9):
        return block("invalid_weight_sum", "权重总和必须为 1（绝对浮点容差 1e-9）")
    weighted = {c: math.fsum(validated_weights[r] * (lookup[c, r]["delayed"] / lookup[c, r]["delivered"]) for r in regions)
                for c in carriers}
    raw_direction = _direction(rates[carriers[0]] - rates[carriers[1]])
    weighted_direction = _direction(weighted[carriers[0]] - weighted[carriers[1]])
    result.update(status="ok", code="descriptive_comparison_only", reason="已按显式公共权重计算描述性比较；因果建议仍被阻断。",
                  weights=validated_weights, weight_sum=weight_sum, weighted_rates=weighted,
                  reversal=raw_direction * weighted_direction < 0, reversal_evaluated=True)
    return result
