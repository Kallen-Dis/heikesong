# -*- coding: utf-8 -*-
"""本体一致性校验器测试：真实本体必须干净，人为注入的缺陷必须被抓到。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.ontology_lint import check_metric_def, format_report, has_errors, lint_ontology


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _save(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _messages(issues, level: str | None = None) -> str:
    return " | ".join(i.message for i in issues if level is None or i.level == level)


class TestShippedOntology:
    def test_has_no_errors(self):
        issues = lint_ontology()
        assert not has_errors(issues), format_report(issues)

    def test_has_no_warnings(self):
        """发布态本体应零警告：警告都要么修掉、要么显式说明理由。"""
        warnings = [i for i in lint_ontology() if i.level == "warning"]
        assert warnings == [], format_report(warnings)

    def test_report_says_clean(self):
        assert "全部检查通过" in format_report([])


class TestStructuralDefects:
    def test_missing_requires_is_an_error(self, ontology_copy):
        path = ontology_copy / "metrics.yaml"
        data = _load(path)
        data["metrics"]["OrderCount"].pop("requires")
        _save(path, data)
        issues = lint_ontology(ontology_copy)
        assert has_errors(issues)
        assert "requires 缺少" in _messages(issues, "error")

    def test_forbidden_expression_is_an_error(self, ontology_copy):
        path = ontology_copy / "metrics.yaml"
        data = _load(path)
        data["metrics"]["OrderCount"]["variants"][0]["expr"] = "COUNT(*); DROP TABLE orders"
        _save(path, data)
        assert "禁止片段" in _messages(lint_ontology(ontology_copy), "error")

    def test_unknown_alias_is_an_error(self, ontology_copy):
        path = ontology_copy / "metrics.yaml"
        data = _load(path)
        data["metrics"]["OrderCount"]["variants"][0]["expr"] = "COUNT(*) FILTER (WHERE x.status IS NULL)"
        _save(path, data)
        assert "未知别名" in _messages(lint_ontology(ontology_copy), "error")

    def test_dangling_default_variant_is_an_error(self, ontology_copy):
        path = ontology_copy / "metrics.yaml"
        data = _load(path)
        data["metrics"]["OrderCount"]["default_variant"] = "ghost"
        _save(path, data)
        assert "不存在于 variants" in _messages(lint_ontology(ontology_copy), "error")

    def test_illegal_base_table_is_an_error(self, ontology_copy):
        path = ontology_copy / "metrics.yaml"
        data = _load(path)
        data["metrics"]["OrderCount"]["table"] = "meta"
        _save(path, data)
        assert "基表" in _messages(lint_ontology(ontology_copy), "error")

    def test_duplicate_variant_keyword_is_an_error(self, ontology_copy):
        path = ontology_copy / "metrics.yaml"
        data = _load(path)
        variants = data["metrics"]["GMV"]["variants"]
        variants[1].setdefault("keywords", []).append(variants[0]["keywords"][0])
        _save(path, data)
        assert "口径关键词" in _messages(lint_ontology(ontology_copy), "error")

    def test_metadata_table_mismatch_is_an_error(self, ontology_copy):
        path = ontology_copy / "metrics.yaml"
        data = _load(path)
        data["metrics"]["OrderCount"]["time_basis"] = "s.ship_time"   # 基表仍是 orders
        _save(path, data)
        assert "不一致" in _messages(lint_ontology(ontology_copy), "error")


class TestReferenceDefects:
    def test_dangling_metric_synonym_target(self, ontology_copy):
        path = ontology_copy / "synonyms.yaml"
        data = _load(path)
        data["terms"][0]["target"]["id"] = "NotExist"
        _save(path, data)
        assert "不存在的指标" in _messages(lint_ontology(ontology_copy), "error")

    def test_dangling_axiom_synonym_target(self, ontology_copy):
        path = ontology_copy / "synonyms.yaml"
        data = _load(path)
        entry = next(e for e in data["terms"] if e["target"]["kind"] == "axiom")
        entry["target"]["id"] = "not_an_axiom"
        _save(path, data)
        assert "不存在的公理" in _messages(lint_ontology(ontology_copy), "error")

    def test_duplicate_alias_across_metrics(self, ontology_copy):
        path = ontology_copy / "metrics.yaml"
        data = _load(path)
        data["metrics"]["GMV"]["synonyms"] = ["订单量"]      # 与 OrderCount 撞名
        _save(path, data)
        assert "同时指向多个指标" in _messages(lint_ontology(ontology_copy), "error")

    def test_learned_id_clash_with_metrics(self, ontology_copy):
        path = ontology_copy / "learned.yaml"
        data = _load(path) if (ontology_copy / "learned.yaml").exists() else {}
        base = _load(ontology_copy / "metrics.yaml")["metrics"]["OrderCount"]
        data.setdefault("metrics", {})["OrderCount"] = base
        _save(path, data)
        assert "指标 ID 与 metrics.yaml 冲突" in _messages(lint_ontology(ontology_copy), "error")

    def test_relation_to_unknown_concept(self, ontology_copy):
        path = ontology_copy / "ontology.yaml"
        data = _load(path)
        data["relations"][0]["to"] = "Invoice"
        _save(path, data)
        assert "不是已定义概念" in _messages(lint_ontology(ontology_copy), "error")

    def test_unsupported_term_not_registered_is_a_warning(self, ontology_copy):
        path = ontology_copy / "ontology.yaml"
        data = _load(path)
        data["not_covered"] = [nc for nc in data["not_covered"] if nc["term"] != "库存"]
        _save(path, data)
        assert "未登记" in _messages(lint_ontology(ontology_copy), "warning")


class TestRationaleRule:
    def test_multi_variant_default_without_rationale_warns(self, ontology_copy):
        path = ontology_copy / "metrics.yaml"
        data = _load(path)
        gmv = data["metrics"]["GMV"]
        gmv["default_variant"] = "gross"
        gmv.pop("default_rationale", None)
        _save(path, data)
        assert "default_rationale" in _messages(lint_ontology(ontology_copy), "warning")

    def test_rationale_silences_the_warning(self, ontology_copy):
        path = ontology_copy / "metrics.yaml"
        data = _load(path)
        gmv = data["metrics"]["GMV"]
        gmv["default_variant"] = "gross"
        gmv["default_rationale"] = "演示：显式声明默认口径的理由"
        _save(path, data)
        issues = lint_ontology(ontology_copy)
        assert not [i for i in issues if "default_rationale" in i.message]


class TestSingleDefCheck:
    def test_check_metric_def_matches_directory_lint(self):
        issues = check_metric_def("Bad", {"zh": "无表", "variants": []}, origin="<t>")
        assert has_errors(issues)
        assert any("基表" in i.message for i in issues)
