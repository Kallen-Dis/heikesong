"""Versioned semantic plans and locally replayable receipts.

Hashes detect accidental modification; they are not signatures or proof of data truth.
SQL received from a client is never executed: the server recompiles a validated plan.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from .alignment import Alignment, TimeRange
from .db import dataset_end

if TYPE_CHECKING:
    from .loop import QueryLoop

TABLES = ("orders", "shipments", "products", "customers", "carriers", "meta")
UNITS = {"GMV": "CNY", "OrderCount": "orders", "SignedRate": "ratio",
         "DelayRate": "ratio", "DelayCount": "shipments", "AvgFulfillmentHours": "hours"}


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        return json_safe(value.item())
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def canonical(value) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def revisions(conn, ontology_dir: Path) -> dict:
    """Fingerprint the actual connection, including in-memory databases.

    The warehouse token uses DuckDB row hashes, counts, and schema. It is a local
    change detector tied to this DuckDB version, not a cryptographic dataset hash.
    """
    semantic = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(Path(ontology_dir).glob("*.yaml"))}
    inventory = {}
    for table in TABLES:
        count, row_hash = conn.execute(
            f"SELECT COUNT(*), SUM(hash(t)) FROM {table} t").fetchone()
        schema = [(r[0], r[1]) for r in conn.execute(f"DESCRIBE {table}").fetchall()]
        inventory[table] = {"rows": count, "row_hash_sum": str(row_hash), "schema": schema}
    return {"semantic": digest(semantic), "data": digest(inventory),
            "data_fingerprint_method": "duckdb-row-hash-sum+count+schema/v1",
            "dataset_end": str(dataset_end(conn).date())}


def make_contract(loop: QueryLoop, alignment: Alignment, compiled,
                  allowed_regions: tuple[str, ...] | None = None) -> dict:
    a = alignment
    mid = (a.ranking or {}).get("metric") or a.metric_id
    definition = loop.aligner.metrics.get(mid, {})
    vid = a.variant_id or definition.get("default_variant")
    variant = next((v for v in definition.get("variants", []) if v["id"] == vid), {})
    grain = "shipment" if a.threshold_hours is not None or definition.get("table") == "shipments" else "order"
    plan = {"question": a.question, "metric_id": a.metric_id, "variant_id": a.variant_id,
            "filters": copy.deepcopy(a.filters), "ranking": copy.deepcopy(a.ranking),
            "threshold_hours": a.threshold_hours,
            "time": {"start": a.time.start.isoformat(), "end_exclusive": a.time.end_excl.isoformat(),
                     "label": a.time.label}}
    contract = {
        "schema_version": "semantica.contract/v1", "plan": plan,
        "meaning": {"metric": mid, "variant": vid,
                    "definition": f"实际发货到签收耗时 > {a.threshold_hours} 小时的运单数"
                    if a.threshold_hours is not None else variant.get("zh"),
                    "expression": variant.get("expr"),
                    "unit": "label" if compiled.kind == "ranking" else "shipments"
                    if a.threshold_hours is not None else UNITS.get(mid, "declared_in_definition"),
                    "metric_unit": UNITS.get(mid, "shipments" if a.threshold_hours is not None else "declared_in_definition"),
                    "result_shape": "dimension_label" if compiled.kind == "ranking" else compiled.kind,
                    "grain": grain, "time_field": "s.ship_time" if a.threshold_hours is not None
                    else definition.get("time_basis"), "operation": compiled.kind},
        "revisions": revisions(loop.conn, loop.aligner.ontology_dir),
        "policy": {"allowed_regions": list(allowed_regions) if allowed_regions is not None else None,
                   "access": "aggregate_only", "authentication": "external_host_required",
                   "max_result_rows": 20},
        "query": {"template": compiled.sql, "parameters": json_safe(compiled.params)},
        "lineage": re.findall(r"(?:FROM|JOIN)\s+(orders|shipments|products|customers|carriers)\b",
                              compiled.sql, re.IGNORECASE),
        "disclosure": compiled.disclosure,
        "limitations": ["数据为固定种子的合成电商物流账本。", "自然语言入口为有限规则解析；不支持任意问题。",
                        "当前关联契约限定每个订单最多一个运单；异常关系会阻断。",
                        "版本指纹用于本地变更检测，不是数字签名或数据真实性证明。"]}
    contract = json_safe(contract)
    contract["contract_id"] = digest(contract)
    return contract


def build_receipt(contract: dict, df: pd.DataFrame, trust: dict, *,
                  resolution: str = "explicit_or_declared_default") -> dict:
    receipt = {
        "schema_version": "semantica.evidence/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contract": contract, "resolution": resolution,
        "result": {"columns": list(df.columns), "row_count": len(df),
                   "rows": json_safe(df.to_dict("records"))}, "trust": json_safe(trust),
        "replay_requirement": "同一语义文件、同一DuckDB版本及同一数据内容；证据包不附带原始数据快照。",
    }
    receipt["receipt_id"] = digest(receipt)
    return receipt


def clarification_payload(clar) -> dict:
    return {"type": "clarification", "question": clar.question,
            "points": [{"id": p.id, "prompt": p.prompt,
                        "options": [{"index": i, "label": o["label"]}
                                    for i, o in enumerate(p.options)]} for p in clar.points],
            "hint": "请让用户明确选择全部澄清点，再传入 choices。"}


def answer_payload(ans) -> dict:
    return json_safe({"type": ans.type, "text": ans.text, "value": ans.value,
                      "rows": ans.rows, "sql": ans.sql, "disclosure": ans.disclosure,
                      "trust": ans.trust, "evidence": ans.evidence})


class QueryGateway:
    """Two-phase plan/execute API. Scope is server configuration, never a tool argument."""

    def __init__(self, loop: QueryLoop, allowed_regions: tuple[str, ...] | None = None):
        self.loop = loop
        self.allowed_regions = tuple(sorted(allowed_regions)) if allowed_regions is not None else None

    def _scope(self, a: Alignment):
        if self.allowed_regions is None:
            return
        requested = a.filters.get("region")
        if requested and requested not in self.allowed_regions:
            raise ValueError("denied_by_policy: 当前角色不允许查询该区域。")
        # Current IR has single-region equality. Never silently use the first region.
        if requested is None:
            if len(self.allowed_regions) != 1:
                raise ValueError("denied_by_policy: 请指定一个获准区域。")
            a.filters["region"] = self.allowed_regions[0]

    def preview(self, question: str, choices: dict[str, int] | None = None) -> dict:
        from .loop import Clarification, select_alignment
        from .semantic_guard import validate_relationships

        a = self.loop.aligner.align(question)
        if a.unsupported:
            return {"type": "insufficient", "status": "unsupported", "text": a.unsupported}
        if a.clarify:
            clar = Clarification(question, list(a.clarify), a)
            if choices is None:
                return clarification_payload(clar)
            try:
                a = select_alignment(clar, choices)
            except ValueError as exc:
                return {"type": "error", "status": "invalid_choices", "text": str(exc)}
        try:
            self._scope(a)
            issues = validate_relationships(self.loop.conn)
            if issues:
                return {"type": "insufficient", "status": "blocked_by_quality", "issues": issues,
                        "text": "数据关系违反当前契约，执行已阻断。"}
            self.loop.compiler.metrics = self.loop.aligner.metrics
            compiled = self.loop.compiler.compile(a)
            # EXPLAIN verifies schema and expressions, without executing the result query.
            self.loop.conn.execute("EXPLAIN " + compiled.sql, compiled.params)
            contract = make_contract(self.loop, a, compiled, self.allowed_regions)
            return {"type": "ready", "contract": contract,
                    "text": "请核对指标、口径、日期和授权范围；确认后执行此契约。"}
        except (ValueError, KeyError) as exc:
            return {"type": "error", "status": "invalid_plan", "text": str(exc)}

    def execute(self, contract: dict) -> dict:
        try:
            candidate = copy.deepcopy(contract)
            token = candidate.pop("contract_id")
            if candidate.get("schema_version") != "semantica.contract/v1" or digest(candidate) != token:
                raise ValueError("契约内容或校验值发生变化，请重新生成计划。")
            self.loop.aligner.maybe_reload()
            if candidate["revisions"] != revisions(self.loop.conn, self.loop.aligner.ontology_dir):
                return {"type": "insufficient", "status": "stale_contract",
                        "text": "数据或语义版本已变更，请重新预览并确认口径。"}
            p = candidate["plan"]
            a = Alignment(question=p["question"], metric_id=p["metric_id"], variant_id=p["variant_id"],
                          filters=p["filters"], ranking=p["ranking"], threshold_hours=p["threshold_hours"],
                          time=TimeRange(pd.Timestamp(p["time"]["start"]),
                                         pd.Timestamp(p["time"]["end_exclusive"]), p["time"]["label"]))
            self._scope(a)
            self.loop.compiler.metrics = self.loop.aligner.metrics
            compiled = self.loop.compiler.compile(a)
            expected = make_contract(self.loop, a, compiled, self.allowed_regions)
            if expected["contract_id"] != token:
                raise ValueError("契约不符合当前编译器或服务端权限策略，请重新预览。")
            ans = self.loop.answer(a)
            if ans.type == "answer" and len(ans.df) > expected["policy"]["max_result_rows"]:
                return {"type": "insufficient", "status": "result_limit",
                        "text": "结果超出本次契约允许行数，请缩小范围。"}
            payload = answer_payload(ans)
            if ans.type == "answer":
                payload["evidence"] = build_receipt(expected, ans.df, ans.trust)
            return payload
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            return {"type": "error", "status": "invalid_contract", "text": str(exc)}

    def replay(self, receipt: dict) -> dict:
        try:
            original = copy.deepcopy(receipt)
            token = original.pop("receipt_id")
            if original.get("schema_version") != "semantica.evidence/v1" or digest(original) != token:
                raise ValueError("证据包校验失败，内容可能已修改。")
            result = self.execute(original["contract"])
            if result["type"] != "answer":
                return result
            actual = result["evidence"]["result"]
            matches = actual == original["result"]
            return {"type": "replay", "matches": matches, "receipt_id": token,
                    "text": "本地重放一致。" if matches else "本地重放结果不同，请检查运行环境。",
                    "expected": original["result"], "actual": actual}
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            return {"type": "error", "status": "invalid_receipt", "text": str(exc)}
