# 预实验结果（v0）· 20260924_103618

- 题数：24（自动判定 23 / 人工复核 1）
- **语枢自动判定正确率：23/23 = 100.0%**
- **裸 DDL 基线正确率：7/23 = 30.4%**

## 分类战绩

| 类别 | 语枢 | 基线 |
|---|---|---|
| A_synonym | 4/4 | 0/4 |
| B_metric_ambiguity | 4/4 | 2/4 |
| C_entity_ambiguity | 3/3 | 2/3 |
| D_time | 4/4 | 1/4 |
| E_multi_hop | 4/4 | 2/4 |
| F_trap | 4/4 | 0/4 |

| id | 类别 | 问题 | 语枢 | 基线 |
|---|---|---|---|---|
| A01 | A_synonym | 8月华东区的妥投率是多少？ | PASS | FAIL |
| A02 | A_synonym | 8月的单量是多少？ | PASS | FAIL |
| A03 | A_synonym | 8月安达快递承运的运单平均履约时长是多少小时？ | PASS | FAIL |
| A04 | A_synonym | 8月华东区超时运单有多少？ | PASS | FAIL |
| B01 | B_metric_ambiguity | 8月的金额是多少？ | PASS | PASS |
| B02 | B_metric_ambiguity | 上个月的履约超时率是多少？ | PASS | PASS |
| B03 | B_metric_ambiguity | 最近的妥投率是多少？ | PASS | FAIL |
| B04 | B_metric_ambiguity | 8月华东区的GMV是多少？ | PASS | FAIL |
| C01 | C_entity_ambiguity | 8月苹果的订单量是多少？ | PASS | FAIL |
| C02 | C_entity_ambiguity | 8月苹果果业有限公司的订单量是多少？ | PASS | PASS |
| C03 | C_entity_ambiguity | 8月华东区苹果的金额是多少？ | PASS | PASS |
| C04 | C_entity_ambiguity | 8月苹果和华为的订单量对比 | MANUAL | MANUAL |
| D01 | D_time | 最近一周的订单量是多少？ | PASS | FAIL |
| D02 | D_time | 最近的订单量是多少？ | PASS | FAIL |
| D03 | D_time | 上个月的GMV是多少？ | PASS | PASS |
| D04 | D_time | 9月1日到9月10日的GMV是多少？ | PASS | FAIL |
| E01 | E_multi_hop | 8月超时运单最多的承运商是谁？ | PASS | FAIL |
| E02 | E_multi_hop | 8月华东区履约超时的订单里，哪个品类最多？ | PASS | PASS |
| E03 | E_multi_hop | 8月妥投率最高的区域是哪个？ | PASS | FAIL |
| E04 | E_multi_hop | 8月从发货到签收超过72小时的运单有多少？ | PASS | PASS |
| F01 | F_trap | 上个月华东区的退货率是多少？ | PASS | FAIL |
| F02 | F_trap | 8月的毛利是多少？ | PASS | FAIL |
| F03 | F_trap | 8月安卓机型的订单量是多少？ | PASS | FAIL |
| F04 | F_trap | 8月比7月增长了多少？ | PASS | FAIL |