# -*- coding: utf-8 -*-
"""任务恢复工作台：场景数据来源与条件驱动的重算。"""
from __future__ import annotations

import duckdb
import pytest

from src import scenario_fixture
from src.task_runtime import TaskRuntime

REPAIR = {"carrier": "B", "source": "primary", "variant": "delivered_only",
          "regions": ["华东", "华南"]}


def _repair_and_compare(rt: TaskRuntime) -> dict:
    rt.action("request_evidence", REPAIR)
    rt.action("derive_comparison", {})
    return rt.snapshot()["comparison"]


class TestScenarioSource:
    def test_builtin_fallback_when_warehouse_missing(self, tmp_path):
        """没生成数据集也要能直接跑工作台。"""
        rt = TaskRuntime(db_path=tmp_path / "missing.duckdb")
        assert rt.scenario_source == "builtin"
        assert rt.snapshot()["state"] == "needs_repair"

    def test_materializes_from_shared_warehouse(self, tmp_path):
        """主仓库存在 demo schema 时，场景表从那里取材——一个库、一条链路。"""
        db = tmp_path / "warehouse.duckdb"
        conn = duckdb.connect(str(db))
        scenario_fixture.install(conn)
        conn.close()

        rt = TaskRuntime(db_path=db)
        assert rt.scenario_source == "warehouse"
        assert rt.snapshot()["scenario_source"] == "warehouse"

    def test_scenario_schema_stays_out_of_main_listing(self, tmp_path):
        """场景表放在独立 schema，裸 DDL 提示词不应看到它们。"""
        db = tmp_path / "warehouse.duckdb"
        conn = duckdb.connect(str(db))
        conn.execute("CREATE TABLE orders(order_id INTEGER)")
        scenario_fixture.install(conn)
        assert [r[0] for r in conn.execute("SHOW TABLES").fetchall()] == ["orders"]
        conn.close()


class TestWeightDrivenRecompute:
    def test_weight_change_flips_ranking_and_reuses_counts(self, tmp_path):
        rt = TaskRuntime(db_path=tmp_path / "missing.duckdb")
        first = _repair_and_compare(rt)
        assert first["better_carrier"] == "B"
        assert first["rates"]["A"] == pytest.approx(0.10)
        assert first["rates"]["B"] == pytest.approx(0.072)

        evidence_before = len(rt.snapshot()["evidence"])
        rt.set_weights(0.8)
        rt.action("derive_comparison", {})

        second = rt.snapshot()["comparison"]
        assert second["better_carrier"] == "A"
        assert second["rates"]["A"] == pytest.approx(0.04)
        assert second["rates"]["B"] == pytest.approx(0.048)
        assert len(rt.snapshot()["evidence"]) == evidence_before, "改权重不应重新取证"
