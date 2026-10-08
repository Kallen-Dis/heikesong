# -*- coding: utf-8 -*-
"""pytest 公共夹具。

约定：
    conn          —— 只读 DuckDB 连接（缺数据仓库时自动跳过依赖它的测试）
    loop          —— 语枢五步闭环（full 档位）
    ontology_copy —— 本体目录的临时副本（用于隔离测试活体本体/校验器）
"""
from __future__ import annotations

import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.db import DB_PATH, ONTOLOGY_DIR, connect  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_feedback_env(monkeypatch):
    """测试不得写入仓库本体目录：默认关闭澄清回流（需显式传 path）。"""
    monkeypatch.delenv("SEMANTICA_FEEDBACK_LOG", raising=False)
    yield


@pytest.fixture(scope="session")
def conn():
    if not DB_PATH.exists():
        pytest.skip("缺少 data/warehouse.duckdb（先运行 python data/generate_data.py）")
    connection = connect()
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def loop(conn):
    from src.loop import QueryLoop

    return QueryLoop(conn)


@pytest.fixture()
def ontology_copy(tmp_path: Path) -> Iterator[Path]:
    dst = tmp_path / "ontology"
    shutil.copytree(ONTOLOGY_DIR, dst)
    yield dst
