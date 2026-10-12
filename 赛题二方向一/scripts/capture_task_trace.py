"""One actual repair loop and two fault variants; no fabricated model fallback."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.task_runtime import TaskRuntime


def main():
    output = ROOT / "评审实验" / "真实Agent轨迹"
    output.mkdir(parents=True, exist_ok=True)
    runtime = TaskRuntime()
    assert all(row["delivered"] is None for row in runtime.evidence[1]["rows"])
    scenarios = {}
    for _ in range(3):
        state = runtime.step("deepseek")
        print(json.dumps({"scenario": "denominator", "state": state["state"], "decision": state["last_decision"]}, ensure_ascii=False), flush=True)
        if state["last_decision"]["tool"] == "planner_failed": raise RuntimeError("actual model planning failed")
    assert state["claim"] and state["claim"]["valid"]
    assert abs(state["comparison"]["rates"]["A"]-.1) < 1e-10
    assert abs(state["comparison"]["rates"]["B"]-.072) < 1e-10
    scenarios["denominator_repair"] = state
    sql_count = sum(len(e["queries"]) for e in state["evidence"])
    runtime.set_weights(.8)
    assert runtime.trace[4]["result"]["claim"]["valid"] is True
    state = runtime.step("protocol")
    assert state["comparison"]["better_carrier"] == "A"
    assert sum(len(e["queries"]) for e in state["evidence"]) == sql_count
    scenarios["weight_reuse_offline"] = state
    runtime.reset(preset="missing_slice", archive_enabled=True)
    state = runtime.step("deepseek")
    print(json.dumps({"scenario": "missing_archive", "state": state["state"], "decision": state["last_decision"]}, ensure_ascii=False), flush=True)
    assert not state["feedback"]["missing"] and state["last_decision"]["arguments"]["source"] == "archive"
    scenarios["missing_archive_repair"] = state
    runtime.reset(preset="missing_slice", archive_enabled=False)
    state = runtime.step("deepseek")
    print(json.dumps({"scenario": "missing_blocked", "state": state["state"], "decision": state["last_decision"]}, ensure_ascii=False), flush=True)
    assert state["state"] == "needs_clarification" and not state["claim"]
    scenarios["missing_no_permission"] = state
    runtime.reset(preset="clean")
    runtime.step()
    runtime.step()
    runtime.mutate("data_change")
    state = runtime.snapshot()
    assert not state["claim"]["valid"] and not any(e["valid"] for e in state["evidence"])
    assert state["trace"][0]["result"]["evidence"]["valid"] is True
    assert state["trace"][3]["result"]["claim"]["valid"] is True
    scenarios["whole_snapshot_invalidation_offline"] = state
    record = {"schema_version": "task-recovery-experiment/v2", "synthetic": True,
              "scope": "5 real next-action calls across 3 bounded scenarios; offline checks explicitly labelled",
              "scenarios": scenarios}
    path = output / "实际闭环与故障变体.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Actual trace and targeted checks saved.", flush=True)


if __name__ == "__main__": main()
