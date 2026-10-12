"""Ten cold, read-only external baselines; no project material is copied to workers."""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_RUNS = ROOT.parent / "tmp" / "blind-deepseek"
OUTPUT = ROOT / "评审实验" / "DeepSeek"
LAUNCHER = Path.home() / ".codex" / "skills" / "deepseek-worker" / "scripts" / "run_worker.py"
PYTHON = os.environ.get("DEEPSEEK_WORKER_PYTHON", "C:/ProgramData/anaconda3/python.exe")

CONTEXT = """数联科技×华东师范大学AI智能体校园黑客松。主办背景为数联科技、华师大数据科学与工程及统计学院、阿里云赞助，面向学生，3—5人队伍，每队完成运营题一及行业垂域题二。DataClawHub已知仅承载报名、组队、作品提交、公开展示、传播互动与统计，不能臆造其SDK/API。允许原型或方案文档，允许公开、模拟、合规自采数据，关注数据/物流/可信数据空间问题。
赛题二三个方向任选。A：AI使用的大数据平台。传统平台服务人、报表、BI，对AI不友好；三问是AI用什么形式数据/如何使用、本体论是否答案、与传统平台如何融合演进。B：多级库存需求预测N天、隐私协同补货、仿真N天比较成本/缺货率/周转。C：跨境多格式多语言PDF/图片/EDI单证提取HS等字段、同票比对、目的国证书和归类风险。
优先为A提出idea，可以借物流场景但不能偷换成B/C应用。评委六维原始100分：价值需求20、完整可用30、AI技术20、创新15、落地10、展示5；计入成绩80%。另官方AI材料20关注完整/逻辑/清晰/可复现，权重未知；跨学院5是队伍属性。初赛5分钟，决赛8+4；原PDF暂定2026-10-14初赛、10-31决赛，最终通知为准。
用户最重视想法先进、逻辑正确、惊艳评委，不要求过度生产实用性或工程测试。你完全不知道任何既有作品或其它基线。
"""

TASK = """这是一次独立冷启动创意基线。仅使用所给赛事背景，从零理解赛题并提出至少3个本质不同的idea。禁止查看任何原项目、其他输出或聊天；不得尝试访问工作目录之外。不要假定已有作品是什么。不联网查证的技术/产业断言应标为待核，不能编造获奖案例或来源。
适用AGENTS：外部worker不继承聊天；只读、唯一输入为源目录official_context.txt；无文件编辑许可；不读取凭据、不更改供应商登录；禁止shell/network/MCP/subagent/skill工具；无需测试。当前workdir只含上述官方背景。
任务内容：解释A三问真正要求什么；设计至少3个不同idea；每项包括新贡献相对产业已有能力、最小demo、AI实际职责、关键假设、最强反驳；选首选，给5分钟输入→选择→工具执行→问题反馈→续作故事和架构。拒绝泛称加RAG/多Agent/MCP就先进。最后给每项概念潜力评分（六维100，不是已完成得分/获奖预测）及区间；首选材料代理按完整/逻辑/清晰/可复现各5总20，注明自设等权非官方。可以出现与其它模型类似的想法，不为追新强造原创；但尽量寻找不同机制。
只返回一个JSON对象，不加代码围栏，中文总内容约1200—1800字。结构：{interpretation:string, ideas:[{name:string, mechanism:string, novelty:string, minimal_demo:string, ai_role:string, assumptions:string, strongest_objection:string, scores:{value:number,completeness:number,ai:number,innovation:number,adoption:number,presentation:number}, total:number,range:string}], recommended:string, five_minute_story:string, architecture:string, falsification:string, material_scores:{completeness:number,logic:number,clarity:number,reproducibility:number,total:number}, caveats:string}。
验收：至少3个不同idea，评分分项合计正确，模型职责具体，未看到/引用原作品。不修改文件。
"""


def prepare(index: int):
    ident = f"D{index:02d}"
    workdir = PRIVATE_RUNS / ident / "source"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "official_context.txt").write_text(CONTEXT, encoding="utf-8")
    task_file = PRIVATE_RUNS / ident / "task.txt"
    prompt = f"实验编号：{ident}。这是全新独立会话。\n" + CONTEXT + "\n" + TASK
    task_file.write_text(prompt, encoding="utf-8")
    return ident, workdir, task_file, prompt


def run(index: int):
    ident, workdir, task_file, prompt = prepare(index)
    raw_path = PRIVATE_RUNS / ident / "worker-result.json"
    env = os.environ.copy()
    env.pop("SSLKEYLOGFILE", None)
    env["PYTHONIOENCODING"] = "utf-8"
    command = [PYTHON, str(LAUNCHER), "--workdir", str(workdir), "--task-file", str(task_file),
               "--mode", "read", "--tools", "Read", "--max-turns", "3", "--timeout", "240",
               "--output-json", str(raw_path)]
    try:
        process = subprocess.run(command, env=env, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=275)
        if raw_path.exists():
            raw = json.loads(raw_path.read_text(encoding="utf-8-sig"))
        else:
            raw = json.loads(process.stdout)
        record = {"id": ident, "generated_at": datetime.now(timezone.utc).isoformat(),
                  "ok": raw.get("ok", False), "exit_code": raw.get("exit_code", process.returncode),
                  "model": raw.get("model"), "usage": raw.get("usage"),
                  "timed_out": raw.get("timed_out", False),
                  "permission_denials": [{"tool": d.get("tool", "Read"), "count": 1,
                      "error": "read_denied: read request rejected by the configured worker permission policy."}
                      for d in (raw.get("permission_denials") or [])],
                  "tool_errors": [{"tool": d.get("tool", "Read"), "count": 1,
                      "error": "read_denied: read request rejected by the configured worker permission policy."}
                      for d in (raw.get("tool_errors") or [])], "error": raw.get("error"),
                  "result": raw.get("result"), "prompt": prompt,
                  "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                  "source_files": ["official_context.txt"], "source_context": CONTEXT,
                  "isolation": "fresh OpenCode session; only official context in source copy"}
    except Exception as exc:
        record = {"id": ident, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                  "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / f"{ident}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record.get(k) for k in ("id", "ok", "model", "timed_out", "error")}, ensure_ascii=False), flush=True)
    return record


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--prepare-only" in sys.argv:
        for i in range(1, 11):
            prepare(i)
        print("Prepared ten isolated directories; each contains official_context.txt only.")
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(1, 11)))
        print(json.dumps({"completed": len(results), "ok": sum(r.get("ok", False) for r in results)}, ensure_ascii=False), flush=True)
