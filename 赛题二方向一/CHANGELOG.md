# 语枢 Semantica · 变更日志（2026-10-08）

> 本文件记录本次工程打磨的**全部改动、原因与验证证据**。
> 项目根：`d:\黑客松\semantica`　｜　记录时间：2026-10-08 13:00–14:30
> 说明：本仓库未启用 git，因此以「文件级清单 + 改动说明 + 实测证据」的形式留档；
> 每一条改动都能用文中给出的命令复现验证。

---

## 0. 一页速览

| 维度 | 改动前 | 改动后 |
|---|---|---|
| 端到端成绩 | 种子题 23/23 | **AmbiQuery 全量 120 题 120/120 = 100%** |
| 澄清质量 | 未量化 | **Precision 100% / Recall 100% / F1 100%**（120 题整题一致，漏报 0 误报 0） |
| 本体质量 | 靠人眼看 YAML | **自动校验 0 错 0 警**（校验器：结构/引用/安全/EXPLAIN 可执行性） |
| SQL 安全 | 字面量拼接 | **全链路参数绑定**（可执行 SQL 无任何内联值） |
| 测试 | 仅冒烟脚本 | **161 项 pytest（2.9 秒）**，含 120 题端到端回归 |
| 性能 | 每题重算 | **语义缓存 26.4× 加速 / 62.5% 命中** |
| 闭环进化 | 无 | **澄清回流**：每次澄清落盘为标注样本 → 偏好挖掘 → 改进建议 |
| 题库 schema | 20 题字段名不一致 | 统一 schema + **指纹校验**（内容零变化） |

---

## 1. 阶段 A：可视化与依赖修复（13:00–13:20）

### A1. 新增实验图表生成器 `scripts/make_charts.py`（172 行）
- 自动读取 `eval/` 下**最新的**矩阵 CSV 与消融报告（正则解析），生成 4 张图到 `eval/charts/`：
  `fig1_headline`（主战绩）、`fig2_category`（分类战绩）、`fig3_ablation`（消融边际贡献）、`fig4_ablation_cat`（消融分类）
- 统一配色：D=#1b8a5a（绿）/ A=#8d99ae（灰）/ B=#e0a458（琥珀）/ C=#c1443c（红）
- 中文渲染：`Microsoft YaHei` + `axes.unicode_minus=False`；矮柱数字标签自动移到柱外（原白字溢出）
- 验证：`python scripts/make_charts.py` → 4 张 PNG（84/61/77/58 KB），`view_image` 人工确认渲染正确

### A2. 新增战绩看板页 `pages/1_战绩看板.py`（52 行）
- Streamlit 多页应用第二页：4 个指标卡（100% / 21.7% / 17.4% / 4.3%）+ 4 张图表 + 三条核心结论 + 复现命令
- 文件名**不带 emoji**（emoji 放 `st.set_page_config(page_icon=)`）：实测带 emoji 的文件名会导致深链路由 404
- 新增自测 `scripts/test_dashboard.py`（23 行，AppTest 渲染校验）

### A3. 修复依赖冲突（阻塞级）
- 现象：`import streamlit` 抛
  `ImportError: cannot import name 'DEFAULT_EXCLUDED_CONTENT_TYPES' from starlette.middleware.gzip`
- 根因：环境里 `fastapi<0.42` 把 `starlette` 钉在 0.41.3，而 `streamlit 1.57` 需要 ≥0.45
- 修复：`pip install -U "starlette>=0.45"`（升至 1.7.0）；`requirements.txt` 写入 `starlette>=0.45` + 排坑注释
- 验证：`streamlit run app.py` 真实启动 + 浏览器全流程实测（见 A4）

### A4. 浏览器端到端实测（真实运行，非 mock）
- 主页加载：数据截止 2026-09-20 / 本体概念 5 / 指标 10 / 订单行数 50,000
- 交互链路：预设「8月华东区的GMV是多少？」→ 弹**口径澄清卡**（毛额/实付/净实付）→ 点「确认并执行」
  → `✅ 10,573,381.49` + 信任标签 + 「口径披露」「编译 SQL」折叠面板
- 看板页：`http://localhost:8502/战绩看板` 返回 200，4 指标卡 + 4 图 + 结论完整渲染

---

## 2. 阶段 B：核心引擎加固（13:40–14:10）

### B1. SQL 全链路参数化（安全加固，涉及 5 个文件）

**改了什么**

| 文件 | 改动 |
|---|---|
| `src/db.py` | 新增 `run_sql(conn, sql, params)`（参数绑定执行）、`sql_literal(v)`（转义字面量）、`render_sql(sql, params)`（占位符回填为字面量，**仅用于展示/归档**） |
| `src/compiler.py` | `CompileResult` 增加 `params` 字段与 `sql_display` 属性；`_where()` 改为返回 `[(谓词, [绑定值])]`；新增 `_assemble()`；四种形态（standard/ranking/threshold/compare）全部改为 `?` 占位 |
| `src/loop.py` | 执行改为 `run_sql(conn, res.sql, res.params)`；对外 `Answer.sql` 给人类可读的 `sql_display` |
| `mcp_server.py` | `run_metric` 统一改用 `_loop.answer(a)`（不再自行编译执行） |
| `src/ontology_pipeline.py` | 教学试跑改参数绑定；并显式指定首口径（多口径指标不再因缺口径而拒绝试跑） |

**关键代码（before → after）**

```python
# before：值直接被拼进 SQL
parts.append(f"c.region = '{filters['region']}'")
sql = f"... WHERE {' AND '.join(wheres)}"

# after：谓词用占位符，值走绑定
items.append((f"{col} = ?", [filters[key]]))
sql, params = self._assemble(items)
df = run_sql(conn, res.sql, res.params)
```

`render_sql` 逐字符扫描并跳过引号包裹片段，因此字符串里的 `?` 不会被误替换：

```python
render_sql("SELECT '??' AS q, ? AS v", [1])  ==  "SELECT '??' AS q, 1 AS v"
render_sql("SELECT ?", [])                   →  ValueError（占位符多于参数）
```

**表达式安全守卫**（防本体被污染）：`FORBIDDEN_EXPR` 提升为模块级常量（`src/compiler.py`），拦截
`;` / `--` / `/* */` / `drop|delete|update|insert|create|attach|copy|pragma|call`；基表白名单限定为 `orders|shipments`。

**验证**：`tests/test_compiler.py::TestParameterization`、`TestGuards`；端到端全量回归 120/120 仍满分。

### B2. 闭环行为修正

| 问题 | 修复 | 验证 |
|---|---|---|
| 排名/对比类答案**只显示第一行**（对比 2 个品牌只看到 1 个） | 新增 `_fmt_rows(df)`：单列直接列值、多列 `列名=值`、超 6 行标注总数；`Answer.rows` 提供结构化输出（≤20 行） | `tests/test_loop.py::TestAnswerShapes`；实测输出 `华为=207 / 苹果=406` |
| 陷阱题（数据不足）**还挂着时间澄清点**（澄清误报根因） | 对齐引擎收尾：`if a.unsupported: a.clarify = []`（答不了就不该再追问） | 澄清评估从 98.1% → **100%** |
| 缺时间范围时行为不明确 | `_proceed` 增加兜底：`insufficient` + 明确提示补时间，不默认全量 | `tests/test_loop.py::test_missing_time_is_declined_not_guessed` |
| 用户说「按已签收口径」仍被追问口径 | 新增**本体声明式口径关键词**：metrics.yaml 的 variant 可写 `keywords`，对齐时最长匹配优先 | `tests/test_alignment.py::TestVariantKeywords`（5 例） |
| 品牌顺序按数据库顺序（与提问顺序不一致） | `brands_hit` 按问题中出现位置排序 | `test_brand_order_follows_question` |

新增的关键方法（`src/alignment.py`）：

```python
@staticmethod
def _detect_variant(q: str, mdef: dict) -> str | None:
    """按本体声明的 keywords 识别显式口径；最长关键词优先，
    避免「取消」盖掉「剔除已取消」。"""
```

`ontology/metrics.yaml` 为多口径指标补充关键词，例如：

```yaml
- id: delivered_only
  keywords: [按已签收, 已签收口径, 妥投口径, 只算已签收, 已妥投口径]
- id: net
  keywords: [净实付, 净额, 剔除已取消, 不含取消, 去掉取消, 只算有效订单]
```

### B3. 阈值类编译补全筛选（真实缺陷）
- 原 `_compile_threshold` 只处理时间与小时数，**静默忽略**区域/承运商/品牌筛选
- 现改为复用 `_from_clause` + `_where`，并按需 JOIN，披露中也列出筛选条件
- 验证：`tests/test_compiler.py::test_threshold_supports_filters`

### B4. 整理半成品代码
- `QueryLoop.answer(a)` 原为**带死代码的空壳**且无人调用（`if a.time is not None: pass` 等）
- 现改为规范的「预对齐入口」：返回 `Answer | Clarification`，供确定性流水线复用同一闭环
  （口径披露 / 信任标签 / 参数绑定与自然语言路径完全同源）
- `mcp_server.run_metric` 随之删除重复的编译执行逻辑，并对**多口径未指定**返回澄清选项而非猜测

---

## 3. 阶段 C：新增 4 个模块（14:10–14:20）

| 新文件 | 行数 | 职责 | 关键设计 |
|---|---|---|---|
| `src/benchmark.py` | 108 | 题库**单一装载入口** | `Item` 数据类；兼容历史字段（`expect` → `expected_outcome`）；`values_match()` 数值相对误差/字符串去空白/**类型不同不相等**；`predicted_clarifications()` 把澄清点映射到题库标注口径 |
| `src/ontology_lint.py` | 275 | **本体一致性校验器** | 结构（zh/expr/variants/default_variant）、一致性（多口径带默认须写 `default_rationale`、`requires` 须覆盖表达式用到的表）、安全（禁用片段、未知别名）、引用（关系指向概念、同义词 target 存在、陷阱术语须登记 `not_covered`）、关键词唯一性；`lint_executable()` 用 `EXPLAIN` 做可执行性预检（不扫数据） |
| `src/cache.py` | 68 | **语义版本化 LRU 缓存** | 键＝(规范化问题, 档位, auto_resolve, **语义版本**)；版本＝本体各文件 mtime + 数据仓库指纹（sha1 短哈希）；**只缓存确定答案**（澄清/数据不足不入缓存，避免把一次性选择固化成默认）；命中返回副本 |
| `src/feedback.py` | 130 | **澄清回流** | 每次澄清选择落盘为标注样本（JSONL 追加写）；`_jsonable()` 递归处理 dataclass/Timestamp；`summarize()` 聚合口径偏好/时间偏好/实体热点并按支持度给建议 |

### C1. 本体校验器当场抓出的 10 个真实不一致（已全部修复）

```
❌ learned.yaml::FastDeliveryRate      requires 缺少表达式用到的表：['shipments']
❌ learned.yaml::CancelledOrderRate    requires 缺少表达式用到的表：['orders']
❌ learned.yaml::HighRatingCarrier…    requires 缺少表达式用到的表：['carriers','shipments']
❌ learned.yaml::EastChinaOrderRatio   requires 缺少表达式用到的表：['customers','orders']
⚠️ ontology.yaml::Product.brand        枚举属性未登记 values
⚠️ metrics.yaml::OrderCount            多口径却设默认口径，会绕过澄清
⚠️ synonyms.yaml::单量/订单数          与指标正式别名重复（双头维护）
⚠️ synonyms.yaml::退款/成本            陷阱术语未登记在 not_covered
```

**修复动作**
1. `ontology/learned.yaml`：4 个教学指标补 `requires` 与 `default_rationale`
2. `ontology/ontology.yaml`：`Product.brand` 改为 `string`（取值以数据为准，本体不重复枚举）；`not_covered` 补「退款」「成本」
3. `ontology/synonyms.yaml`：删除与 metrics.yaml 重复的词条（`订单笔数` 并入 metrics.yaml，保持单一事实来源）
4. `ontology/metrics.yaml`：`OrderCount` 补 `default_rationale` 显式说明默认口径理由
5. 校验器规则升级：`default_rationale` 存在即免警告（**强制写理由**而不是沉默）

**结果：`本体校验：0 个错误，0 个警告`，退出码 0（可直接做 CI 门禁）**

### C2. 教学管线与校验器共用同一套规则
- `ontology_pipeline.draft_metric` 的提示词新增 `requires` / `default_rationale` 要求，
  并在 LLM 漏填时**按表达式别名自动推断补全**
- `validate_metric` 追加 `check_metric_def()`（复用校验器规则），杜绝"教学入库的定义"与"手工本体"两套标准漂移
- 实测：`python scripts/teach.py "移动端订单占比" --desc "下单渠道为 App 的订单占全部订单的比例" --dry-run`
  → 三关校验通过，生成的定义与本体规范一致

### C3. 澄清回流接进闭环
- `QueryLoop.resolve()` 每个澄清点写一条样本（`source="loop"`）；自动取默认值时写 `source="auto"`
- **库代码不默认写文件**：`feedback_path()` 未显式指定且无环境变量时返回 `None`（回流是可选能力，不是副作用）
  开启方式：传 `feedback_path=...` 或设 `SEMANTICA_FEEDBACK_LOG`
- 演示界面 `app.py` 显式开启（`ontology/feedback_log.jsonl`），真实使用中自动积累样本

---

## 4. 阶段 D：题库规范化与测试套件（14:10–14:25）

### D1. 题库 schema 规范化 `scripts/normalize_benchmark.py`（52 行）
- 问题：F 类 20 道陷阱题用 `expect: insufficient` 且缺 `expected_clarification`，其余 100 题字段不同 → 下游被迫写兼容分支
- 处理：统一为
  `id / category / question / expected_clarification / expected_outcome / gold_sql / compare / notes`
  （`expected_outcome ∈ {answer, insufficient}`）
- **指纹校验**：规范化前后逐题比对（题目/答案/标注），不一致即中止写入
- 实测：`✅ 已规范化 120 题并写回（指纹校验通过：题目/答案/标注零变化）`
- 规范化后复跑：端到端 120/120、澄清 100%、题库终验 120/120 全部保持

### D2. pytest 套件（新增 11 个文件：9 个测试文件 + 夹具 + 配置）

| 文件 | 行数 | 覆盖 |
|---|---|---|
| `pyproject.toml` | 19 | pytest 配置（testpaths / strict-markers / slow 标记） |
| `tests/conftest.py` | 37 | 夹具：只读连接、闭环、本体临时副本；**autouse 隔离回流环境变量**（测试不写仓库） |
| `tests/test_db_sql.py` | 52 | 字面量转义（含 `'` 双写）、`render_sql` 跳过引号内 `?`、参数个数不匹配报错、`values_match` |
| `tests/test_alignment.py` | 177 | 6 类时间解析、7 个指标命中、最长匹配、阈值、排名、实体歧义/显式客户优先、5 类陷阱题、消融档位、**活体本体热加载**、口径关键词 |
| `tests/test_compiler.py` | 122 | 参数化（SQL 无内联字面量）、展示 SQL 转义、注入不可逃逸、按需 JOIN（6 例）、四种形态、披露文案、5 类安全守卫、真实执行比对 gold |
| `tests/test_loop.py` | 135 | `_fmt`/`_fmt_rows`、澄清三形态与 resolve、`no_clarify` 档位、多行结果、陷阱题、预对齐入口、信任标签、空窗口不伪造、消融档位 |
| `tests/test_verifier.py` | 38 | 信任标签字段、空结果/NaN 判定、无指标时不瞎填置信度 |
| `tests/test_ontology_lint.py` | 131 | 真实本体零错零警 + **16 类人为注入缺陷必须被抓到**（缺 requires、禁用片段、未知别名、悬空默认口径、非法基表、时间基准不一致、悬空同义词、别名冲突、ID 冲突、关系指向未定义概念、关键词冲突…） |
| `tests/test_benchmark.py` | 68 | 120 题/六类均衡、ID 唯一、schema 规范、标注格式、陷阱题无 gold SQL、**gold SQL 全部可执行且为标量** |
| `tests/test_iso_benchmark.py` | 37 | **120 题端到端回归**（整体 + 分类别参数化） |
| `tests/test_cache_feedback.py` | 164 | LRU 淘汰与命中率、缓存命中不污染、澄清/数据不足不入缓存、档位隔离、**本体变更使缓存失效**、回流日志写入/来源标记/坏行跳过/默认关闭/JSON 可序列化、偏好挖掘建议与最小支持度 |

**结果：`161 passed in 2.86s`**

### D3. `src/alignment.py` 可测试性改造
- `Aligner(conn, profile=..., ontology_dir=...)`：本体目录可注入 → 隔离测试活体本体、支持多租户
- 新增只读属性 `language_mtimes`（供缓存版本号计算），不再从外部访问私有字段

---

## 5. 阶段 E：四项新的量化能力（新增脚本，全部离线）

| 脚本 | 行数 | 产出 | 实测结果 |
|---|---|---|---|
| `scripts/eval_iso.py` | 104 | `eval/iso_selfcheck.md` + 逐题 CSV | **语枢 120/120 = 100%**（同义词 20/20、口径歧义 20/20、实体歧义 20/20、时间 20/20、多跳 20/20、陷阱 20/20） |
| `scripts/eval_clarification.py` | 121 | `eval/clarification_report.md` | **P 100% / R 100% / F1 100%**，整题一致 120/120，漏报 0、误报 0（明细：`GMV.variants` 27、`entity.苹果` 9、`DelayRate.variants` 8、`time.range` 7） |
| `scripts/bench_cache.py` | 85 | `eval/cache_bench.md` | 无缓存 1460 ms → 有缓存 55 ms，**加速 26.41×**，命中率 **62.5%**（300/480） |
| `scripts/mine_feedback.py` | 119 | `eval/feedback_mining.md` | 样例 17 条样本 → 3 条建议（默认口径 8/10、时间选项 4、实体引导 3） |
| `scripts/check_ontology.py` | 36 | 控制台/可选 `--out` | 0 错 0 警，**退出码 0** |

---

## 6. 全量验证证据（最后一次完整运行）

```powershell
cd d:\黑客松\semantica
$env:PYTHONUTF8='1'; [Console]::OutputEncoding=[Text.Encoding]::UTF8
```

| # | 命令 | 结果 |
|---|---|---|
| 1 | `python -m pytest` | **161 passed in 2.86s** |
| 2 | `python scripts/check_ontology.py --execute` | 0 错 0 警，退出码 0 |
| 3 | `python scripts/eval_iso.py` | 120/120 = 100.0% |
| 4 | `python scripts/eval_clarification.py` | Precision 100% / Recall 100% / F1 100% |
| 5 | `python scripts/validate_draft.py` | 通过 120/120 |
| 6 | `python scripts/test_ui.py` | UI 冒烟测试全部通过 |
| 7 | `python scripts/test_dashboard.py` | 看板渲染 OK（4 指标卡 + 4 张图） |
| 8 | `python scripts/test_mcp_client.py` | MCP 端到端通过（3 工具 / 2 资源 / 1 提示词） |
| 9 | `python scripts/smoke_test.py` | 8 个场景通过（含多行对比、陷阱题） |

---

## 7. 变更文件清单（按类型）

**新增（24 个；另有本日志文件）**
```
src/benchmark.py            src/ontology_lint.py       src/cache.py            src/feedback.py
scripts/check_ontology.py   scripts/eval_clarification.py  scripts/eval_iso.py
scripts/bench_cache.py      scripts/mine_feedback.py   scripts/normalize_benchmark.py
scripts/make_charts.py      scripts/test_dashboard.py
pages/1_战绩看板.py
pyproject.toml
tests/conftest.py           tests/test_db_sql.py       tests/test_alignment.py
tests/test_compiler.py      tests/test_loop.py         tests/test_verifier.py
tests/test_ontology_lint.py tests/test_benchmark.py    tests/test_iso_benchmark.py
tests/test_cache_feedback.py
```

**修改（17 个）**
```
src/db.py           参数绑定执行 + 字面量转义 + 展示 SQL 渲染
src/compiler.py     CompileResult.params/sql_display、_where 占位符化、阈值补筛选、
                    守卫提升为模块级 FORBIDDEN_EXPR、编译前置条件校验
src/alignment.py    ontology_dir 注入、口径关键词识别、品牌顺序、unsupported 清空澄清点、
                    language_mtimes 属性
src/loop.py         缓存接入、回流接入、多行格式化、缺失时间兜底、answer() 规范化
src/ontology_pipeline.py  试跑参数化 + 首口径；提示词与校验规则对齐
mcp_server.py       run_metric 复用 answer()、多口径返回澄清、输出 schema 与 nl_query 统一
app.py              显式开启回流 + 语义缓存
README.md           能力表/快速开始/目录树/进度/新增「工程质量与可验证性」章节/Roadmap 现状
requirements.txt    补 streamlit / mcp / matplotlib / pytest / starlette 提示与排坑注释
.gitignore          补运行时产物（pytest 缓存、回流日志、自检 CSV）
ontology/metrics.yaml     口径 keywords、OrderCount default_rationale、订单笔数别名回收
ontology/ontology.yaml    Product.brand 改数据驱动、not_covered 补 退款/成本
ontology/synonyms.yaml    删除与 metrics.yaml 重复的词条
ontology/learned.yaml     4 个指标补 requires / default_rationale
benchmark/ambiquery_v1.jsonl  schema 统一（指纹校验零变化）
scripts/test_mcp_client.py    补 run_metric 两条分支断言
../赛题二方向一-冲冠方案.md    §4.6 里程碑回填全量自检/澄清量化/工程加固
```

**生成产物（可复现，已加入 .gitignore 的为运行时产物）**
```
eval/charts/fig1_headline.png ~ fig4_ablation_cat.png   4 张实验图表
eval/iso_selfcheck.md + eval/iso_selfcheck_*.csv        120 题自检报告与明细
eval/clarification_report.md                            澄清 P/R/F1 报告
eval/cache_bench.md                                     缓存基准报告
eval/feedback_mining.md                                 回流挖掘报告
ontology/feedback_log.jsonl                             运行时产物（UI 澄清样本，已 gitignore）
```

---

## 8. 已知取舍与后续项

- **回流默认关闭**：库代码不写文件是刻意设计（避免副作用）；需要采集时显式开启。
- **`fastapi 0.115.6` 与本工程的 starlette 版本冲突**：`pip` 会提示，但本工程不用 fastapi，忽略即可；
  若其他项目需要 fastapi，建议单独虚拟环境。
- **待补能力**：对齐引擎的 embedding 检索与 LLM 仲裁通道；编译器 IR 抽象与多后端（API/解释型）。
- **人工步骤（按需）**：双人独立复核（工具与工作手册已就绪）、公开数据泛化演示。

---

> 复现全部验证：`python -m pytest && python scripts/check_ontology.py --execute && python scripts/eval_iso.py && python scripts/eval_clarification.py && python scripts/bench_cache.py`
