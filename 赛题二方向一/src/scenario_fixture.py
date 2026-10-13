# -*- coding: utf-8 -*-
"""任务恢复工作台的物流场景数据（唯一来源）。

场景表住在主仓库 `data/warehouse.duckdb` 的 `demo` schema 里，由
`data/generate_data.py` 一并写入。工作台只读 ATTACH 该文件，把场景表复制进
内存工作副本再执行：结论失效与"数据变化"演示需要写库，而主仓库要留给语义层与题库。

于是整个作品只有**一个 DuckDB 文件、一条连接、一个 Compiler**；内存副本只是可写工作区。
场景表放在独立 schema，因此不出现在 `SHOW TABLES` 里，裸 DDL 基线提示词与题库不受污染。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import duckdb

SCHEMA = "demo"

COLUMNS: dict[str, tuple[str, ...]] = {
    "customers": ("customer_id INTEGER", "customer_name VARCHAR", "region VARCHAR"),
    "carriers": ("carrier_id INTEGER", "carrier_name VARCHAR"),
    "orders": ("order_id INTEGER", "customer_id INTEGER", "order_time TIMESTAMP"),
    "shipments": ("shipment_id INTEGER", "order_id INTEGER", "carrier_id INTEGER",
                  "ship_time TIMESTAMP", "delivery_time TIMESTAMP", "promised_time TIMESTAMP"),
}

# (承运商, 客户, 已妥投, 其中超时, 在途)——华东/华南两格各自构成反转
CELLS = ((1, 1, 900, 18, 25), (1, 2, 100, 12, 25), (2, 1, 100, 4, 25), (2, 2, 900, 72, 25))
START = datetime(2026, 9, 1, 8)
PROMISE_HOURS = 24
LATE_HOURS = 36
ON_TIME_HOURS = 12


def rows() -> dict[str, list[tuple]]:
    """场景表的全部行：2 个客户、2 家承运商，每格另有 25 条在途运单。"""
    orders: list[tuple] = []
    shipments: list[tuple] = []
    idx = 0
    for carrier, customer, completed, late, in_transit in CELLS:
        for n in range(completed + in_transit):
            idx += 1
            orders.append((idx, customer, START))
            delivery = None if n >= completed else \
                START + timedelta(hours=LATE_HOURS if n < late else ON_TIME_HOURS)
            shipments.append((idx, idx, carrier, START, delivery,
                              START + timedelta(hours=PROMISE_HOURS)))
    return {
        "customers": [(1, "合成客户东", "华东"), (2, "合成客户南", "华南")],
        "carriers": [(1, "A"), (2, "B")],
        "orders": orders,
        "shipments": shipments,
    }


def install(conn: duckdb.DuckDBPyConnection, schema: str | None = SCHEMA) -> None:
    """把场景表写进 conn（schema=None 表示写入当前 schema）。"""
    if schema:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    data = rows()
    # 逐行 INSERT 在自动提交下每行一次提交，文件库上要十几秒；包成一个事务即可。
    conn.execute("BEGIN TRANSACTION")
    try:
        for name, columns in COLUMNS.items():
            target = f"{schema}.{name}" if schema else name
            conn.execute(f"CREATE OR REPLACE TABLE {target} ({', '.join(columns)})")
            placeholders = ", ".join("?" * len(columns))
            conn.executemany(f"INSERT INTO {target} VALUES ({placeholders})", data[name])
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def materialize(conn: duckdb.DuckDBPyConnection, db_path: Path | str) -> str:
    """把主仓库里的场景表复制成 conn 内可写的工作副本。

    返回数据来源：``warehouse``（来自 warehouse.duckdb 的 demo schema）或
    ``builtin``（仓库或场景表缺失时按内置定义生成，这样没生成数据集也能直接跑工作台）。
    """
    path = Path(db_path)
    if path.exists():
        quoted = "'" + str(path).replace("'", "''") + "'"
        try:
            conn.execute(f"ATTACH {quoted} AS scenario_src (READ_ONLY)")
            try:
                for name in COLUMNS:
                    conn.execute(f"CREATE OR REPLACE TABLE {name} AS "
                                 f"SELECT * FROM scenario_src.{SCHEMA}.{name}")
                return "warehouse"
            finally:
                conn.execute("DETACH scenario_src")
        except duckdb.Error:
            pass
    install(conn, schema=None)
    return "builtin"
