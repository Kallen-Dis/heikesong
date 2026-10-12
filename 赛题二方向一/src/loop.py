# -*- coding: utf-8 -*-
"""五步闭环编排器：解析 → 对齐 → 澄清 → 编译 → 披露。

用法：
    loop = QueryLoop(conn)
    ans = loop.ask("上个月的履约超时率是多少？")
    if isinstance(ans, Clarification):
        ans = loop.resolve(ans, {"variant": 0})   # 每个澄清点选择选项下标
    print(ans.text, ans.sql, ans.disclosure)
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from .alignment import Aligner, Alignment, ClarifyPoint
from .cache import SemanticCache
from .compiler import Compiler
from .db import run_sql
from .feedback import log_resolution
from .verifier import build_trust
from .contracts import make_contract, build_receipt, revisions
from .semantic_guard import validate_relationships


@dataclass
class Answer:
    type: str                       # answer | insufficient | error
    text: str
    value: object | None = None
    sql: str | None = None
    disclosure: list[str] = field(default_factory=list)
    df: pd.DataFrame | None = None
    trust: dict = field(default_factory=dict)
    rows: list[dict] = field(default_factory=list)   # 多行结果（排名/对比）结构化输出
    evidence: dict = field(default_factory=dict)


@dataclass
class Clarification:
    question: str
    points: list[ClarifyPoint]
    alignment: Alignment


def select_alignment(clar: Clarification, choices: dict[str, int]) -> Alignment:
    """Apply all explicit choices to an independent plan. Missing choices never default."""
    expected = {p.id for p in clar.points}
    if set(choices) != expected:
        raise ValueError(f"请明确选择全部澄清点：{sorted(expected)}；不能省略或添加选择。")
    a = copy.deepcopy(clar.alignment)
    for p in clar.points:
        idx = choices[p.id]
        if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < len(p.options):
            raise ValueError(f"澄清点 {p.id} 的选项无效，请选择 0..{len(p.options)-1}。")
        a.apply(copy.deepcopy(p.options[idx]["payload"]))
    a.clarify = []
    return a


def _fmt(v: object) -> str:
    if v is None:
        return "无结果"
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float):
        if math.isnan(v):
            return "无结果（空集）"
        if v.is_integer():
            return f"{int(v):,}"
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _fmt_rows(df: pd.DataFrame, max_rows: int = 6) -> str:
    """多行结果 → 紧凑可读文本：单列直接列值，多列输出 列名=值，超出部分标注总数。"""
    if df.empty:
        return "无结果"
    names = [str(c) for c in df.columns]
    lines: list[str] = []
    for row in df.head(max_rows).itertuples(index=False):
        vals = [_fmt(v) for v in row]
        if len(vals) == 1:
            lines.append(vals[0])
        else:
            lines.append("，".join(f"{n}={v}" for n, v in zip(names, vals)))
    if len(df) > max_rows:
        lines.append(f"…（共 {len(df)} 行）")
    return "\n".join(lines)


class QueryLoop:
    def __init__(self, conn: duckdb.DuckDBPyConnection, profile: str = "full",
                 ontology_dir: Path | str | None = None,
                 cache: SemanticCache | None = None,
                 feedback_path: Path | str | None = None) -> None:
        self.conn = conn
        self.profile = profile  # full | no_synonyms | no_axioms | no_clarify（消融档位）
        self.clarify_enabled = profile != "no_clarify"
        self.aligner = Aligner(conn, profile="full" if profile == "no_clarify" else profile,
                               ontology_dir=ontology_dir)
        self.compiler = Compiler(self.aligner.metrics)
        self.cache = cache
        self.feedback_path = feedback_path

    # ------------------------------------------------------------ 版本与缓存

    def version(self) -> str:
        """当前语义版本（本体 mtime + 数据仓库指纹）——缓存/审计的失效依据。"""
        self.aligner.maybe_reload()
        from .contracts import digest
        return digest(revisions(self.conn, self.aligner.ontology_dir))

    def ask(self, question: str, auto_resolve: bool = False) -> Answer | Clarification:
        self.aligner.maybe_reload()      # 先看本体是否变过，保证版本号最新
        key = None
        if self.cache is not None:
            key = self.cache.make_key(question, self.profile, self.version(), auto_resolve)
            hit = self.cache.get(key)
            if isinstance(hit, Answer):
                return copy.deepcopy(hit)
        out = self._proceed(self.aligner.align(question), auto_resolve)
        # 只缓存确定答案：澄清/数据不足不入缓存，避免把一次性选择固化成默认行为
        if self.cache is not None and key is not None \
                and isinstance(out, Answer) and out.type == "answer":
            self.cache.put(key, copy.deepcopy(out))
        return out

    def answer(self, a: Alignment) -> Answer | Clarification:
        """对**已完成对齐**的查询计划直接编译执行（跳过自然语言解析）。

        供确定性流水线（MCP run_metric、参数化调用方）复用同一条闭环：口径披露、
        信任标签、参数化执行与自然语言路径完全同源，避免调用方自己拼 SQL。
        若仍有待澄清点（如多口径指标未指定口径），原样返回 Clarification 由调用方处理。
        """
        return self._proceed(a, auto_resolve=False)

    def resolve(self, clar: Clarification, choices: dict[str, int]) -> Answer:
        try:
            a = select_alignment(clar, choices)
        except ValueError as exc:
            return Answer(type="error", text=str(exc), trust={"状态": "invalid_choices"})
        for p in clar.points:
            chosen = p.options[choices[p.id]]
            # 澄清回流：每一次用户选择都是一条人类标注（口径/实体/时间偏好）
            log_resolution(question=clar.question, point_id=p.id, prompt=p.prompt,
                           chosen_label=chosen.get("label", ""), payload=chosen["payload"],
                           metric_id=a.metric_id, source="loop", path=self.feedback_path)
        return self._proceed(a, auto_resolve=False)

    def _proceed(self, a: Alignment, auto_resolve: bool) -> Answer | Clarification:
        a = copy.deepcopy(a)
        assumed = False
        if a.unsupported:
            return Answer(type="insufficient", text=a.unsupported)
        if a.clarify:
            if auto_resolve or not self.clarify_enabled:
                assumed = True
                for p in a.clarify:
                    chosen = p.options[0]
                    a.apply(chosen["payload"])
                    log_resolution(question=a.question, point_id=p.id, prompt=p.prompt,
                                   chosen_label=chosen.get("label", ""), payload=chosen["payload"],
                                   metric_id=a.metric_id, source="auto", path=self.feedback_path)
                a.clarify = []
            else:
                return Clarification(a.question, list(a.clarify), a)
        if not (a.metric_id or a.ranking or a.threshold_hours is not None):
            return Answer(type="insufficient", text="无法映射到本体（v0 覆盖范围见 README）。")
        if a.time is None:  # 完全没提时间：不猜、不默认全量
            return Answer(type="insufficient",
                          text="缺少时间范围：请补充时间（如「8月」「上个月」「近7天」）。")
        try:
            issues = validate_relationships(self.conn)
            if issues:
                return Answer(type="insufficient", text="数据关系违反当前契约，执行已阻断。",
                              trust={"状态": "blocked_by_quality", "质量问题": issues})
            self.compiler.metrics = self.aligner.metrics  # 活体本体热更新同步
            res = self.compiler.compile(a)
            df = run_sql(self.conn, res.sql, res.params)   # 参数绑定执行（无字面量拼接）
            trust = build_trust(self.conn, self.aligner.metrics, a, df)
            trust["口径决策"] = "自动选首项（仅实验用；未经用户确认）" if assumed else "明确选择或本体声明默认值"
            if assumed:
                trust["置信度"] = "需人工确认（自动选首项）"
            contract = make_contract(self, a, res)
            receipt = build_receipt(contract, df, trust,
                                    resolution="assumed_first_option" if assumed else "explicit_or_declared_default")
            value = df.iloc[0, 0] if len(df) and len(df.columns) else None
            multi = len(df) > 1 or len(df.columns) > 1
            text = _fmt_rows(df) if multi else _fmt(value)
            if trust.get("空结果") and "无结果" not in text:
                text += "（空结果）"
            return Answer(type="answer", text=text, value=value, sql=res.sql_display,
                          disclosure=res.disclosure, df=df, trust=trust,
                          rows=df.head(20).to_dict("records") if multi else [], evidence=receipt)
        except Exception as e:  # 编译/执行失败：返回可诊断信息
            return Answer(type="error", text=f"执行失败：{e}")
