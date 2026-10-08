# -*- coding: utf-8 -*-
"""本体一致性校验器（ontology lint）。

本体是语枢的"语法"，语法错了整个编译器就会静默出错。本模块把本体质量从
"靠人眼审 YAML" 提升为**可自动执行的检查**，覆盖四类文件：

    ontology.yaml  —— 概念 / 属性 / 关系 / 公理 / 刻意不覆盖清单
    metrics.yaml   —— 指标口径库（单一事实来源）
    synonyms.yaml  —— 跨切面口语映射
    learned.yaml   —— 活体本体（现场教学产物）

检查项（error = 必须修；warning = 建议修）：

    结构   zh/expr/variants 缺失、variant id 重复、枚举属性缺 values
    一致性 default_variant 悬空、多口径却带默认（会绕过澄清）、requires 缺表
    安全   expr 含禁止片段（; -- /* 等）、引用未声明的表别名
    引用   relations 指向未定义概念、同义词 target 指向不存在的指标/公理、
           陷阱术语未登记在 not_covered、learned 与 metrics 指标 ID 冲突

用法：
    from src.ontology_lint import lint_ontology, lint_executable, has_errors
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .compiler import FORBIDDEN_EXPR
from .db import ONTOLOGY_DIR

# 表别名约定（与本体注释、编译器、data/generate_data.py 对齐）
ALIAS_TO_TABLE = {"o": "orders", "s": "shipments", "p": "products",
                  "c": "customers", "k": "carriers"}
TABLE_TO_ALIAS = {v: k for k, v in ALIAS_TO_TABLE.items()}
TABLES = set(ALIAS_TO_TABLE.values())
BASE_TABLES = {"orders", "shipments"}          # 指标基表只能是事实表
ALIAS_RE = re.compile(r"\b([a-z])\.\w+")
VALID_TARGET_KINDS = {"metric", "axiom", "status", "unsupported"}


@dataclass(frozen=True)
class Issue:
    level: str      # error | warning
    where: str      # 定位（文件::对象）
    message: str

    def __str__(self) -> str:  # pragma: no cover - 展示用
        icon = "❌" if self.level == "error" else "⚠️"
        return f"{icon} [{self.where}] {self.message}"


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _aliases_used(expr: str) -> set[str]:
    return set(ALIAS_RE.findall(expr or ""))


def _check_metric(mid: str, mdef: dict, origin: str, issues: list[Issue],
                  axiom_ids: set[str] | None = None) -> None:
    where = f"{origin}::{mid}"
    if not isinstance(mdef, dict):
        issues.append(Issue("error", where, "指标定义必须是映射"))
        return
    if not mdef.get("zh"):
        issues.append(Issue("error", where, "缺少中文名 zh"))
    table = mdef.get("table")
    if table not in BASE_TABLES:
        issues.append(Issue("error", where, f"基表 {table!r} 非法（应为 {sorted(BASE_TABLES)}）"))

    basis = mdef.get("time_basis") or ""
    if "." not in basis:
        issues.append(Issue("error", where, f"time_basis 需带表别名，当前 {basis!r}"))
    else:
        alias = basis.split(".")[0]
        if ALIAS_TO_TABLE.get(alias) != table:
            issues.append(Issue("error", where,
                                f"time_basis 别名 {alias!r} 与基表 {table!r} 不一致"))

    variants = mdef.get("variants") or []
    if not variants:
        issues.append(Issue("error", where, "variants 为空"))
    vids = [v.get("id") for v in variants]
    if len(set(vids)) != len(vids):
        issues.append(Issue("error", where, "variant id 重复"))
    if any(not vid for vid in vids):
        issues.append(Issue("error", where, "存在未命名（id 为空）的口径"))

    default = mdef.get("default_variant", "__missing__")
    if default == "__missing__":
        issues.append(Issue("error", where, "缺少 default_variant 键（多口径请显式写 null）"))
    elif default is not None and default not in vids:
        issues.append(Issue("error", where, f"default_variant {default!r} 不存在于 variants"))
    elif default is not None and len(variants) > 1:
        if not mdef.get("default_rationale"):
            issues.append(Issue("warning", where,
                                f"多口径指标却设了默认口径 {default!r}，会绕过澄清；"
                                "如属有意为之，请补 default_rationale 说明理由"))
    elif default is None and len(variants) <= 1:
        issues.append(Issue("warning", where, "单口径指标却把 default_variant 设为 null，会产生无意义澄清"))

    used_tables: set[str] = {table} if table in TABLES else set()
    kw_owner: dict[str, str] = {}
    metric_names = {mdef.get("zh"), *(mdef.get("synonyms") or [])}
    for v in variants:
        for kw in v.get("keywords") or []:
            owner = kw_owner.get(kw)
            if owner and owner != v.get("id"):
                issues.append(Issue("error", where,
                                    f"口径关键词 {kw!r} 同时属于 {owner!r} 与 {v.get('id')!r}（歧义无法判定）"))
            kw_owner[kw] = v.get("id")
            if kw in metric_names:
                issues.append(Issue("warning", where,
                                    f"口径关键词 {kw!r} 与指标名/别名重复，指标匹配会优先命中"))
    for v in variants:
        expr = v.get("expr") or ""
        if not expr:
            issues.append(Issue("error", where, f"口径 {v.get('id')!r} 缺少 expr"))
            continue
        if FORBIDDEN_EXPR.search(expr):
            issues.append(Issue("error", where, f"口径 {v.get('id')!r} 的 expr 含禁止片段：{expr[:50]}"))
        for alias in _aliases_used(expr):
            if alias not in ALIAS_TO_TABLE:
                issues.append(Issue("error", where, f"expr 引用未知别名 {alias!r}"))
            else:
                used_tables.add(ALIAS_TO_TABLE[alias])
    if basis and "." in basis:
        used_tables.add(ALIAS_TO_TABLE.get(basis.split(".")[0], "?"))

    requires = set(mdef.get("requires") or [])
    unknown = requires - TABLES
    if unknown:
        issues.append(Issue("error", where, f"requires 含未知表：{sorted(unknown)}"))
    missing = used_tables - requires
    if missing:
        issues.append(Issue("error", where,
                            f"requires 缺少表达式/时间基准用到的表：{sorted(missing)}"))

    syns = mdef.get("synonyms") or []
    if len(set(syns)) != len(syns):
        issues.append(Issue("warning", where, "synonyms 有重复词条"))


def check_metric_def(mid: str, defn: dict, origin: str = "<draft>") -> list[Issue]:
    """对单个指标定义做与全量校验一致的检查（供活体本体管线等复用，避免两套规则漂移）。"""
    issues: list[Issue] = []
    _check_metric(mid, defn, origin, issues)
    return issues


def lint_ontology(ontology_dir: Path | str = ONTOLOGY_DIR) -> list[Issue]:
    """对本体目录做静态一致性检查（纯文件，不连数据库）。"""
    d = Path(ontology_dir)
    issues: list[Issue] = []
    ontology = _read_yaml(d / "ontology.yaml")
    metrics_raw = _read_yaml(d / "metrics.yaml")
    synonyms_raw = _read_yaml(d / "synonyms.yaml")
    learned_raw = _read_yaml(d / "learned.yaml")

    # ---------------- ontology.yaml ----------------
    concepts = ontology.get("concepts") or {}
    if not concepts:
        issues.append(Issue("error", "ontology.yaml", "concepts 为空"))
    for cid, cdef in concepts.items():
        where = f"ontology.yaml::{cid}"
        if not isinstance(cdef, dict):
            issues.append(Issue("error", where, "概念定义必须是映射"))
            continue
        if not cdef.get("zh"):
            issues.append(Issue("error", where, "缺少 zh"))
        if cdef.get("table") not in TABLES:
            issues.append(Issue("error", where, f"table {cdef.get('table')!r} 不在允许列表内"))
        if not cdef.get("key"):
            issues.append(Issue("error", where, "缺少主键 key"))
        for pname, pdef in (cdef.get("properties") or {}).items():
            pw = f"{where}.{pname}"
            if not isinstance(pdef, dict) or not pdef.get("type"):
                issues.append(Issue("error", pw, "属性需声明 type"))
            elif pdef.get("type") == "enum" and not pdef.get("values"):
                issues.append(Issue("warning", pw, "枚举属性未登记 values"))

    axiom_ids: set[str] = set()
    for ax in ontology.get("axioms") or []:
        aid = ax.get("id") if isinstance(ax, dict) else None
        where = f"ontology.yaml::axiom {aid}"
        if not aid:
            issues.append(Issue("error", "ontology.yaml", "公理缺少 id"))
            continue
        if aid in axiom_ids:
            issues.append(Issue("error", where, "公理 id 重复"))
        axiom_ids.add(aid)
        if not ax.get("expr"):
            issues.append(Issue("error", where, "公理缺少 expr"))
        if not ax.get("zh"):
            issues.append(Issue("warning", where, "公理缺少中文名 zh"))
        for alias in _aliases_used(ax.get("expr") or ""):
            if alias not in ALIAS_TO_TABLE:
                issues.append(Issue("error", where, f"expr 引用未知别名 {alias!r}"))

    for rel in ontology.get("relations") or []:
        where = f"ontology.yaml::relation {rel.get('from')}->{rel.get('to')}"
        for side in ("from", "to"):
            if rel.get(side) not in concepts:
                issues.append(Issue("error", where, f"{side}={rel.get(side)!r} 不是已定义概念"))
        if not rel.get("join"):
            issues.append(Issue("warning", where, "关系缺少 join 表达式"))
        if not rel.get("zh"):
            issues.append(Issue("warning", where, "关系缺少中文名 zh"))

    not_covered = {nc.get("term") for nc in (ontology.get("not_covered") or []) if isinstance(nc, dict)}
    for nc in ontology.get("not_covered") or []:
        if not isinstance(nc, dict) or not nc.get("term") or not nc.get("reason"):
            issues.append(Issue("error", "ontology.yaml::not_covered", "每项需含 term 与 reason"))

    # ---------------- metrics.yaml / learned.yaml ----------------
    metrics = dict(metrics_raw.get("metrics") or {})
    learned = dict(learned_raw.get("metrics") or {})
    for mid, mdef in metrics.items():
        _check_metric(mid, mdef, "metrics.yaml", issues)
    clash = set(metrics) & set(learned)
    if clash:
        issues.append(Issue("error", "learned.yaml",
                            f"指标 ID 与 metrics.yaml 冲突：{sorted(clash)}（教学会覆盖正式指标）"))
    for mid, mdef in learned.items():
        _check_metric(mid, mdef, "learned.yaml", issues, axiom_ids)

    all_metrics = {**metrics, **learned}
    alias_index: dict[str, list[str]] = {}
    for mid, mdef in all_metrics.items():
        for term in [mdef.get("zh"), *(mdef.get("synonyms") or [])]:
            if term:
                alias_index.setdefault(term, []).append(mid)
    for term, owners in alias_index.items():
        if len(set(owners)) > 1:
            issues.append(Issue("error", "metrics.yaml",
                                f"别名/名称 {term!r} 同时指向多个指标：{sorted(set(owners))}"))

    # ---------------- synonyms.yaml / learned 术语 ----------------
    seen_terms: dict[str, int] = {}
    entries = [*(synonyms_raw.get("terms") or []), *(learned_raw.get("terms") or [])]
    for e in entries:
        term = (e or {}).get("term")
        where = f"synonyms.yaml::{term}"
        if not term:
            issues.append(Issue("error", "synonyms.yaml", "词条缺少 term"))
            continue
        seen_terms[term] = seen_terms.get(term, 0) + 1
        target = e.get("target") or {}
        kind = target.get("kind")
        if kind not in VALID_TARGET_KINDS:
            issues.append(Issue("error", where, f"target.kind {kind!r} 非法（可用 {sorted(VALID_TARGET_KINDS)}）"))
        elif kind == "metric" and target.get("id") not in all_metrics:
            issues.append(Issue("error", where, f"target 指向不存在的指标 {target.get('id')!r}"))
        elif kind == "axiom" and target.get("id") not in axiom_ids:
            issues.append(Issue("error", where, f"target 指向不存在的公理 {target.get('id')!r}"))
        elif kind == "status":
            if target.get("concept") not in concepts:
                issues.append(Issue("error", where, f"target.concept {target.get('concept')!r} 不是已定义概念"))
            if not target.get("value"):
                issues.append(Issue("error", where, "status 型 target 需给出 value"))
        elif kind == "unsupported" and term not in not_covered:
            issues.append(Issue("warning", where, "陷阱术语未登记在 ontology.yaml 的 not_covered 清单"))
        if term in alias_index:
            issues.append(Issue("warning", where, "该词条与指标正式别名重复（metrics.yaml 优先）"))

    for term, n in seen_terms.items():
        if n > 1:
            issues.append(Issue("error", "synonyms.yaml", f"词条 {term!r} 重复出现 {n} 次"))

    return issues


def lint_executable(ontology_dir: Path | str = ONTOLOGY_DIR) -> list[Issue]:
    """可执行性检查：每个口径表达式在真库上做 EXPLAIN（不执行、不扫数据）。"""
    from .db import connect

    d = Path(ontology_dir)
    metrics = dict(_read_yaml(d / "metrics.yaml").get("metrics") or {})
    metrics.update(_read_yaml(d / "learned.yaml").get("metrics") or {})
    conn = connect()
    issues: list[Issue] = []
    for mid, mdef in metrics.items():
        for v in mdef.get("variants") or []:
            expr = v.get("expr")
            if not expr:
                continue
            try:
                conn.execute(f"EXPLAIN SELECT {expr} FROM orders o "
                             "JOIN shipments s ON s.order_id = o.order_id "
                             "JOIN products p ON o.product_id = p.product_id "
                             "JOIN customers c ON o.customer_id = c.customer_id "
                             "JOIN carriers k ON s.carrier_id = k.carrier_id")
            except Exception as e:  # noqa: BLE001
                issues.append(Issue("error", f"{mid}::{v.get('id')}",
                                    f"表达式无法通过 SQL 解析：{str(e)[:120]}"))
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == "error" for i in issues)


def format_report(issues: list[Issue]) -> str:
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    lines = [f"本体校验：{len(errors)} 个错误，{len(warnings)} 个警告", ""]
    if errors:
        lines += ["## 错误", *[f"- {i}" for i in errors], ""]
    if warnings:
        lines += ["## 警告", *[f"- {i}" for i in warnings], ""]
    if not issues:
        lines.append("✅ 全部检查通过：本体结构、引用、安全与一致性均无问题。")
    return "\n".join(lines)
