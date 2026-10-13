"""Synthetic, executable task recovery workbench. Model proposals are never facts.

SQL runs against a small DuckDB warehouse through the existing Compiler. Handles,
coverage checks and claims are server-owned; the archive is another view of the
same warehouse, not independent corroboration. This is a bounded demonstration.
"""
from __future__ import annotations

import hashlib
import copy
import json
import math
from datetime import datetime
from pathlib import Path
from threading import RLock

import duckdb
import pandas as pd

from .alignment import Alignment, TimeRange
from .compiler import Compiler
from .db import DB_PATH
from .scenario_fixture import materialize


REGIONS = ("华东", "华南")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    default=str).encode()).hexdigest()[:16]


class TaskRuntime:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.lock = RLock()
        self.conn = duckdb.connect(":memory:")
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.scenario_source = "builtin"
        self.reset()

    def _fixture(self):
        """刷新场景工作副本：来自主仓库 demo schema，缺失时用内置定义。"""
        self.scenario_source = materialize(self.conn, self.db_path)
        base = {"zh": "计数", "table": "shipments", "time_basis": "s.ship_time",
                "default_variant": "count"}
        self.compiler = Compiler({key: {**base, "variants": [{"id": "count", "zh": key, "expr": expr}]}
            for key, expr in {"ObservedCount": "COUNT(*)", "CompletedCount": "COUNT(*) FILTER (WHERE s.delivery_time IS NOT NULL)",
                             "DelayCount": "COUNT(*) FILTER (WHERE s.delivery_time > s.promised_time)"}.items()})

    def _revision(self):
        # Whole snapshot detection, deliberately not incremental lineage.
        return digest(self.conn.execute("SELECT * FROM shipments ORDER BY shipment_id").fetchall())

    def reset(self, preset="denominator_conflict", east_weight=0.2, archive_enabled=True,
              allow_scope_change=False, goal=None):
        with self.lock:
            if preset not in {"denominator_conflict", "missing_slice", "clean"}:
                raise ValueError("unknown preset")
            self._weight(east_weight)
            self._fixture()
            self.provider = {"missing_B_south": preset == "missing_slice", "legacy_B_default": preset == "denominator_conflict",
                             "archive_enabled": bool(archive_enabled)}
            self.task = {"id": digest([preset, datetime.now().isoformat()]),
                         "goal": goal or "按已妥投口径、同一发货时间窗比较 A/B；保留所有正权重区域，并说明换承运商能否改善。",
                         "east_weight": float(east_weight), "weights": {"华东": float(east_weight), "华南": 1-float(east_weight)},
                         "required_variant": "delivered_only", "time_window": "2026-09-01 / 2026-10-01（发货时间，含始不含终）",
                         "require_full": True, "allow_scope_change": bool(allow_scope_change)}
            self.evidence, self.trace, self.comparison, self.claim = [], [], None, None
            self.last_decision = None
            self.metrics = {"tool_calls": 0, "repairs": 0, "model_calls": 0, "current_revision": self._revision()}
            self.paused = False
            # Inputs genuinely come from legacy product requests, not the model.
            self.action("request_evidence", {"carrier": "A", "source": "primary", "variant": None, "regions": list(REGIONS)}, actor="既有产品")
            self.action("request_evidence", {"carrier": "B", "source": "primary", "variant": None, "regions": list(REGIONS)}, actor="既有产品")
            return self.snapshot()

    @staticmethod
    def _weight(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("east_weight must be finite within [0,1]")

    def _active(self):
        return [r for r, w in self.task["weights"].items() if w > 0]

    def _signature(self):
        return digest({"task": self.task, "revision": self.metrics["current_revision"],
                       "provider": self.provider})

    def _latest(self, carrier, region):
        for e in reversed(self.evidence):
            if e["valid"] and e["carrier"] == carrier and e["variant"] == "delivered_only":
                for row in e["rows"]:
                    if row["region"] == region and row["delivered"] > 0:
                        return e, row
        return None

    def _requirements(self):
        missing, conflicts = [], []
        for carrier in ("A", "B"):
            for region in self._active():
                if self._latest(carrier, region):
                    continue
                wrong = next((e for e in reversed(self.evidence) if e["valid"] and e["carrier"] == carrier
                              and any(r["region"] == region for r in e["rows"]) and e["variant"] != "delivered_only"), None)
                if wrong:
                    conflicts.append({"carrier": carrier, "region": region, "field": "denominator.variant",
                                      "expected": "delivered_only", "actual": wrong["variant"], "evidence_id": wrong["id"]})
                else:
                    missing.append({"carrier": carrier, "region": region, "weight": self.task["weights"][region]})
        return conflicts, missing

    def _feedback(self):
        conflicts, missing = self._requirements()
        if conflicts:
            code, message = "denominator_conflict", "B 的产品默认分母含在途，任务要求已妥投；需要按字段冲突重新取证。"
        elif missing:
            code, message = "missing_positive_weight_slice", "正权重区域缺证；不能填零、静默删区域或重新归一化。"
        elif self.claim and self.claim["valid"]:
            code, message = "finalized", "描述性结论已定稿；因果收益仍未证实。"
        elif self.comparison and self.comparison["signature"] == self._signature():
            code, message = "ready_to_finalize", "同口径且覆盖充分，可以定稿当前条件下的描述性比较。"
        else:
            code, message = "ready_to_derive", "有效计数已覆盖所有正权重区域，可以复用证据计算。"
        counterexamples = []
        # Explicit hypothetical completions, not warehouse evidence or imputations.
        if missing and any(m["carrier"] == "B" and m["region"] == "华南" for m in missing):
            a = sum(self.task["weights"][r] * (self._latest("A", r)[1]["rate"] if self._latest("A", r) else 0)
                    for r in self._active())
            east = self._latest("B", "华东")
            if east and self.task["weights"]["华南"] > 0:
                for assumed in (0.0, 0.2):
                    b = self.task["weights"]["华东"] * east[1]["rate"] + self.task["weights"]["华南"] * assumed
                    counterexamples.append({"label": "假设补全，非真实观测", "assumed_B_south_rate": assumed,
                                            "A_rate": a, "B_rate": b, "better_carrier": "A" if a < b else "B"})
        options = self.available_actions(conflicts, missing)
        if missing and self.task["allow_scope_change"]:
            options += [{"tool": "authorize_scope", "arguments": {"region": "华东"},
                         "label": "用户显式授权仅比较华东（改变任务范围）", "actor": "人类"}]
        return {"code": code, "message": message, "conflicts": conflicts, "missing": missing,
                "counterexamples": counterexamples, "options": options}

    def available_actions(self, conflicts=None, missing=None):
        if conflicts is None:
            conflicts, missing = self._requirements()
        actions = []
        for carrier in ("A", "B"):
            regions = list(dict.fromkeys(x["region"] for x in conflicts + missing if x["carrier"] == carrier))
            if regions:
                actions.append({"tool": "request_evidence", "arguments": {"carrier": carrier, "source": "primary",
                    "variant": "delivered_only", "regions": regions}, "label": f"按已妥投重取 {carrier}"})
                if self.provider["archive_enabled"]:
                    actions.append({"tool": "request_evidence", "arguments": {"carrier": carrier, "source": "archive",
                        "variant": "delivered_only", "regions": regions}, "label": f"同仓备用视图补取 {carrier}"})
        if not conflicts and not missing:
            if self.comparison and self.comparison["signature"] == self._signature():
                actions.append({"tool": "finalize_claim", "arguments": {}, "label": "定稿描述性比较"})
            else:
                actions.append({"tool": "derive_comparison", "arguments": {}, "label": "复用计数计算"})
        actions += [{"tool": "request_clarification", "arguments": {}, "label": "请求用户处理缺证/范围"},
                    {"tool": "stop", "arguments": {}, "label": "停止当前任务"}]
        return actions

    def observation(self):
        return {"task": self.task, "allowed_regions": self._active(), "provider": self.provider,
                "allowed_tools": list(dict.fromkeys(a["tool"] for a in self.available_actions())),
                "available_actions": self.available_actions(), "feedback": {**self._feedback(),
                    "options": self.available_actions()},
                "evidence": [{k: e[k] for k in ("id", "carrier", "source", "variant", "rows", "valid", "revision", "time_window")}
                             for e in self.evidence], "comparison": self.comparison,
                "history": [{k: t[k] for k in ("tool", "arguments", "result_status", "summary")} for t in self.trace[-8:]]}

    def _record(self, actor, tool, arguments, result, model_decision=None):
        self.metrics["tool_calls"] += 1
        self.trace.append(copy.deepcopy({"step": len(self.trace)+1, "actor": actor, "tool": tool, "arguments": arguments,
                           "result_status": result.get("status", "ok"), "summary": result.get("summary", ""),
                           "result": result, "model_decision": model_decision}))
        return result

    def action(self, tool, arguments=None, *, actor="人类", model_decision=None):
        with self.lock:
            args = arguments or {}
            if not isinstance(args, dict):
                raise ValueError("arguments must be an object")
            if tool == "request_evidence":
                result = self._request(args)
                if actor not in {"既有产品", "人类"} and result.get("status") == "ok":
                    self.metrics["repairs"] += 1
            elif tool == "derive_comparison":
                if args: raise ValueError("unexpected arguments")
                result = self._derive()
            elif tool == "finalize_claim":
                if args: raise ValueError("claims are constructed by server; arguments must be empty")
                result = self._finalize()
            elif tool == "authorize_scope":
                if actor != "人类" or not self.task["allow_scope_change"]:
                    result = {"status": "blocked", "summary": "范围变更只能由用户显式开放并授权。"}
                elif args != {"region": "华东"}:
                    raise ValueError("only explicit East scope supported")
                else:
                    self.task.update(require_full=False, east_weight=1.0, weights={"华东": 1.0, "华南": 0.0})
                    self._invalidate_claim("人类授权仅比较华东；目标范围已显式改变。")
                    self.paused = False
                    result = {"status": "ok", "summary": "用户已授权仅比较华东；不能解释为完成原全域任务。"}
            elif tool in {"request_clarification", "stop"}:
                if args: raise ValueError("unexpected arguments")
                self.paused = True
                result = {"status": "needs_clarification", "summary": "等待用户补证、开放备用视图或明确改变任务范围。"}
            else:
                raise ValueError("unknown task tool")
            return self._record(actor, tool, args, result, model_decision)

    def _request(self, args):
        if set(args) != {"carrier", "source", "variant", "regions"}:
            raise ValueError("request_evidence requires carrier/source/variant/regions")
        carrier, source, variant, regions = (args[k] for k in ("carrier", "source", "variant", "regions"))
        if carrier not in {"A", "B"} or source not in {"primary", "archive"} or variant not in {None, "delivered_only", "all_shipments"}:
            raise ValueError("unsupported evidence request")
        if not isinstance(regions, list) or not regions or len(set(regions)) != len(regions) or not set(regions) <= set(REGIONS):
            raise ValueError("invalid regions")
        if source == "archive" and not self.provider["archive_enabled"]:
            return {"status": "blocked", "summary": "备用视图未开放；模型不能授予访问权限。"}
        variant = variant or ("all_shipments" if carrier == "B" and self.provider["legacy_B_default"] else "delivered_only")
        rows, queries, absent = [], [], []
        for region in regions:
            if carrier == "B" and region == "华南" and source == "primary" and self.provider["missing_B_south"]:
                absent.append(region)
                continue
            counts = {}
            denominator_metric = "CompletedCount" if variant == "delivered_only" else "ObservedCount"
            for metric in (denominator_metric, "DelayCount"):
                compiled = self.compiler.compile(Alignment(question="<task evidence>", metric_id=metric, variant_id="count",
                    filters={"carrier": carrier, "region": region}, time=TimeRange(pd.Timestamp("2026-09-01"), pd.Timestamp("2026-10-01"), "2026年9月")))
                counts[metric] = self.conn.execute(compiled.sql, compiled.params).fetchone()[0]
                queries.append({"metric": metric, "region": region, "sql": compiled.sql, "params": [str(p) for p in compiled.params], "value": counts[metric]})
            denominator = counts[denominator_metric]
            rows.append({"region": region, "total": counts.get("ObservedCount"), "delivered": counts.get("CompletedCount"),
                         "delayed": counts["DelayCount"], "rate": counts["DelayCount"]/denominator if denominator else None})
        evidence = {"id": "E"+str(len(self.evidence)+1), "carrier": carrier, "source": source, "variant": variant,
                    "time_window": self.task["time_window"], "grain": "one shipment per order, grouped carrier/region",
                    "rows": rows, "absent_regions": absent, "queries": queries,
                    "revision": self.metrics["current_revision"], "valid": True}
        self.evidence.append(evidence)
        self.comparison = None
        self._invalidate_claim("新证据到达，重新检查。")
        self.paused = False
        return {"status": "ok", "summary": f"{evidence['id']} · {carrier} · {variant} · 实际 SQL 返回 {len(rows)} 个区域，缺失 {absent or '无'}",
                "evidence": evidence, "feedback": self._feedback()}

    def _derive(self):
        conflicts, missing = self._requirements()
        if conflicts or missing:
            return {"status": "blocked", "summary": "口径/覆盖条件未满足，禁止构造完整区域比较。", "feedback": self._feedback()}
        rates, refs = {}, []
        for carrier in ("A", "B"):
            rates[carrier] = 0.0
            for region in self._active():
                e, row = self._latest(carrier, region)
                rates[carrier] += self.task["weights"][region]*row["rate"]
                refs.append({"evidence_id": e["id"], "carrier": carrier, "region": region,
                             "delayed": row["delayed"], "denominator": row["delivered"]})
        self.comparison = {"rates": rates, "better_carrier": "tie" if abs(rates["A"]-rates["B"]) < 1e-12 else ("A" if rates["A"] < rates["B"] else "B"),
                           "difference_pp": abs(rates["A"]-rates["B"])*100, "weights": dict(self.task["weights"]),
                           "coverage": 1.0, "claim_id": None, "signature": self._signature(), "evidence_refs": refs}
        self.paused = False
        return {"status": "ok", "summary": "复用有效计数完成标准化比较；未重新读取 SQL。", "comparison": self.comparison}

    def _finalize(self):
        if (self._requirements() != ([], []) or not self.comparison or
                self.comparison["signature"] != self._signature()):
            return {"status": "blocked", "summary": "必须先有当前条件下的有效比较，不能直接定稿。"}
        c = self.comparison
        scope = "、".join(self._active())
        summary = f"在 {scope} 的当前权重与已妥投口径下，A 超时率 {c['rates']['A']:.2%}，B {c['rates']['B']:.2%}；" + (
            "两者相同。" if c["better_carrier"] == "tie" else f"{c['better_carrier']} 的历史描述性率较低，差 {c['difference_pp']:.2f} 个百分点。")
        self.claim = {"id": "C"+digest(c), "task_id": self.task["id"], "type": "descriptive_comparison", "valid": True, "summary": summary,
                      "conditions": {"scope": scope, "weights": dict(self.task["weights"]), "variant": "delivered_only",
                                     "revision": self.metrics["current_revision"], "time_window": self.task["time_window"]},
                      "unresolved": "换承运商的因果收益尚无干预/混杂证据，不能由历史率差推出。",
                      "evidence_refs": c["evidence_refs"]}
        c["claim_id"] = self.claim["id"]
        return {"status": "ok", "summary": summary, "claim": self.claim}

    def _invalidate_claim(self, reason):
        if self.claim:
            self.claim.update(valid=False, invalidation_reason=reason)

    def set_weights(self, east_weight):
        with self.lock:
            self._weight(east_weight)
            self.task.update(east_weight=float(east_weight), weights={"华东": float(east_weight), "华南": 1-float(east_weight)})
            self.comparison = None
            self._invalidate_claim("用户改变权重；原计数仍可复用，但原结论条件已失效。")
            self.paused = False
            self._record("人类", "change_weights", {"east_weight": east_weight}, {"status": "ok", "summary": "权重已改；保留有效计数，仅重算比较。"})
            return self.snapshot()

    def mutate(self, kind, value=None):
        with self.lock:
            if kind in {"missing_region", "restore_region"}:
                self.provider["missing_B_south"] = kind == "missing_region"
                # Withdraw handles from the affected source, including inherited claims.
                if kind == "missing_region":
                    for e in self.evidence:
                        if e["source"] == "primary" and e["carrier"] == "B" and any(r["region"] == "华南" for r in e["rows"]):
                            e["valid"] = False
            elif kind == "archive_toggle":
                self.provider["archive_enabled"] = bool(value)
                if not value:
                    for e in self.evidence:
                        if e["source"] == "archive": e["valid"] = False
            elif kind == "data_change":
                self.conn.execute("UPDATE shipments SET delivery_time = promised_time + INTERVAL '12 hours' WHERE shipment_id IN (SELECT s.shipment_id FROM shipments s JOIN orders o ON s.order_id=o.order_id WHERE s.carrier_id=2 AND o.customer_id=2 AND s.delivery_time <= s.promised_time ORDER BY s.shipment_id LIMIT 60)")
                self.metrics["current_revision"] = self._revision()
                for e in self.evidence: e["valid"] = False
            elif kind == "scope_toggle":
                self.task["allow_scope_change"] = bool(value)
            else:
                raise ValueError("unknown mutation")
            self.comparison = None
            self._invalidate_claim("证据来源/数据/任务条件改变，原结论已撤销。")
            self.paused = False
            self._record("平台", kind, {"value": value}, {"status": "ok", "summary": "条件变化已触发结论撤销；数据变化按整个快照失效。"})
            return self.snapshot()

    def step(self, mode="protocol"):
        with self.lock:
            if mode not in {"protocol", "deepseek"}: raise ValueError("unknown planner mode")
            if mode == "deepseek":
                from .task_planner import plan_next
                self.metrics["model_calls"] += 1
                planned = plan_next(self.observation())
                if not planned["ok"]:
                    self.last_decision = {"mode": mode, "model": planned["model"], "tool": "planner_failed", "reason": planned.get("error"), "arguments": {}}
                    self._record("DeepSeek", "planner_failed", {}, {"status": "error", "summary": planned.get("error", "规划失败"),
                                   "actual_model": planned["model"], "usage": planned["usage"]})
                    return self.snapshot()
                decision = planned["decision"]
                actor = planned["model"]
                details = {"decision": decision, "raw_response": planned["raw_response"], "model": actor,
                           "usage": planned["usage"], "permission_denials_count": planned["permission_denials_count"]}
            else:
                choices = self.available_actions()
                # Explicit deterministic offline control, never labelled an LLM.
                choice = next((a for a in choices if a["tool"] == "request_evidence" and a["arguments"]["source"] == "archive"
                               and a["arguments"]["carrier"] == "B" and "华南" in a["arguments"]["regions"] and self.provider["missing_B_south"]), None)
                if not choice and self._requirements()[1] and not self.provider["archive_enabled"] and self.provider["missing_B_south"]:
                    choice = next(a for a in choices if a["tool"] == "request_clarification")
                choice = choice or choices[0]
                decision = {**{k: choice[k] for k in ("tool", "arguments")}, "reason": "离线协议策略依据当前反馈选择，非模型推理。"}
                actor, details = "离线协议", {"decision": decision}
            self.last_decision = {"mode": mode, "model": actor, **decision}
            self.action(decision["tool"], decision["arguments"], actor=actor, model_decision=details)
            return self.snapshot()

    def snapshot(self):
        with self.lock:
            feedback = self._feedback()
            state = ("needs_clarification" if self.paused else "needs_repair" if feedback["conflicts"] else
                     "needs_evidence" if feedback["missing"] else "finalized" if self.claim and self.claim["valid"] else "ready")
            return json.loads(json.dumps({"schema_version": "task-recovery/v1", "synthetic": True, "task": self.task,
                "scenario_source": self.scenario_source,
                "state": state, "evidence": self.evidence, "feedback": feedback, "comparison": self.comparison,
                "claim": self.claim, "trace": self.trace, "metrics": self.metrics, "last_decision": self.last_decision,
                "provider": self.provider}, ensure_ascii=False, default=str))
