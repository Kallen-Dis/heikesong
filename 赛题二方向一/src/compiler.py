# -*- coding: utf-8 -*-
"""语义编译器（步骤④）：把"对齐后的概念查询计划"编译为可执行 SQL。

v0 支持四种编译形态：
    standard  —— 指标 + 筛选 + 时间范围
    ranking   —— "≤最多/最高≥" 排名类（按维度分组取第 1）
    threshold —— "超过 N 小时" 阈值类
    compare   —— 多品牌对比（分组）

对话披露（disclosure）随编译一并产出：口径 / 时间基准 / 筛选条件。
"""
from __future__ import annotations

import re
import math
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from .alignment import Alignment
from .db import render_sql

DIM_EXPR = {"carrier": "k.carrier_name", "region": "c.region", "category": "p.category", "brand": "p.brand"}
DIM_ZH = {"carrier": "承运商", "region": "区域", "category": "品类", "brand": "品牌"}
FILTER_ZH = {"region": "区域", "brand": "品牌", "brands": "品牌", "category": "品类",
             "carrier": "承运商", "channel": "渠道", "customer": "客户", "customer_like": "客户（模糊）"}

# 表达式安全守卫（本体 YAML 是受信任输入，仍做纵深防御）；ontology_lint 复用同一规则
FORBIDDEN_EXPR = re.compile(
    r";|--|/\*|\*/|\b(drop|delete|update|insert|create|attach|detach|copy|pragma|call)\b",
    re.IGNORECASE)


@dataclass
class CompileResult:
    sql: str                                     # 可执行 SQL（筛选值一律用 ? 占位）
    params: list = field(default_factory=list)   # 与占位符一一对应的绑定值
    disclosure: list[str] = field(default_factory=list)
    kind: str = "standard"

    @property
    def sql_display(self) -> str:
        """人类可读 SQL：字面量已转义内联，供 UI 展示 / MCP 返回 / 实验归档。

        安全设计：**执行用 sql + params（参数绑定），展示用 sql_display**，同一编译产物。
        """
        return render_sql(self.sql, self.params)


class Compiler:
    _FORBIDDEN_EXPR = FORBIDDEN_EXPR
    _TABLES = ("orders", "shipments")

    def __init__(self, metrics: dict) -> None:
        self.metrics = metrics

    # ------------------------------------------------------------ 工具

    def _expr(self, metric_id: str, variant_id: str | None) -> tuple[str, dict]:
        """取出口径表达式与口径定义（带一致性/安全校验）。"""
        mdef = self.metrics[metric_id]
        vid = variant_id or mdef.get("default_variant")
        if vid is None:
            raise ValueError(f"指标 {metric_id} 属多口径指标，必须先澄清口径再编译")
        variant = next((v for v in mdef["variants"] if v["id"] == vid), None)
        if variant is None:
            raise ValueError(f"指标 {metric_id} 不存在口径 {vid}")
        expr = variant["expr"]
        if self._FORBIDDEN_EXPR.search(expr):
            raise ValueError(f"指标 {metric_id} 口径 {vid} 的表达式含禁止片段，已拒绝编译")
        if mdef.get("table") not in self._TABLES:
            raise ValueError(f"指标 {metric_id} 的基表 {mdef.get('table')!r} 不在允许列表内")
        return expr, variant

    def _from_clause(self, metric_table: str, filters: dict, ranking_dim: str | None,
                     expr: str = "", time_basis: str = "") -> list[str]:
        """按需装配 JOIN：筛选条件 + 排名维度 + 表达式/时间基准中引用的别名。"""
        blob = f"{expr} {time_basis}"
        parts = ["orders o"]
        if metric_table == "shipments" or re.search(r"\b(?:s|k)\.", blob) \
                or filters.get("carrier") or ranking_dim == "carrier":
            parts.append("JOIN shipments s ON s.order_id = o.order_id")
        if filters.get("region") or filters.get("customer") or filters.get("customer_like") \
                or ranking_dim == "region" or re.search(r"\bc\.", blob):
            parts.append("JOIN customers c ON o.customer_id = c.customer_id")
        if filters.get("brand") or filters.get("brands") or filters.get("category") \
                or ranking_dim in ("brand", "category") or re.search(r"\bp\.", blob):
            parts.append("JOIN products p ON o.product_id = p.product_id")
        if filters.get("carrier") or ranking_dim == "carrier" or re.search(r"\bk\.", blob):
            parts.append("JOIN carriers k ON s.carrier_id = k.carrier_id")
        return parts

    def _where(self, metric_time_basis: str, filters: dict, time,
               skip: frozenset[str] = frozenset()) -> list[tuple[str, list]]:
        """返回 [(谓词, [绑定值])]，谓词里一律用 ? 占位符。"""
        items: list[tuple[str, list]] = [
            (f"{metric_time_basis} >= ?", [time.start]),
            (f"{metric_time_basis} < ?", [time.end_excl]),
        ]
        cols = {"region": "c.region", "brand": "p.brand", "category": "p.category",
                "carrier": "k.carrier_name", "channel": "o.channel",
                "customer": "c.customer_name"}
        for key, col in cols.items():
            if key in skip or not filters.get(key):
                continue
            items.append((f"{col} = ?", [filters[key]]))
        if "customer_like" not in skip and filters.get("customer_like"):
            items.append(("c.customer_name LIKE ?", [f"%{filters['customer_like']}%"]))
        if "brands" not in skip and filters.get("brands"):
            brands = list(filters["brands"])
            items.append((f"p.brand IN ({', '.join('?' for _ in brands)})", brands))
        return items

    @staticmethod
    def _assemble(where_items: list[tuple[str, list]]) -> tuple[str, list]:
        """把谓词列表拼成 WHERE 子句文本 + 有序绑定值。"""
        sql = "\n  AND ".join(clause for clause, _ in where_items)
        params = [v for _, values in where_items for v in values]
        return sql, params

    def _base_disclosure(self, metric_id: str, variant: dict, a: Alignment) -> list[str]:
        mdef = self.metrics[metric_id]
        basis_zh = "下单时间" if mdef["time_basis"].startswith("o.") else "发货时间"
        lines = [f"指标：{mdef['zh']}（口径：{variant['zh']}）",
                 f"时间：{a.time.label}（按{basis_zh}过滤）"]
        for k, v in a.filters.items():
            if k == "brands":   # 多品牌对比由 _compile_compare 单独披露
                continue
            label = FILTER_ZH.get(k, k)
            if k == "customer_like":
                v = f"*{v}*"
            lines.append(f"筛选：{label} = {v}")
        if mdef["table"] == "orders" and (a.filters.get("carrier")
                or (a.ranking or {}).get("dim") == "carrier"):
            lines.append("关联粒度：仅统计已关联运单的订单；每订单至多一运单契约由执行前检查保障")
        return lines

    # ------------------------------------------------------------ 编译入口

    def compile(self, a: Alignment) -> CompileResult:
        """编译入口：按对齐结果选择形态；前置条件不足时抛出可读异常。"""
        if a.time is None:
            raise ValueError("缺少时间范围：编译前必须先确定时间口径")
        if not isinstance(a.time.start, (pd.Timestamp, datetime)) \
                or not isinstance(a.time.end_excl, (pd.Timestamp, datetime)) \
                or pd.isna(a.time.start) or pd.isna(a.time.end_excl) \
                or a.time.end_excl <= a.time.start:
            raise ValueError("时间范围无效：起止时间必须合法，结束时间必须晚于开始时间")
        if a.clarify:
            raise ValueError("存在未完成的澄清，不能编译查询")
        if not isinstance(a.filters, dict):
            raise ValueError("筛选条件必须为字段到值的映射")
        unknown = set(a.filters) - set(FILTER_ZH)
        if unknown:
            raise ValueError(f"不支持的筛选字段：{sorted(unknown)}")
        for key, value in a.filters.items():
            if key == "brands":
                if not isinstance(value, list) or not value \
                        or any(not isinstance(v, str) or not v.strip() for v in value):
                    raise ValueError("brands 筛选必须为非空字符串列表")
            elif not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} 筛选必须为非空字符串")
        if "brand" in a.filters and "brands" in a.filters:
            raise ValueError("brand 与 brands 筛选不能同时出现")
        if a.metric_id is not None and a.metric_id not in self.metrics:
            raise KeyError(f"未知指标 {a.metric_id}")
        if a.ranking is not None:
            if not isinstance(a.ranking, dict) or set(a.ranking) != {"dim", "metric"} or a.ranking.get("dim") not in DIM_EXPR \
                    or a.ranking.get("metric") not in self.metrics:
                raise ValueError("排名维度或指标无效")
            if a.metric_id != a.ranking["metric"]:
                raise ValueError("排名指标与对齐指标不一致")
        if a.threshold_hours is not None:
            if isinstance(a.threshold_hours, bool) or not isinstance(a.threshold_hours, (int, float)) \
                    or not math.isfinite(a.threshold_hours) or a.threshold_hours < 0:
                raise ValueError("时长阈值必须为有限的非负数字")
            if a.ranking:
                raise ValueError("当前引擎不支持时长阈值与排名组合")
            if a.metric_id is not None:
                raise ValueError("当前时长阈值查询只支持已签收运单计数，不能与其他指标组合")
        if a.ranking:
            return self._compile_ranking(a)
        if a.threshold_hours is not None:
            return self._compile_threshold(a)
        if not a.metric_id:
            raise ValueError("未对齐到任何指标，无法编译")
        if len(a.filters.get("brands") or []) >= 2:
            return self._compile_compare(a)
        return self._compile_standard(a)

    # ------------------------------------------------------------ 各形态

    def _compile_standard(self, a: Alignment) -> CompileResult:
        expr, variant = self._expr(a.metric_id, a.variant_id)
        mdef = self.metrics[a.metric_id]
        froms = self._from_clause(mdef["table"], a.filters, None, expr, mdef["time_basis"])
        where_sql, params = self._assemble(
            self._where(mdef["time_basis"], a.filters, a.time))
        sql = (f"SELECT {expr} AS value\nFROM {' '.join(froms)}\n"
               f"WHERE {where_sql}")
        return CompileResult(sql=sql, params=params,
                             disclosure=self._base_disclosure(a.metric_id, variant, a),
                             kind="standard")

    def _compile_ranking(self, a: Alignment) -> CompileResult:
        dim = a.ranking["dim"]
        metric_id = a.ranking["metric"] or "DelayCount"
        expr, variant = self._expr(metric_id, a.variant_id)
        mdef = self.metrics[metric_id]
        froms = self._from_clause(mdef["table"], a.filters, dim, expr, mdef["time_basis"])
        where_sql, params = self._assemble(
            self._where(mdef["time_basis"], a.filters, a.time))
        sql = (f"SELECT {DIM_EXPR[dim]} AS value\nFROM {' '.join(froms)}\n"
               f"WHERE {where_sql}\n"
               f"GROUP BY 1\nORDER BY {expr} DESC NULLS LAST, {DIM_EXPR[dim]} ASC\nLIMIT 1")
        disc = self._base_disclosure(metric_id, variant, a)
        disc.append(f"排名：按指标降序取第 1 名（维度：{DIM_ZH[dim]}）")
        return CompileResult(sql=sql, params=params, disclosure=disc, kind="ranking")

    def _compile_threshold(self, a: Alignment) -> CompileResult:
        """"超过 N 小时"阈值类：同样支持区域/承运商/品牌等筛选（v0 曾遗漏）。"""
        h = a.threshold_hours
        froms = self._from_clause("shipments", a.filters, None, "", "s.ship_time")
        items: list[tuple[str, list]] = [
            ("s.delivery_time IS NOT NULL", []),
            ("epoch(s.delivery_time - s.ship_time) / 3600.0 > ?", [h]),
            *self._where("s.ship_time", a.filters, a.time),
        ]
        where_sql, params = self._assemble(items)
        sql = f"SELECT COUNT(*) AS value\nFROM {' '.join(froms)}\nWHERE {where_sql}"
        disc = [f"口径：发货→签收耗时 > {h} 小时（阈值题）",
                f"时间：{a.time.label}（按发货时间过滤）"]
        for k, v in a.filters.items():
            label = FILTER_ZH.get(k, k)
            if k == "customer_like":
                v = f"*{v}*"
            disc.append(f"筛选：{label} = {v}")
        return CompileResult(sql=sql, params=params, disclosure=disc, kind="threshold")

    def _compile_compare(self, a: Alignment) -> CompileResult:
        expr, variant = self._expr(a.metric_id, a.variant_id)
        mdef = self.metrics[a.metric_id]
        brands = list(a.filters["brands"])
        froms = self._from_clause(mdef["table"], a.filters, "brand", expr, mdef["time_basis"])
        items = [*self._where(mdef["time_basis"], a.filters, a.time, skip=frozenset({"brand", "brands"})),
                 (f"p.brand IN ({', '.join('?' * len(brands))})", brands)]
        where_sql, params = self._assemble(items)
        sql = (f"SELECT p.brand AS value, {expr} AS metric\nFROM {' '.join(froms)}\n"
               f"WHERE {where_sql}\nGROUP BY 1\nORDER BY 1")
        disc = self._base_disclosure(a.metric_id, variant, a)
        disc.append(f"对比：品牌分组（{'、'.join(brands)}）")
        return CompileResult(sql=sql, params=params, disclosure=disc, kind="compare")
