# -*- coding: utf-8 -*-
"""验证当前数仓的关联契约；异常数据必须阻断查询，不能静默放大聚合。

当前版本声明：orders 每订单一行，shipments 每订单至多一行，三个维表键唯一。
若业务需要拆单/多运单，应升级粒度契约与编译策略，而不是删除这个检查。
本模块不缓存；调用方可以在明确且可信的数据快照内复用一次检查结果。
"""
from __future__ import annotations

import duckdb


PRIMARY_KEYS = {
    "orders": "order_id", "shipments": "shipment_id", "products": "product_id",
    "customers": "customer_id", "carriers": "carrier_id",
}
FOREIGN_KEYS = (
    ("orders", "customer_id", "customers", "customer_id"),
    ("orders", "product_id", "products", "product_id"),
    ("shipments", "order_id", "orders", "order_id"),
    ("shipments", "carrier_id", "carriers", "carrier_id"),
)


def validate_relationships(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """返回 code/message/count 结构；空列表表示固定 schema 的关联契约通过。

    所有表名/列名来自静态允许列表；不会执行外部 SQL 或访问外部数据。
    检查缺失列/表等 schema 错误也作为质量阻断返回。
    """
    issues: list[dict] = []
    try:
        for table, key in PRIMARY_KEYS.items():
            total, present, distinct = conn.execute(
                f"SELECT COUNT(*), COUNT({key}), COUNT(DISTINCT {key}) FROM {table}"
            ).fetchone()
            if total != present:
                issues.append({"code": "null_primary_key", "table": table,
                               "count": total - present,
                               "message": f"{table}.{key} 存在空主键，无法保证行身份。"})
            if present != distinct:
                issues.append({"code": "duplicate_primary_key", "table": table,
                               "count": present - distinct,
                               "message": f"{table}.{key} 存在重复主键，JOIN 可能放大结果。"})

        extra = conn.execute("""SELECT COALESCE(SUM(n - 1), 0) FROM (
            SELECT COUNT(*) AS n FROM shipments WHERE order_id IS NOT NULL
            GROUP BY order_id HAVING COUNT(*) > 1)""").fetchone()[0]
        if extra:
            issues.append({"code": "shipment_fanout", "table": "shipments", "count": extra,
                           "message": "一订单对应多个运单，违反当前单运单粒度契约；请升级关联契约后查询。"})

        for child, key, parent, parent_key in FOREIGN_KEYS:
            bad = conn.execute(f"""SELECT COUNT(*) FROM {child} child
                LEFT JOIN {parent} parent ON child.{key} = parent.{parent_key}
                WHERE child.{key} IS NULL OR parent.{parent_key} IS NULL""").fetchone()[0]
            if bad:
                issues.append({"code": "orphan_foreign_key", "table": child, "count": bad,
                               "message": f"{child}.{key} 有 {bad} 行未关联到 {parent}.{parent_key}；内连接会静默丢失这些行。"})
    except duckdb.Error as exc:
        issues.append({"code": "relationship_schema_error",
                       "message": f"无法验证关联契约：{exc}"})
    return issues
