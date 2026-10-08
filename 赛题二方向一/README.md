# 语枢 Semantica · 原型工程

> 赛题二 · 方向一（AI 使用的大数据平台）冲冠方案原型。
> 核心闭环五步：**解析 → 对齐 → 澄清 → 编译 → 披露**

---

## 0. 现在能跑什么

| 能力 | 命令 | 是否需 LLM API |
|---|---|---|
| 生成合成数据集（5 表 ≈10 万行） | `python data/generate_data.py` | 否 |
| 五步闭环 v0（词典对齐 + 模板编译 + 澄清卡 + 口径披露） | `python scripts/smoke_test.py` | 否 |
| **演示界面**（澄清卡 + 双模式对照 + 信任标签 + 现场教学面板） | `streamlit run app.py` | 教学/对照需要 |
| **MCP Server**（任何 Agent 即插即用） | `python mcp_server.py` | 否 |
| **单元/集成测试套件**（161 项，含 120 题端到端回归） | `python -m pytest` | 否 |
| **本体一致性校验**（结构/引用/安全/可执行性） | `python scripts/check_ontology.py --execute` | 否 |
| **澄清质量评估**（精准率/召回率/F1） | `python scripts/eval_clarification.py` | 否 |
| **端到端自检**（120 题离线全量） | `python scripts/eval_iso.py` | 否 |
| **语义缓存基准**（冷/热对比、命中率） | `python scripts/bench_cache.py` | 否 |
| **澄清回流挖掘**（把澄清样本变成本体改进建议） | `python scripts/mine_feedback.py` | 否 |
| MCP 端到端自测 / UI 冒烟测试 / 看板自测 | `python scripts/test_mcp_client.py` · `python scripts/test_ui.py` · `python scripts/test_dashboard.py` | 否 |
| **实验图表**（4 张战绩/消融图，PNG 直接进 PPT） | `python scripts/make_charts.py` | 否 |
| **战绩看板**（Streamlit 第二页：指标卡 + 4 图 + 结论） | `streamlit run app.py` → 侧边栏「📊 战绩看板」 | 否 |
| **现场教学**（活体本体：新术语 30 秒内可查） | `python scripts/teach.py "术语" --desc "定义"` | 是 |
| **题库双人复核**（120 题工作单，离线） | `python scripts/review_benchmark.py --name 你的名字` | 否 |
| **W2 实验矩阵**（A/B/C/D 四组对比） | `python scripts/run_experiment.py --samples 2` | LLM 组需要 |
| 预实验：语枢 vs 裸 DDL 基线（AmbiQuery 种子题） | `python scripts/pre_experiment.py` | 基线部分需要 |

## 1. 快速开始

```powershell
cd semantica
python -m pip install -r requirements.txt

# 1) 生成数据（可复现，种子固定）
python data/generate_data.py

# 2) 离线闭环演示（无需任何 API Key）
python scripts/smoke_test.py
python scripts/smoke_test.py --interactive   # 交互模式：自己回答澄清卡

# 3) 预实验（无 API Key 时只跑"语枢"侧；配置 Key 后自动附带基线对比）
copy .env.example .env   # 填入 LLM_API_KEY
python scripts/pre_experiment.py

# 4) 演示界面（路演主力）
streamlit run app.py

# 5) MCP Server（支持 MCP 的 Agent 配置 mcp_server.py 即可即插即用）
python scripts/test_mcp_client.py   # 端到端自测（扮演 MCP 客户端）

# 6) 现场教学（活体本体：新术语 30 秒内可查）
python scripts/teach.py "快时效占比" --desc "承诺时效不超过24小时的运单占全部运单的比例"

# 7) W2 实验矩阵（四组对比，LLM 组采样取多数）
python scripts/run_experiment.py --samples 2

# 8) 消融实验 + 题库终验 + 实验图表
python scripts/run_ablation.py
python scripts/validate_draft.py          # 输出 eval/benchmark_validation.md（120/120）
python scripts/make_charts.py             # 输出 eval/charts/*.png（可直接进 PPT）

# 9) 质量门禁：单元测试 + 本体校验
python -m pytest                          # 161 项（含 120 题端到端回归）
python scripts/check_ontology.py --execute

# 10) 评估与可观测能力
python scripts/eval_clarification.py      # 澄清精准率/召回率/F1
python scripts/eval_iso.py                # 120 题离线端到端自检
python scripts/bench_cache.py             # 语义缓存命中率与加速比
python scripts/mine_feedback.py --demo    # 澄清回流挖掘（建议草案）
```

## 2. 目录结构

```
semantica/
├── app.py                    # 演示界面（Streamlit：澄清卡 + 双模式对照 + 披露面板 + 现场教学）
├── pages/
│   └── 1_战绩看板.py          # 看板页：指标卡 + 4 张图表 + 三条核心结论
├── mcp_server.py             # MCP Server（tools + resources + prompt，任何 Agent 即插即用）
├── data/
│   ├── generate_data.py      # 合成数据集生成器（固定种子 + 固定截止日）
│   └── warehouse.duckdb      # 生成产物（git 忽略）
├── ontology/
│   ├── ontology.yaml         # 本体：概念 / 关系 / 公理
│   ├── synonyms.yaml         # 同义词与黑话映射（含"陷阱"术语）
│   ├── metrics.yaml          # 指标口径库（多口径 + SQL 表达式）
│   └── learned.yaml          # 活体本体：现场教学产物（热加载，无需重启）
├── src/
│   ├── db.py                 # DuckDB 连接 / 参数化执行 / 展示 SQL 渲染 / DDL 导出
│   ├── llm.py                # LLM 客户端（OpenAI 兼容：百炼 / DeepSeek）
│   ├── alignment.py          # 步骤②③：对齐引擎 + 口径关键词 + 澄清触发 + 时间解析 + 热加载
│   ├── compiler.py           # 步骤④：语义编译器（参数化 SQL / 排名 / 阈值 / 对比）
│   ├── loop.py               # 五步闭环编排器（含缓存与澄清回流接入）
│   ├── baseline.py           # 裸 DDL 对照组（预实验 / 双模式演示 / 实验矩阵共用）
│   ├── ontology_pipeline.py  # 活体本体管线（LLM 草稿 + 三关校验 + 发布）
│   ├── ontology_lint.py      # 本体一致性校验器（结构/引用/安全/EXPLAIN）
│   ├── verifier.py           # 验证器：信任四件套（口径/权限/成本/空结果）+ 信任标签
│   ├── benchmark.py          # 题库单一装载入口（schema 规范化 + 答案比较器）
│   ├── cache.py              # 语义版本化 LRU 缓存（命中率统计）
│   └── feedback.py           # 澄清回流：样本落盘 + 偏好挖掘
├── tests/                    # pytest 套件（161 项，含 120 题端到端回归）
├── pyproject.toml            # pytest 配置与项目元信息
├── benchmark/
│   ├── ambiquery_v1.jsonl    # **AmbiQuery-120 定稿**（120/120 机器终验通过）
│   ├── ambiquery_seed_v0.jsonl  # 种子题 24 道（预实验 / 演示用）
│   └── 标注工作手册.md        # 可选：双人复核工作单与判定口径
├── eval/                     # 实验档案（可复现证据）
│   ├── matrix_*.csv / matrix_summary_*.md   # A/B/C/D 四组 × 多次采样
│   ├── ablation_*.md                        # 消融实验报告
│   ├── benchmark_validation.md              # 题库机器终验报告
│   ├── iso_selfcheck.md / iso_selfcheck_*.csv  # 120 题端到端自检（逐题 verdict）
│   ├── clarification_report.md              # 澄清精准率/召回率报告
│   ├── cache_bench.md                       # 语义缓存基准
│   ├── feedback_mining.md                   # 澄清回流挖掘报告
│   ├── ontology_lint.md                     # 本体校验报告（--out 时生成）
│   └── charts/*.png                         # 实验图表（fig1–fig4）
├── scripts/
│   ├── smoke_test.py         # 离线演示脚本
│   ├── pre_experiment.py     # 预实验：语枢 vs 裸 DDL 基线
│   ├── run_experiment.py     # W2 实验矩阵（A/B/C/D 四组，采样取多数）
│   ├── run_ablation.py       # 消融实验（逐构件拆除）
│   ├── validate_draft.py     # 题库机器终验（可执行 / 自洽 / 澄清点一致）
│   ├── normalize_benchmark.py # 题库 schema 规范化（带指纹校验）
│   ├── check_ontology.py     # 本体一致性校验（CI 门禁，error 非零退出）
│   ├── eval_clarification.py # 澄清质量评估（P/R/F1）
│   ├── eval_iso.py           # 语枢侧 120 题离线端到端自检
│   ├── bench_cache.py        # 语义缓存基准（冷/热、命中率、加速比）
│   ├── mine_feedback.py      # 澄清回流挖掘（建议草案）
│   ├── make_charts.py        # 实验图表生成（读 eval/ 档案 → eval/charts/*.png）
│   ├── teach.py              # 现场教学（活体本体生长，30 秒内可查）
│   ├── check_llm.py          # LLM 连通性自检（自动识别服务商）
│   ├── test_mcp_client.py    # MCP 端到端自测（标准 stdio 协议）
│   ├── test_ui.py            # UI 冒烟测试（AppTest 模拟完整交互）
│   └── test_dashboard.py     # 看板页冒烟测试
├── requirements.txt
└── .env.example
```

## 3. 数据集关键约定（评测纪律）

- **固定截止日 `DATASET_END = 2026-09-20`**：所有相对时间表达（"上月""近7天"）均以此为基准，
  保证评测可复现。换日期：`python data/generate_data.py --end-date <YYYY-MM-DD>`（评测集需同步更新）。
- **歧义设计清单**（专为 AmbiQuery 评测而设计）：
  - 金额三口径：`order_amount` 毛额 / `pay_amount` 实付 / 剔除取消的净额；
  - 超时两口径：按全部运单 / 按已签收运单；
  - 实体歧义："苹果"= 商品品牌 vs 客户名（苹果果业有限公司…）；
  - 相对时间："最近"（无范围）必须澄清；
  - 多跳关系：订单 → 运单 → 承运商 / 商品 → 品类。
- **故意不覆盖（陷阱题）**：退货率、毛利、成本、库存、"安卓"——
  平台应"诚实地说不知道"，绝不瞎编。

## 4. 与《冲冠方案》的对应（W1 进度）

- [x] D1：合成数据集 v1（5 表 ≈10 万行）+ 项目骨架
- [x] D1：闭环 v0 可离线运行（词典对齐版，先保闭环）
- [x] D3 红线检查点提前达标：smoke 演示 + AmbiQuery 种子 **23/23 PASS**
- [x] 验证器信任标签（口径披露 / 数据新鲜度 / 空结果自检 / 置信度）
- [x] MCP Server v1（工具×3 + 资源×2 + Prompt×1，端到端自测通过）
- [x] 演示界面 v1（澄清卡 + 双模式对照开关 + 信任标签）
- [x] D2：预实验完成 → 基线 6–7/23（跨三轮 5–7/23）vs 语枢 23/23，已回填方案文档
- [x] **活体本体管线**：现场教学实测通过（快时效占比 30 秒内可查 + 三关校验）
- [x] **UI 现场教学面板**：三个预设术语全部预验证（已取消订单占比 6.4% / 高评分承运商占比 74.5% / 华东区订单占比 29.9%，均与数据设计吻合）
- [x] **W2 实验矩阵首跑**：A 21.7% / B 8.7% / C 13.0% / **D 100%**（B/C 证明注释与本体入提示词均无效）
- [x] **AmbiQuery-120 定稿**：**120/120 机器终验通过**（gold SQL 可执行 + 系统自洽 + 澄清点一致）；双人复核工具 + 手册就绪（人工复核列为可选项）
- [x] **3 次采样实验矩阵**（10-08）：A 21.7% / B 17.4% / **C 4.3%（本体入提示词最差）** / **D 100%**
- [x] **消融实验**（10-08）：去同义词 63.2%（-43 题）/ 去公理·关系 73.5%（-31 题）/ 去澄清器 100%（但暴露 36.8% 风险面）
- [x] **路演可视化**（10-08）：4 张图表生成（`eval/charts/`）+ Streamlit 战绩看板页（侧边栏可切换）
- [x] **工程打磨（10-08）**：SQL 全链路参数化；本体一致性校验器（0 错 0 警）；题库 schema 规范化；
      语义缓存（**26.4× 加速 / 62.5% 命中**）；澄清回流日志 + 挖掘；**161 项 pytest 套件**
- [x] **口径口语识别（10-08）**：“按已签收口径”“净实付”等由本体 `keywords` 声明式识别，不再重复追问
- [x] **全量评测升级（10-08）**：语枢在 **AmbiQuery-120 全量**上 **120/120 = 100%**；
      澄清 **Precision 100% / Recall 100% / F1 100%**（120 题整题一致）
- [ ] 可选：双人独立复核、录制备份视频、彩排

## 5. 工程质量与可验证性

「能跑」和「可依赖」是两件事。本工程把语义质量变成可自动执行的检查：

| 维度 | 做法 | 证据/命令 |
|---|---|---|
| **SQL 安全** | 编译产物只含 `?` 占位符，值全部走 DuckDB 参数绑定；展示用 SQL 另走转义渲染；
 表达式禁用片段（`;` / 注释 / DDL/DML 关键词）拦截；基表白名单 | `tests/test_compiler.py::TestParameterization` · `TestGuards` |
| **本体质量** | 结构 / 引用 / 安全 / 可执行性四类检查（含 `EXPLAIN` 预检），error 退出码非 0，可直接做 CI 门禁 | `python scripts/check_ontology.py --execute` |
| **题库质量** | 单一装载入口（`src/benchmark.py`）+ schema 规范化 + 指纹校验；120 题 gold SQL 可执行性回归 | `python -m pytest tests/test_benchmark.py` |
| **回归保护** | 161 项测试，含 **120 题端到端**（分级 + 逐类）回归，任何引擎改动导致答错立刻变红 | `python -m pytest` |
| **可观测性** | 语义缓存命中率；澄清精准率/召回率；信任标签（数据截止/行数/空结果/置信度）随每个答案披露 | `eval/cache_bench.md` · `eval/clarification_report.md` |
| **闭环进化** | 每次澄清交互落盘为标注样本 → 按支持度给出「默认口径/关键词/实体引导」建议草案（人工确认后入库） | `python scripts/mine_feedback.py --demo` |

配套产出：`eval/iso_selfcheck.md`（120 题逐题 verdict + CSV 明细）、`eval/clarification_report.md`、
`eval/cache_bench.md`、`eval/feedback_mining.md`。

## 6. 评分映射（证据索引）

赛题二评委评分维度（100 分）→ 本项目可直接拿出手的证据：

| 维度 | 分值 | 证据（拿着就能说） |
|---|---|---|
| 问题价值与需求理解 | 20 | 失败分类学（六类歧义）× AmbiQuery-120；预实验实测“LLM 直连 17–22% vs 语枢 100%” |
| 成果完整性与可用性 | 30 | `streamlit run app.py` 可现场演示 + `python mcp_server.py` 任何 Agent 即插即用 + `eval/` 全部可复现 + 看板页 |
| AI 与技术实现 | 20 | 五步闭环（解析→对齐→澄清→编译→披露）；消融实验证明每个构件的边际贡献；题库 120/120 机器终验 |
| 创新性 | 15 | 活体本体（现场教学 30 秒可查）+ 清晰度回流 + “本体不塞提示词、交给编译器”的反直觉实验结论 |
| 落地潜力 | 10 | 低侵入外挂路径（不动数仓，只加语义层）+ 成熟度模型 P1→P3 |
| 展示表达 | 5 | 「本体塞进提示词 = 最差路线」反直觉钩子 + 4 张图表 + 电影结构剧本 + Q&A 预案 |

总分构成（赛事规则）：`总成绩 = AI 评分 20 + 评委评分 80 + 跨学院组队加分 5 = 105`。

> 详细对照见《赛题二方向一-冲冠方案.md》§7「屠榜检查表」。

## 7. Roadmap（v0 → v1）

| 模块 | v0 | 现状 |
|---|---|---|
| 对齐引擎 | 词典精确匹配 | ✅ 词典 + 本体声明的口径关键词；消融档位可拆卸 |
| 澄清引擎 | 规则触发（口径/时间/实体） | ✅ 触发 + **精准率/召回率统计**（100%/100%） |
| 语义编译器 | SQL 模板拼接 | ✅ 参数化绑定 + 表达式安全守卫 + 展示 SQL 双轨 |
| 活体本体 | 静态 YAML | ✅ LLM 草稿 + 三关校验（与本体校验器同规则）+ 热加载 |
| 语义缓存 | 无 | ✅ 语义版本化 LRU（本体/数据变更自动失效） |
| 澄清回流 | 无 | ✅ 标注样本落盘 + 偏好挖掘 + 建议草案 |
| 接口 | 脚本 | ✅ MCP Server + Streamlit 双页 UI（含看板） |
| 测评 | 种子 24 题 | ✅ AmbiQuery-120（100%）+ 消融 + 四组对比 + 图表 |
| 待补 | — | ⏳ embedding 检索 / LLM 仲裁通道；IR 抽象与多后端（API/解释型） |
