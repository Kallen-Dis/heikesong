# 独立改写与负向业务问题评测

开发后新增的独立手写反例；非严格holdout，不代表国际泛化；gold与核心使用同一仓库。

最新运行：2026-10-12T17:31:56.877005+00:00；运行次数：2；样本：24。

| 指标 | 首次运行 | 最新运行 |
|---|---|---|
| answer_coverage | 100.0%（14/14） | 100.0%（14/14） |
| answer_correctness_given_answer | 73.7%（14/19） | 100.0%（14/14） |
| answerable_correctness | 100.0%（14/14） | 100.0%（14/14） |
| blocked_execution_rate | 50.0%（5/10） | 0.0%（0/10） |
| expected_block_correctness | 50.0%（5/10） | 100.0%（10/10） |
| clarification_correct | 100.0%（4/4） | 100.0%（4/4） |
| overall_pass | 79.2%（19/24） | 100.0%（24/24） |

## 首次发现（保留，不随修复清除）

- **ADV19** 8月每笔实付超过1000元的订单量是多少？ — 期望初始类型 insufficient，实际 answer；最终 answer；完整结果正确=None；判定理由：当前IR不支持订单金额阈值筛选，不能忽略每笔金额条件。
- **ADV20** 8月订单量排名前三的品牌是哪些？ — 期望初始类型 insufficient，实际 answer；最终 answer；完整结果正确=None；判定理由：当前仅支持第一名且没有TopN计划，不能返回全量计数。
- **ADV22** 8月荣耀品牌的订单量是多少？ — 期望初始类型 insufficient，实际 answer；最终 answer；完整结果正确=None；判定理由：荣耀不在商品品牌词表中；不能遗漏未知品牌筛选而计算所有品牌。
- **ADV23** 8月已完成订单量是多少？ — 期望初始类型 insufficient，实际 answer；最终 answer；完整结果正确=None；判定理由：当前公开筛选计划没有任意订单状态，已完成不同于全部或仅剔除取消。
- **ADV24** 8月华东区订单量按天的趋势是多少？ — 期望初始类型 insufficient，实际 answer；最终 answer；完整结果正确=None；判定理由：当前没有按天聚合或趋势计划，不能以月总数充当趋势。

## 最新失败清单

无失败项。

## 判定与分母

- answerable：有手写gold的直接可答题，以及带明确choices的澄清后可答题。
- answer_coverage：可答题中最终实际返回answer的比例，不把必须拒答题计入分母。
- answer_correctness_given_answer：所有已输出answer的题中，完整结果表正确的比例；必须阻断题输出answer直接判错误。
- blocked_execution_rate：必须阻断题中仍返回answer的比例；error与clarification均不算成功阻断。
- clarification_correct：期望澄清的题中，首次实际返回clarification的比例；是否执行正确由完整结果评估。
- overall_pass：初始响应类型正确，且可答题完整gold匹配，必须阻断题最终为insufficient。

## 最新逐题结果

| ID | 类型 | 问题 | 结果 |
|---|---|---|---|
| ADV01 | answer | 8月苹果、华为与小米的净实付成交额对比 | PASS |
| ADV02 | answer | 2026年8月15日的订单数是多少？ | PASS |
| ADV03 | answer | 2025年12月31日到2026年1月2日的订单量是多少？ | PASS |
| ADV04 | answer | 2026年8月1日到2026年8月1日的订单量是多少？ | PASS |
| ADV05 | answer | 8月红苹果商贸有限公司在App渠道的订单量是多少？ | PASS |
| ADV06 | answer | 8月按已签收口径履约超时率最高的承运商是谁？ | PASS |
| ADV07 | answer | 8月剔除已取消后订单量最多的品牌是哪个？ | PASS |
| ADV08 | answer | 8月小程序渠道的妥投率是多少？ | PASS |
| ADV09 | answer | 8月APP渠道净实付成交额是多少？ | PASS |
| ADV10 | answer | 2026年8月15日从发货到签收大于48.5小时的运单有多少？ | PASS |
| ADV11 | clarification | 8月App渠道苹果的订单量是多少？ | PASS |
| ADV12 | clarification | 8月小程序渠道的成交额是多少？ | PASS |
| ADV13 | clarification | 最近小程序渠道的订单量是多少？ | PASS |
| ADV14 | clarification | 8月成交额最高的品类是哪个？ | PASS |
| ADV15 | insufficient | 8月的净利润是多少？ | PASS |
| ADV16 | insufficient | 8月订单量比7月涨了多少？ | PASS |
| ADV17 | insufficient | 8月App和小程序渠道净实付成交额对比 | PASS |
| ADV18 | insufficient | 2026年2月30日订单量是多少？ | PASS |
| ADV19 | insufficient | 8月每笔实付超过1000元的订单量是多少？ | PASS |
| ADV20 | insufficient | 8月订单量排名前三的品牌是哪些？ | PASS |
| ADV21 | insufficient | 8月各区域的订单量分别是多少？ | PASS |
| ADV22 | insufficient | 8月荣耀品牌的订单量是多少？ | PASS |
| ADV23 | insufficient | 8月已完成订单量是多少？ | PASS |
| ADV24 | insufficient | 8月华东区订单量按天的趋势是多少？ | PASS |
