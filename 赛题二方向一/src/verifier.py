# -*- coding: utf-8 -*-
"""验证器（信任四件套 v1）：口径校验 / 权限裁剪 / 成本估算 / 空结果自检。

v0（已完成）：
    - 空结果自检：查询正常执行但 0 行 → 明确标注，不伪装成答案；
    - 数据新鲜度：披露数据截止日；
    - 信任标签组装：指标 / 时间范围 / 行数 / 置信度 → 供 UI 与 MCP 消费者展示。
规划中：
    - 权限裁剪：行级/列级（P2 融合阶段，接统一权限中心）；
    - 成本估算：EXPLAIN 预检扫描量（P2）。
"""
from __future__ import annotations

import duckdb
import pandas as pd

from .alignment import Alignment
from .db import dataset_end


def build_trust(conn: duckdb.DuckDBPyConnection, metrics: dict, a: Alignment,
                df: pd.DataFrame) -> dict:
    """组装信任标签（解释性元数据，随每个答案一起披露）。"""
    empty = len(df) == 0
    if not empty and len(df.columns):
        try:
            empty = bool(pd.isna(df.iloc[0, 0]))
        except (TypeError, ValueError):
            empty = False

    trust: dict = {
        "数据截止": str(dataset_end(conn).date()),
        "结果行数": int(len(df)),
        "空结果": empty,
    }
    if a.metric_id and a.metric_id in metrics:
        trust["指标"] = metrics[a.metric_id]["zh"]
    if a.ranking:
        trust["排名"] = f"按{a.ranking['metric'] or 'DelayCount'}取第 1"
    if a.threshold_hours is not None:
        trust["阈值"] = f"> {a.threshold_hours} 小时"
    if a.time:
        trust["时间范围"] = a.time.label
    trust["置信度"] = "待核对（空结果）" if empty else "规则校验通过；非统计置信度"
    return trust
