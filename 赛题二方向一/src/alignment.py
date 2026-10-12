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
import hashlib
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
        self._language_digests = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
                                 for p in self._language_paths()}

    def maybe_reload(self) -> bool:
        """检测语法源变更（如现场教学写入 learned.yaml）并热重载。"""
        cur = {str(p): (p.stat().st_mtime if p.exists() else 0.0) for p in self._language_paths()}
        contents = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
                    for p in self._language_paths()}
        if cur != self._language_mtimes or contents != self._language_digests:
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
        if start < cap < end_excl:  # 仅截断包含截止日的月份，未来月份保留合法空窗口
            end_excl = cap
        last = end_excl - pd.Timedelta(days=1)
        return TimeRange(start, end_excl, f"{label}（{start:%m/%d}–{last:%m/%d}）")

    def _time_options(self) -> list[dict]:
        opts = [self._last_n_days(7), self._month(self.end.year, self.end.month, "本月"), self._last_n_days(30)]
        return [{"label": tr.label, "payload": {"time": tr}} for tr in opts]

    def resolve_time(self, q: str) -> tuple[str, object]:
        """返回 ("range", TimeRange) | ("ambiguous", options) | ("none", None)"""
        y = self.end.year
        m = re.search(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日\s*[到至~]\s*"
                      r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", q)
        if m:
            y1, m1, d1, y2, m2, d2 = m.groups()
            start = pd.Timestamp(year=int(y1 or y), month=int(m1), day=int(d1))
            end_excl = pd.Timestamp(year=int(y2 or y1 or y), month=int(m2), day=int(d2)) + pd.Timedelta(days=1)
            return "range", TimeRange(start, end_excl, f"{start:%Y/%m/%d}–{end_excl - pd.Timedelta(days=1):%Y/%m/%d}")
        m = re.search(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", q)
        if m:
            start = pd.Timestamp(year=int(m.group(1) or y), month=int(m.group(2)), day=int(m.group(3)))
            return "range", TimeRange(start, start + pd.Timedelta(days=1), f"{start:%Y/%m/%d}")
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
        if metric_id is not None:
            rmetric = metric_id
        elif "妥投" in q or "签收率" in q:
            rmetric = "SignedRate"
        elif "超时" in q:
            rmetric = "DelayCount"
        else:
            rmetric = metric_id
        return {"dim": dim, "metric": rmetric}

    def _unsupported_composition(self, q: str, a: Alignment) -> str | None:
        """拒绝尚不能表达的运算，避免只执行问题中已识别的一小部分。"""
        if re.search(r"(?:前|top\s*)\s*(?:\d+|[一二三四五六七八九十]+)\s*(?:名|个)?", q, re.IGNORECASE):
            return "当前排名只支持最高/最多的第1名，尚不支持Top-N列表。"
        if re.search(r"按天|每天|逐日|每日|按周|按月|趋势|走势", q):
            return "当前查询尚不支持时间序列分组，请给出单一时间窗口聚合。"
        if re.search(r"(?:金额|实付|价格|单价|每笔|订单)\s*(?:大于|小于|超过|低于|高于|[<>]=?)\s*\d|\d\s*元", q):
            return "当前查询尚不支持金额或单价阈值筛选，不能忽略这个条件。"
        if "已完成" in q and not self._covered_by_metric("已完成", a):
            return "当前查询尚不支持已完成状态筛选，请使用明确的全部订单或有效订单口径。"
        named_brand = re.search(r"([\u4e00-\u9fffA-Za-z0-9]{1,12})品牌", q)
        if named_brand and not any(named_brand.group(1).endswith(b) for b in self.brands) \
                and not named_brand.group(1).endswith(("哪个", "什么", "各", "所有", "的")):
            return "指定品牌不在当前数据值词表中，不能忽略品牌条件后返回全量。"
        if any(w in q for w in ("增长", "环比", "同比", "相比", "相较")) \
                or re.search(r"比.+(?:高|低|多|少|变化|差)", q):
            if a.metric_id is None:
                return "未指定指标：请说明比较的指标；当前引擎尚不支持增长、环比或同比计算。"
            return "当前引擎尚不支持增长、环比或同比计算，请分别查询两个明确时间窗口。"

        # 一个连续的日范围可以包含两个月份；其余多时间表达不能折叠为首月。
        day_range = re.search(r"(?:\d{4}年)?\d{1,2}月\d{1,2}日\s*[到至~]\s*"
                              r"(?:\d{4}年)?\d{1,2}月\d{1,2}日", q)
        if not day_range and re.search(r"月\d{1,2}日\s*[到至~\-]\s*\d{1,2}日", q):
            return "当前引擎要求完整起止日期，例如「8月1日到8月7日」，请补充结束日期的月份。"
        time_text = q[:day_range.start()] + q[day_range.end():] if day_range else q
        anchors = re.findall(r"(?:\d{4}年)?\d{1,2}月|(?:上|本|这个)个?月|"
                             r"(?:近|最近)\d+(?:个)?天|(?:近|最近|这)\s*(?:一)?(?:周|星期)", time_text)
        if len(anchors) + bool(day_range) > 1 \
                or (not day_range and re.search(r"\d{1,2}月\s*(?:到|至|~|-|和|与|、)\s*\d{1,2}月", q)):
            return "当前引擎尚不支持多时间窗口或跨月范围，请给出一个月份或明确的起止日期。"

        # 区域/承运商/品类/渠道暂为单值；品牌已有独立分组路径。
        for label, values in (("区域", REGIONS), ("承运商", self.carriers),
                              ("品类", self.categories), ("渠道", self.channels)):
            hits = [v for v in values if v in q and not self._covered_by_metric(v, a)]
            if len(hits) > 1:
                return f"当前引擎尚不支持多个{label}的并列筛选或对比，请分别查询。"
        entity_values = [*REGIONS, *self.brands, *self.categories, *self.carriers, *self.channels]
        for word in entity_values:
            if re.search(r"(?:排除|除去|不含|剔除|去掉|除了)\s*" + re.escape(word), q):
                return "当前引擎尚不支持实体排除条件，请使用明确的包含筛选条件。"
        if re.search(r"各(?:区域|地区|大区|承运商|品类|渠道|客户)", q) \
                or ("分组" in q and not re.search(r"品牌.*分组|分组.*品牌", q)):
            return "当前引擎只支持品牌对比和单维度第一名查询，尚不支持该分组查询。"
        return None

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
            # 短词可能是长指标名称的一部分；独立出现的第二个指标则不能被丢弃。
            longest = max(hits, key=lambda kv: len(kv[0]))[0]
            remaining = q.replace(longest, "")
            if any(mid != a.metric_id and term in remaining for term, mid in hits):
                a.unsupported = "当前引擎一次查询仅支持一个指标，请分别查询各指标。"
                return a
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
        a.unsupported = self._unsupported_composition(q, a)
        if a.unsupported:
            return a
        try:
            kind, payload = self.resolve_time(q)
        except (ValueError, OverflowError):
            a.unsupported = "时间表达无效：请使用合法的月份和日期。"
            return a
        if kind == "range":
            a.time = payload
            if a.time.end_excl <= a.time.start:
                a.unsupported = "时间范围无效：结束日期必须不早于开始日期，最近天数必须大于零。"
                return a
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
        for channel in self.channels:
            if channel.lower() in q.lower() and not self._covered_by_metric(channel, a):
                a.filters["channel"] = channel
                break

        # 5) 排名 / 阈值
        a.ranking = self._detect_ranking(q, a.metric_id)
        a.threshold_hours = self._detect_threshold(q) if self.profile != "no_axioms" else None
        # 「履约时长」也可只是阈值计数的属性，不能被口语别名误判为 AVG 请求。
        if a.threshold_hours is not None and a.metric_id == "AvgFulfillmentHours" \
                and "平均" not in q and any(w in q for w in ("多少", "数量", "几单", "几个")):
            a.metric_id = None
        if a.threshold_hours is not None and a.metric_id is not None:
            a.unsupported = "当前时长阈值查询只支持已签收运单计数，尚不支持与其他指标组合。"
            a.clarify = []
            return a
        if a.threshold_hours is not None and a.ranking:
            a.unsupported = "当前引擎尚不支持时长阈值与排名组合，请分别查询。"
            a.clarify = []
            return a
        if a.threshold_hours is not None and len(a.filters.get("brands", [])) > 1 \
                and any(w in q for w in ("对比", "比较", "各自", "分别")):
            a.unsupported = "当前引擎尚不支持时长阈值的品牌分组对比，请分别查询各品牌。"
            a.clarify = []
            return a

        # 6) 口径：先按口语关键词识别显式口径；未识别且多口径无默认 → 必须问
        if a.metric_id and a.metric_id in self.metrics:
            mdef = self.metrics[a.metric_id]
            if a.variant_id is None:
                a.variant_id = self._detect_variant(q, mdef)
            if a.variant_id is None \
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
