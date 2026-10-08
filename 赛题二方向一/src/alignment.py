# -*- coding: utf-8 -*-
"""对齐引擎（步骤②）+ 澄清触发（步骤③）。

v0：词典精确匹配（本体同义词 + 业务口语表 + 数据值词表），离线可用、结果确定。
v1 计划：+ embedding 语义检索 + LLM 仲裁（三通道混合，接口已预留）。

对齐产出：
    - metric_id / variant_id（指标与口径）
    - filters（区域 / 品牌 / 品类 / 承运商 / 客户 / 渠道）
    - time（时间范围；缺失或模糊时生成澄清点）
    - clarify（澄清点列表：口径 / 时间 / 实体）
    - unsupported（"诚实说不知道"的判定结果）
    - ranking（排名类问题）/ threshold_hours（阈值类问题）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd
import yaml

from .db import ONTOLOGY_DIR, dataset_end

REGIONS = ["华东", "华南", "华北", "华中", "西南", "西北", "东北"]

# 陷阱题术语 → "数据不足"话术（平台刻意不猜测）
UNSUPPORTED_MESSAGES = {
    "退货率": "数据不足：数据仓库中不存在退货/退款表，无法计算退货率。建议补充退货数据源，或改问「妥投率」「履约超时率」。",
    "退款": "数据不足：订单表中无退款字段，无法回答退款相关问题。",
    "毛利": "数据不足：订单/商品表中无成本字段，无法计算毛利/毛利率。",
    "成本": "数据不足：数据集中没有成本数据，无法回答成本相关问题。",
    "库存": "数据不足：数据仓库无库存快照表，无法回答库存相关问题。",
    "安卓": "本体未覆盖「安卓」这一外部概念（平台刻意不猜测）。本体内品牌枚举：苹果 / 华为 / 小米 / OPPO / vivo，可改用具体品牌查询。",
}


def _load_yaml(name: str, ontology_dir: Path = ONTOLOGY_DIR) -> dict:
    return yaml.safe_load((ontology_dir / name).read_text(encoding="utf-8"))


def _load_yaml_optional(name: str, ontology_dir: Path = ONTOLOGY_DIR) -> dict | None:
    p = ontology_dir / name
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


@dataclass
class TimeRange:
    start: pd.Timestamp
    end_excl: pd.Timestamp
    label: str


@dataclass
class ClarifyPoint:
    id: str                 # variant | time | entity
    prompt: str
    options: list[dict]     # [{"label": str, "payload": dict}]


@dataclass
class Alignment:
    question: str
    metric_id: str | None = None
    variant_id: str | None = None
    filters: dict = field(default_factory=dict)
    time: TimeRange | None = None
    clarify: list[ClarifyPoint] = field(default_factory=list)
    unsupported: str | None = None
    ranking: dict | None = None          # {"dim": carrier|region|category|brand, "metric": id}
    threshold_hours: float | None = None

    def apply(self, payload: dict) -> None:
        if "variant" in payload:
            self.metric_id, self.variant_id = payload["metric"], payload["variant"]
        elif "brand" in payload:
            self.filters["brand"] = payload["brand"]
        elif "customer_like" in payload:
            self.filters["customer_like"] = payload["customer_like"]
        elif "time" in payload:
            self.time = payload["time"]


class Aligner:
    def __init__(self, conn: duckdb.DuckDBPyConnection, profile: str = "full",
                 ontology_dir: Path | str | None = None) -> None:
        self.conn = conn
        self.profile = profile  # full | no_synonyms | no_axioms（消融档位）
        self.ontology_dir = Path(ontology_dir) if ontology_dir else ONTOLOGY_DIR
        self.end = dataset_end(conn)  # 相对时间基准
        self._language_mtimes: dict[str, float] = {}
        self._load_language_sources()

        # 数据值词表（自我同步：改数据即改词典）
        self.carriers = [r[0] for r in conn.execute("SELECT DISTINCT carrier_name FROM carriers").fetchall()]
        self.brands = [r[0] for r in conn.execute("SELECT DISTINCT brand FROM products").fetchall()]
        self.categories = [r[0] for r in conn.execute("SELECT DISTINCT category FROM products").fetchall()]
        self.channels = [r[0] for r in conn.execute("SELECT DISTINCT channel FROM orders").fetchall()]
        self.customer_names = [r[0] for r in conn.execute("SELECT DISTINCT customer_name FROM customers").fetchall()]

    # ------------------------------------------------------ 活体本体热加载

    def _language_paths(self) -> list[Path]:
        d = self.ontology_dir
        return [d / "metrics.yaml", d / "synonyms.yaml", d / "learned.yaml"]

    @property
    def language_mtimes(self) -> dict[str, float]:
        """语法源文件的 mtime 快照（对外只读，供缓存版本号计算）。"""
        return dict(self._language_mtimes)

    _AXIOM_METRICS = ("DelayRate", "DelayCount", "AvgFulfillmentHours")

    def _load_language_sources(self) -> None:
        """加载语法源（含消融档位：no_synonyms 去同义词；no_axioms 去公理/关系指标）。"""
        self.metrics: dict = dict(_load_yaml("metrics.yaml", self.ontology_dir)["metrics"])
        syn = list(_load_yaml("synonyms.yaml", self.ontology_dir)["terms"])
        learned = _load_yaml_optional("learned.yaml", self.ontology_dir) or {}
        self.metrics.update(learned.get("metrics") or {})
        syn.extend(learned.get("terms") or [])

        if self.profile == "no_axioms":  # 消融：失去公理与关系 → 相关指标不可用
            for mid in self._AXIOM_METRICS:
                self.metrics.pop(mid, None)

        # 指标词表（正式别名 + 口语映射）
        use_syn = self.profile != "no_synonyms"
        terms: dict[str, str] = {}
        for mid, mdef in self.metrics.items():
            names = [mdef["zh"], *(mdef.get("synonyms", []) if use_syn else [])]
            for t in names:
                terms[t] = mid
        for e in syn:
            if e["target"]["kind"] == "metric" and use_syn and e["target"]["id"] in self.metrics:
                terms[e["term"]] = e["target"]["id"]
        self.metric_terms = sorted(terms.items(), key=lambda kv: -len(kv[0]))

        axiom_base = {e["term"] for e in syn if e["target"]["kind"] == "axiom"} | {"超时", "履约超时"}
        self.axiom_terms = axiom_base if self.profile != "no_axioms" else set()
        self._language_mtimes = {str(p): (p.stat().st_mtime if p.exists() else 0.0)
                                 for p in self._language_paths()}

    def maybe_reload(self) -> bool:
        """检测语法源变更（如现场教学写入 learned.yaml）并热重载。"""
        cur = {str(p): (p.stat().st_mtime if p.exists() else 0.0) for p in self._language_paths()}
        if cur != self._language_mtimes:
            self._load_language_sources()
            return True
        return False

    # ---------------------------------------------------------- 时间解析

    def _last_n_days(self, n: int) -> TimeRange:
        e = self.end.normalize()
        s = e - pd.Timedelta(days=n - 1)
        return TimeRange(s, e + pd.Timedelta(days=1), f"近{n}天（{s:%m/%d}–{e:%m/%d}）")

    def _month(self, y: int, m: int, label: str) -> TimeRange:
        start = pd.Timestamp(year=y, month=m, day=1)
        end_excl = start + pd.offsets.MonthBegin(1)
        cap = self.end.normalize() + pd.Timedelta(days=1)
        if end_excl > cap:  # 截止日所在月未结束
            end_excl = cap
        last = end_excl - pd.Timedelta(days=1)
        return TimeRange(start, end_excl, f"{label}（{start:%m/%d}–{last:%m/%d}）")

    def _time_options(self) -> list[dict]:
        opts = [self._last_n_days(7), self._month(self.end.year, self.end.month, "本月"), self._last_n_days(30)]
        return [{"label": tr.label, "payload": {"time": tr}} for tr in opts]

    def resolve_time(self, q: str) -> tuple[str, object]:
        """返回 ("range", TimeRange) | ("ambiguous", options) | ("none", None)"""
        y = self.end.year
        m = re.search(r"(\d{1,2})月(\d{1,2})日\s*[到至~]\s*(\d{1,2})月(\d{1,2})日", q)
        if m:
            m1, d1, m2, d2 = (int(x) for x in m.groups())
            start = pd.Timestamp(year=y, month=m1, day=d1)
            end_excl = pd.Timestamp(year=y, month=m2, day=d2) + pd.Timedelta(days=1)
            return "range", TimeRange(start, end_excl, f"{m1}/{d1}–{m2}/{d2}")
        m = re.search(r"(\d{4})年(\d{1,2})月", q)
        if m:
            return "range", self._month(int(m.group(1)), int(m.group(2)), f"{m.group(1)}年{m.group(2)}月")
        m = re.search(r"(上|本|这个)个?月", q)
        if m:
            if m.group(1) == "上":
                last = self.end.replace(day=1) - pd.Timedelta(days=1)
                return "range", self._month(last.year, last.month, "上月")
            return "range", self._month(self.end.year, self.end.month, "本月")
        m = re.search(r"(近|最近)(\d+)(?:个)?天", q)
        if m:
            return "range", self._last_n_days(int(m.group(2)))
        if re.search(r"(近|最近|这)\s*(?:一)?(?:周|星期)", q):
            return "range", self._last_n_days(7)
        m = re.search(r"(\d{1,2})月", q)
        if m:
            mi = int(m.group(1))
            return "range", self._month(y, mi, f"{y}年{mi}月")
        if re.search(r"最近|近期|这几天", q):
            return "ambiguous", self._time_options()
        return "none", None

    # ---------------------------------------------------------- 组合检测

    @staticmethod
    def _detect_threshold(q: str) -> float | None:
        m = re.search(r"(?:超过|大于|高于)\s*(\d+(?:\.\d+)?)\s*个?\s*小时", q)
        return float(m.group(1)) if m else None

    def _covered_by_metric(self, word: str, a: Alignment) -> bool:
        """词已被“指标名/别名”本身包含时，不再重复提取为筛选条件。"""
        if not a.metric_id or a.metric_id not in self.metrics:
            return False
        m = self.metrics[a.metric_id]
        names = [m.get("zh", ""), *(m.get("synonyms") or [])]
        return any(word and word in n for n in names)

    @staticmethod
    def _detect_variant(q: str, mdef: dict) -> str | None:
        """按本体声明的 keywords 识别用户口语中的**显式口径**（如「净实付」「按已签收」）。

        命中则无需再澄清口径；未命中且多口径无默认值时，仍由调用方触发澄清。
        采用最长关键词优先，避免「取消」盖掉「剔除已取消」。
        """
        best, best_len = None, 0
        for v in mdef.get("variants") or []:
            for kw in v.get("keywords") or []:
                if kw in q and len(kw) > best_len:
                    best, best_len = v["id"], len(kw)
        return best

    def _detect_ranking(self, q: str, metric_id: str | None) -> dict | None:
        if not any(w in q for w in ("最多", "最高", "最大")):
            return None
        dim = None
        for kw, d in [("承运商", "carrier"), ("区域", "region"), ("大区", "region"),
                      ("品类", "category"), ("品牌", "brand")]:
            if kw in q:
                dim = d
                break
        if dim is None:
            return None
        if "妥投" in q:
            rmetric = "SignedRate"
        elif "超时" in q:
            rmetric = "DelayCount"
        else:
            rmetric = metric_id
        return {"dim": dim, "metric": rmetric}

    # ---------------------------------------------------------- 主入口

    def align(self, q: str) -> Alignment:
        self.maybe_reload()  # 活体本体：教学后即刻生效
        a = Alignment(question=q)

        # 1) 陷阱题：本体刻意不覆盖 → 诚实说"不知道"
        for term, msg in UNSUPPORTED_MESSAGES.items():
            if term in q:
                a.unsupported = msg
                return a

        # 2) 指标识别（最长匹配）
        hits = [(t, mid) for t, mid in self.metric_terms if t in q]
        if hits:
            a.metric_id = max(hits, key=lambda kv: len(kv[0]))[1]
        # "超时"上下文规则：率/占比 → DelayRate；数量词 → DelayCount
        if a.metric_id is None and any(t in q for t in self.axiom_terms):
            if any(w in q for w in ("率", "占比", "比例")):
                a.metric_id = "DelayRate"
            elif any(w in q for w in ("多少", "数量", "几单", "几个")) or "有多少" in q:
                a.metric_id = "DelayCount"
            elif "最多" in q:
                a.metric_id = "DelayCount"
            else:
                a.metric_id = "DelayRate"

        # 3) 时间
        kind, payload = self.resolve_time(q)
        if kind == "range":
            a.time = payload
        elif kind == "ambiguous":
            a.clarify.append(ClarifyPoint("time", "时间范围不明确，请选择：", payload))

        # 4) 实体对齐：显式客户名 > 品牌；品牌与客户名重合时触发实体澄清
        q_wo = q
        explicit = [n for n in self.customer_names if len(n) >= 4 and n in q]
        for n in explicit:
            q_wo = q_wo.replace(n, "")
        if explicit:
            a.filters["customer"] = explicit[0]

        brands_hit = sorted((b for b in self.brands if b in q_wo), key=q_wo.index)
        if len(brands_hit) >= 2:
            a.filters["brands"] = brands_hit   # 保持提问中的出现顺序，便于人造对比
        elif len(brands_hit) == 1:
            b = brands_hit[0]
            cust_like = [n for n in self.customer_names if b in n and len(n) >= 4]
            if cust_like and not explicit:
                a.clarify.append(ClarifyPoint(
                    "entity", f"「{b}」指商品品牌还是客户？", [
                        {"label": f"商品品牌「{b}」", "payload": {"brand": b}},
                        {"label": f"客户名称含「{b}」（如 {cust_like[0]}，共 {len(cust_like)} 家）",
                         "payload": {"customer_like": b}},
                    ]))
            else:
                a.filters["brand"] = b

        # 区域 / 承运商 / 品类 / 渠道（若词已被指标名包含，则不再作为筛选条件）
        for r in REGIONS:
            if r in q and not self._covered_by_metric(r, a):
                a.filters["region"] = r
                break
        for k in self.carriers:
            if k in q and not self._covered_by_metric(k, a):
                a.filters["carrier"] = k
                break
        for c in self.categories:
            if c in q and not self._covered_by_metric(c, a):
                a.filters["category"] = c
                break

        # 5) 排名 / 阈值
        a.ranking = self._detect_ranking(q, a.metric_id)
        a.threshold_hours = self._detect_threshold(q) if self.profile != "no_axioms" else None

        # 6) 口径：先按口语关键词识别显式口径；未识别且多口径无默认 → 必须问
        if a.metric_id and a.metric_id in self.metrics:
            mdef = self.metrics[a.metric_id]
            if a.variant_id is None:
                a.variant_id = self._detect_variant(q, mdef)
            if a.variant_id is None and not a.ranking \
                    and mdef.get("default_variant") is None and len(mdef.get("variants", [])) > 1:
                a.clarify.append(ClarifyPoint(
                    "variant", f"「{mdef['zh']}」有多种口径，请选择：", [
                        {"label": v["zh"], "payload": {"metric": a.metric_id, "variant": v["id"]}}
                        for v in mdef["variants"]]))

        # 7) 时间缺失 → 澄清（指标/排名/阈值类问题必须带时间）
        if a.time is None and (a.metric_id or a.ranking or a.threshold_hours is not None) \
                and not any(p.id == "time" for p in a.clarify):
            a.clarify.append(ClarifyPoint("time", "未指明时间范围，请选择：", self._time_options()))

        # 8) 动态未指定 → 诚实说"不知道"
        if a.metric_id is None and a.ranking is None and a.threshold_hours is None and not a.unsupported:
            if any(w in q for w in ("增长", "环比", "同比")):
                a.unsupported = "未指定指标：请说明「增长」的对象（如 GMV、订单量、履约超时率），平台不会猜测。"
            else:
                a.unsupported = ("无法将问题映射到本体概念/指标。v0 覆盖：GMV / 订单量 / 妥投率 / 履约超时率 / "
                                 "超时运单数 / 平均履约时长（可按区域/品牌/品类/承运商筛选，支持排名与时长阈值）。")
        if a.unsupported:
            # 数据不足优先级最高：既然答不了，就不该再追问口径/时间（避免"幻觉式追问"）
            a.clarify = []
        return a
