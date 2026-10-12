# 语枢 Semantica

**让 Agent 在证据冲突之后，保留用户约束并继续完成任务。**

赛题二方向 A：现有数仓之上的 **Agent 语义执行网关**。让 AI 使用带口径、版本、证据和使用条件的数据。

优化分支：`赛题2-Astra评审优化-庄子由`，原作品冻结于 `64166dd`。本次主线为**任务恢复工作台**；完整评审见 [实验设计](评审实验/00-实验设计.md)、[Astra对照](评审实验/01-Astra对照与采用决策.md)、[DeepSeek构思汇总](评审实验/02-DeepSeek冷启动汇总.md)。

## 新主演示：任务恢复工作台

在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe 赛题二方向一/scripts/run_workbench.py
```

打开 <http://127.0.0.1:8766>。界面同时呈现目标条件、真实工具调用和服务端结论。先修复 B 的默认分母冲突，再改目标权重、制造缺证或更新数据。备用视图是同一个合成仓库的另一视图，不代表独立真实性证明。

- **离线协议**：确定性策略，完全不调用语言模型。
- **真实 DeepSeek**：调用本机安装的 `deepseek-worker`，实际模型 `deepseek/deepseek-flash`；外部 API 独立计费。桥接不可用时如实失败，没有规则回退冒充模型。
- **已保存真实证据**：[当前五次实际规划、三种故障](评审实验/真实Agent轨迹/实际闭环与故障变体.json)。模型在口径冲突时选择重取 B；缺华南时只补备用视图华南；备用不可用时请求用户处理。v1原记录也保留；修复前后累计十次调用。模型自由文本理由仍可能出错，执行和结论以服务端证据为准。

结构控件定义任务口径、时间窗与范围；文字目标供人核对，尚未实现通用自然语言任务解析。固定合成场景证明的是局部恢复机制；历史率差不能证明换承运商的因果收益。详见 [新方案与五分钟路演](参赛材料/05-任务恢复工作台.md)。

## 原有底座与历史演示

1. **比较前先检查**：总体超时率 A=2.8%、B=8.2%；两个区域内却都是 A 更差。声明公共区域权重后，等权 A=6%、B=5%。正确数字不自动支持正确决策。
2. **契约与证据**：自然语言 → 明确口径 → 预览契约 → 确认执行 → 下载完整结果与版本 → 同环境重放。数据或语义改变，旧契约失效。
3. **决策实验室**：区分超时量与超时率，展示样本量与 Wilson 区间；在给定成本、预算、覆盖和效力假设下比较情景。模拟结果附带假设和公式。

上述主线全部无需模型 API，使用明确标注的合成数据。可选 LLM 负责提出查询草案，确定性引擎负责检查和执行。未配置 API 时如实显示不可用，不伪装成大模型运行。

原独立数学演示及条件实验室保留供解释；本次舞台主屏使用新工作台，避免在多个页面之间讲一条没有执行连接的流程。

## 启动

在 `赛题二方向一` 目录，Python 3.11+（当前安装验证环境为 3.12）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe data/generate_data.py
.\.venv\Scripts\python.exe -m streamlit run app.py
```

本机已经配置的环境位于仓库根目录 `../.venv`，直接运行：

```powershell
..\.venv\Scripts\python.exe -m streamlit run app.py
```

数据为 50,000 订单、43,190 运单、500 商品、5,000 客户、8 承运商；固定种子 42，截止日 `2026-09-20`。相对时间以数据截止日为基准。

## 已实现的核心

| 模块 | 能力 | 实现 |
|---|---|---|
| 业务意义 | 指标、多口径、实体和时间澄清 | `src/alignment.py`、`ontology/` |
| 执行契约 | 指标/粒度/时间/来源/版本/策略、先预览再执行 | `src/contracts.py` |
| 安全编译 | 受支持 IR、参数绑定、表达式与关联依赖校验 | `src/compiler.py` |
| 质量阻断 | 主键、外键、孤儿、单订单单运单粒度 | `src/semantic_guard.py` |
| 证据 | 完整结果、模板与参数、版本、同环境重放 | `src/contracts.py`、`src/loop.py` |
| 可比性 | 共同区域支持、明确公共权重、构成反转 | `src/comparability.py` |
| 条件决策 | 超时量/率、样本区间、共享预算与敏感性 | `src/decision_lab.py` |
| 可选 AI | 读取指标目录、提出草案、可见人工核对 | `src/agent_workflow.py` |
| Agent 接口 | MCP 类型化结构输出，默认不代选口径 | `mcp_server.py` |
| 任务恢复 | 字段冲突/缺证→模型下一工具→SQL证据→重新计算→结论 | `src/task_runtime.py`、`src/task_planner.py` |

## MCP 接入

```json
{
  "mcpServers": {
    "semantica": {
      "command": "<你的虚拟环境/python绝对路径>",
      "args": ["<本项目/mcp_server.py绝对路径>"]
    }
  }
}
```

调用序列：`preview_query` → 必要时用户确认 `choices` → `execute_contract` → `replay_evidence`。

新闭环：`start_recovery_task` → `inspect_recovery_task` → `execute_recovery_action`。宿主 Agent 可自己选择候选动作；授权改变任务范围没有开放给 Agent。MCP 模式使用独立合成会话，与浏览器会话不同。

另外有 `align_terms`、`nl_query`、`run_metric`、`diagnose_logistics`；`ontology://metrics` 与 `data://cards` 提供目录和数据卡。

`nl_query` 默认 `auto_resolve=False`。`run_metric` 不再把缺失日期偷换为最近30天。所有歧义选择必须完整、合法；实验代选明确记录为 `assumed_first_option`。

## 证据范围

- [独立业务反例](eval/adversarial_v2.md)：首次 19/24，发现五类遗漏条件；修复后 24/24。首次失败完整保留。它参与了开发反馈，属于对抗验收，不是严格盲测。
- [AmbiQuery 回归](eval/iso_selfcheck.md)：120 道自建题，完整比较行、列和单元格。实验中首项澄清不是用户确认。
- 本次修订真实耗时公式，10 道 v1 gold 与 2 道 seed gold 因此更新；见 [技术说明](参赛材料/02-技术与证据.md)。
- 历史四组 LLM 实验只有23道可自动判定种子题，不能与120题回归当作同规模比较；也不能断言“本体放入提示词普遍更差”。

按需检查，不需要反复全量运行：

```powershell
python scripts/eval_iso.py
python scripts/eval_adversarial.py
python -m pytest
python scripts/test_mcp_client.py
```

## 范围与边界

这是轻量原型，非通用问数或因果推断系统。自然语言为有限规则解析；金额阈值、Top-N、多时间窗口、趋势等会保守拒答。用户应核对契约是否忠实表达原问题。

区域权限是服务端聚合范围约束，演示角色尚未接企业身份认证。数据关系检查限定每订单最多一个运单，多运单业务需升级粒度策略。版本检测当前会扫描本地表，不能据此声称大数据规模性能。

证据哈希检测一致性，不是数字签名或原始数据真实性证明；证据包不自带原始数据快照。重放要求相同数据、语义定义和运行环境。可比性演示是独立数学反例；情景模拟不等于真实预测、因果效果或自动调度。

## 提交材料

- [01 · 参赛方案](参赛材料/01-参赛方案.md)
- [02 · 技术、正确性与证据](参赛材料/02-技术与证据.md)
- [03 · 5分钟剧本、答辩与提交文案](参赛材料/03-路演与答辩.md)
- [04 · 国际参考与演进路线](参赛材料/04-国际参考与演进.md)
