# -*- coding: utf-8 -*-
"""活体本体管线 v1：指标的"生长"（现场教学杀招的引擎）。

流程：术语 + 自然语言定义 → LLM 生成指标草稿 → 三关校验（结构 / 安全 / 可执行）
      → 写入 ontology/learned.yaml → 对齐引擎热加载，即刻可查询（无需重启）。

用法见 scripts/teach.py。
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import yaml

from .alignment import Alignment, TimeRange
from .compiler import Compiler
from .db import ONTOLOGY_DIR, dataset_end
from .llm import LLMClient

LEARNED_PATH = ONTOLOGY_DIR / "learned.yaml"

_ALLOWED_ALIASES = {"o", "s", "p", "c", "k"}
_FORBIDDEN = re.compile(r";|--|/\*|\b(select|from|join|drop|delete|update|insert|create)\b", re.IGNORECASE)

DRAFT_SYSTEM = (
    "你是数据平台的语义工程师。根据数据仓库表结构与术语的业务定义，"
    "为该术语生成一个指标口径的 YAML 定义。只输出 YAML 原文，不要解释、不要代码块围栏。"
)

_PROMPT_TEMPLATE = """数据仓库表结构：
{ddl}

现有指标口径库（格式样例，供参考）：
{example}

术语名称：{term}
术语定义（业务含义）：{desc}
附加同义词：{synonyms}

要求：
1. 输出格式（严格照抄结构）：
metrics:
  <英文PascalCase标识>:
    zh: <中文名>
    synonyms: [<别名1>, <别名2>]
    time_basis: <o.order_time 或 s.ship_time，选择语义合理者>
    table: <orders 或 shipments>
    requires: [<表达式/时间基准用到的表>]
    default_variant: std
    default_rationale: <为何该单口径不需要向用户澄清>
    variants:
      - id: std
        zh: <口径的一句话描述>
        expr: "<单个 DuckDB 聚合表达式>"
2. expr 的 SQL 别名仅允许：orders→o，shipments→s，products→p，customers→c，carriers→k；
3. expr 必须是单行表达式（聚合/比率皆可），禁止分号、禁止子查询、禁止注释；
4. 时间差建议用 date_diff('hour', 较早时间, 较晚时间)；比率用 * 1.0 / 保证浮点；
5. 若定义涉及"占比/率"，分母用 COUNT(*) 或相应的 FILTER 条件；
6. requires 必须完整列出 expr 与 time_basis 引用到的表（缺失会被本体校验器判为错误）；
7. default_rationale 用一句中文说明"为什么这个口径无需澄清即可直接使用"。
"""


def draft_metric(llm: LLMClient, term: str, desc: str, synonyms: list[str] | None,
                 ddl: str, example_metrics: dict) -> tuple[str, dict]:
    """调用 LLM 生成指标草稿；返回 (metric_id, 定义 dict)。"""
    example = yaml.safe_dump(
        {"metrics": dict(list(example_metrics.items())[:2])}, allow_unicode=True, sort_keys=False)
    user = _PROMPT_TEMPLATE.format(ddl=ddl, example=example, term=term, desc=desc,
                                   synonyms=", ".join(synonyms or []) or "无")
    text = llm.chat(DRAFT_SYSTEM, user)
    text = re.sub(r"```(?:yaml)?", "", text, flags=re.IGNORECASE).strip("` \n\t")
    data = yaml.safe_load(text)
    metrics = (data or {}).get("metrics") or {}
    if not metrics:
        raise ValueError(f"LLM 未返回有效的 metrics 结构，原始回复：\n{text[:500]}")
    mid = list(metrics)[0]
    defn = metrics[mid]

    # 规整：单变体时自动补默认口径；以用户术语作为规范名（LLM 原命名降级为同义词）
    if not defn.get("default_variant") and defn.get("variants"):
        defn["default_variant"] = defn["variants"][0]["id"]
    if defn.get("default_variant") and not defn.get("default_rationale"):
        defn["default_rationale"] = "单口径指标：语义无歧义，可直接使用（口径随答案披露）"
    if not defn.get("requires"):
        # LLM 偶尔漏填 → 依据 expr/time_basis 的别名推断，保证本体一致
        from .ontology_lint import ALIAS_TO_TABLE
        blob = " ".join([str((v or {}).get("expr", "")) for v in defn.get("variants") or []]
                        + [str(defn.get("time_basis") or "")])
        tables = [ALIAS_TO_TABLE[a] for a in re.findall(r"\b([a-z])\.\w+", blob)
                  if a in ALIAS_TO_TABLE]
        if defn.get("table"):
            tables.append(defn["table"])
        defn["requires"] = list(dict.fromkeys(tables))
    llm_zh = str(defn.get("zh") or "").strip()
    aliases = list(defn.get("synonyms") or [])
    if llm_zh and llm_zh != term:
        aliases.append(llm_zh)
    defn["zh"] = term
    if synonyms:
        aliases.extend(synonyms)
    defn["synonyms"] = list(dict.fromkeys(aliases))
    return mid, defn


def validate_metric(mid: str, defn: dict, conn, base_metrics: dict) -> tuple[bool, str]:
    """三关校验：结构关 / 安全关 / 可执行关。返回 (通过与否, 试跑 SQL 或错误说明)。"""
    errors: list[str] = []
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", mid):
        errors.append(f"指标 ID 非法：{mid}")
    for field in ("zh", "time_basis", "table", "variants"):
        if not defn.get(field):
            errors.append(f"缺少字段：{field}")
    if defn.get("time_basis") not in ("o.order_time", "s.ship_time"):
        errors.append(f"time_basis 非法：{defn.get('time_basis')}")
    if defn.get("table") not in ("orders", "shipments"):
        errors.append(f"table 非法：{defn.get('table')}")
    variants = defn.get("variants") or []
    if variants:
        vid = defn.get("default_variant")
        if vid and all(v.get("id") != vid for v in variants):
            errors.append(f"default_variant「{vid}」不在 variants 中")
        for v in variants:
            expr = str(v.get("expr", ""))
            if not expr:
                errors.append("存在空 expr")
                continue
            if _FORBIDDEN.search(expr):
                errors.append(f"expr 含禁止内容：{expr[:60]}")
            used = set(re.findall(r"\b([a-z])\.\w+", expr))
            bad = used - _ALLOWED_ALIASES
            if bad:
                errors.append(f"expr 使用未知别名：{sorted(bad)}")

    # 与本体校验器共用同一套规则：避免"教学管线"与"手工本体"两套标准漂移
    from .ontology_lint import check_metric_def
    for issue in check_metric_def(mid, defn, origin="<teach>"):
        if issue.level == "error" and issue.message not in errors:
            errors.append(issue.message)

    if errors:
        return False, "；".join(errors)

    # 可执行关：在真库上试跑（近 30 天）
    test_metrics = dict(base_metrics)
    test_metrics[mid] = defn
    compiler = Compiler(test_metrics)
    end = dataset_end(conn)
    variants = defn.get("variants") or []
    a = Alignment(question="<teach-test>", metric_id=mid,
                  variant_id=(variants[0]["id"] if variants else None),
                  time=TimeRange(end.normalize() - pd.Timedelta(days=29),
                                 end.normalize() + pd.Timedelta(days=1), "试跑：近30天"))
    try:
        res = compiler.compile(a)
        conn.execute(res.sql, list(res.params)).fetchall()
        return True, res.sql_display
    except Exception as e:  # noqa: BLE001
        return False, f"试跑失败：{e}"


def apply_metric(mid: str, defn: dict) -> Path:
    """写入 learned.yaml（与既有内容合并）；对齐引擎将热加载生效。"""
    data: dict = {"metrics": {}}
    if LEARNED_PATH.exists():
        data = yaml.safe_load(LEARNED_PATH.read_text(encoding="utf-8")) or {"metrics": {}}
    data.setdefault("metrics", {})[mid] = defn
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    LEARNED_PATH.write_text(
        "# 活体本体 · 现场教学产物（由 scripts/teach.py 生成；可手工编辑，热加载无需重启）\n" + body,
        encoding="utf-8")
    return LEARNED_PATH
