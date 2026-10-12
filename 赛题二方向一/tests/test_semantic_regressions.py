# -*- coding: utf-8 -*-
"""独立构造反例，不复用 AmbiQuery 的 gold 或生成数据。"""
import duckdb
import pandas as pd
import pytest

from src.alignment import Aligner, Alignment, TimeRange
from src.benchmark import results_match
from src.compiler import Compiler


@pytest.fixture()
def semantic_db():
    conn = duckdb.connect()
    conn.execute("CREATE TABLE meta (key VARCHAR, value VARCHAR); INSERT INTO meta VALUES ('dataset_end','2026-09-20')")
    conn.execute("CREATE TABLE customers (customer_id VARCHAR, customer_name VARCHAR, region VARCHAR); INSERT INTO customers VALUES ('C1','苹果果业有限公司','华东'),('C2','其他客户有限公司','华南')")
    conn.execute("CREATE TABLE products (product_id VARCHAR, brand VARCHAR, category VARCHAR); INSERT INTO products VALUES ('P1','苹果','数码'),('P2','华为','数码')")
    conn.execute("CREATE TABLE carriers (carrier_id VARCHAR, carrier_name VARCHAR); INSERT INTO carriers VALUES ('K1','甲快递'),('K2','乙快递')")
    conn.execute("""CREATE TABLE orders (order_id VARCHAR, customer_id VARCHAR, product_id VARCHAR,
        order_time TIMESTAMP, order_amount DOUBLE, pay_amount DOUBLE, status VARCHAR, channel VARCHAR);
        INSERT INTO orders VALUES
        ('O1','C1','P1','2026-08-01 10:00',1000,900,'已取消','App'),
        ('O2','C1','P2','2026-08-01 10:00',10,9,'已完成','Web'),
        ('O3','C2','P2','2026-08-01 10:00',100,90,'已完成','App'),
        ('O4','C2','P1','2026-08-01 10:00',100,50,'已完成','App')""")
    conn.execute("""CREATE TABLE shipments (shipment_id VARCHAR, order_id VARCHAR, carrier_id VARCHAR,
        ship_time TIMESTAMP, delivery_time TIMESTAMP, promised_time TIMESTAMP);
        INSERT INTO shipments VALUES
        ('S1','O1','K1','2026-08-01 10:00','2026-08-03 10:30','2026-08-03 10:00'),
        ('S2','O2','K1','2026-08-01 10:00','2026-08-03 09:30','2026-08-03 11:00'),
        ('S3','O3','K2','2026-08-01 10:00','2026-08-03 11:00','2026-08-03 10:00'),
        ('S4','O4','K1','2026-08-01 10:00','2026-08-03 08:00','2026-08-03 02:00')""")
    yield conn
    conn.close()


def compiled(semantic_db, question):
    aligner = Aligner(semantic_db)
    a = aligner.align(question)
    assert not a.unsupported and not a.clarify, a
    result = Compiler(aligner.metrics).compile(a)
    return semantic_db.execute(result.sql, result.params).fetchdf(), result


def test_channel_filter_is_applied_to_the_result(semantic_db):
    df, result = compiled(semantic_db, '8月app渠道的订单量是多少？')
    assert df.iloc[0, 0] == 3
    assert 'o.channel = ?' in result.sql and 'App' in result.params


@pytest.mark.parametrize('question', [
    '8月订单量比7月增长多少？', '8月订单量的同比是多少？',
    '8月与7月的订单量对比', '7月至8月的订单量是多少？',
    '8月华东和华南订单量对比', '8月App和Web渠道订单量对比',
    '8月订单量排除华东', '8月订单量和妥投率是多少？',
    '8月签收率超过48小时是多少？', '8月耗时超过48小时最多的品牌是哪个？',
    '2026年13月订单量是多少？', '9月10日到9月1日订单量是多少？',
    '近0天订单量是多少？',
    '8月1日到7日订单量是多少？', '8月各渠道订单量是多少？',
    '8月苹果和华为耗时超过48小时运单数量对比',
])
def test_unsupported_composition_is_declined_before_compilation(semantic_db, question):
    a = Aligner(semantic_db).align(question)
    assert a.unsupported and not a.clarify


def test_rate_ranking_does_not_silently_become_a_count_ranking(semantic_db):
    df, result = compiled(semantic_db, '8月按全部运单口径超时率最高的承运商是谁？')
    assert df.iloc[0, 0] == '乙快递'  # 1/1 > 2/3，而数量为甲快递2 > 乙快递1
    assert 'COUNT(*) FILTER' in result.sql and '* 1.0 / COUNT(*)' in result.sql


def test_ranking_respects_explicit_net_variant(semantic_db):
    df, result = compiled(semantic_db, '8月净实付GMV最多的品牌是哪个？')
    assert df.iloc[0, 0] == '华为'  # 净额99 > 50；毛额则苹果1100 > 华为110
    assert "o.status <> '已取消'" in result.sql


def test_multi_variant_ranking_requires_a_choice(semantic_db):
    a = Aligner(semantic_db).align('8月GMV最多的品牌是哪个？')
    assert [p.id for p in a.clarify] == ['variant']
    with pytest.raises(ValueError, match='澄清'):
        Compiler(Aligner(semantic_db).metrics).compile(a)


def test_order_metric_carrier_filter_has_all_join_dependencies(semantic_db):
    df, result = compiled(semantic_db, '8月甲快递承运的订单量是多少？')
    assert df.iloc[0, 0] == 3
    assert 'JOIN shipments' in result.sql and 'JOIN carriers' in result.sql
    assert any('仅统计已关联运单' in d for d in result.disclosure)


def test_fractional_hours_are_counted_as_elapsed_duration(semantic_db):
    df, _ = compiled(semantic_db, '8月从发货到签收超过48小时的运单有多少？')
    assert df.iloc[0, 0] == 2  # 48.5h和49h；date_diff('hour')旧实现只计49h


def test_fulfillment_duration_word_in_threshold_count_is_an_attribute(semantic_db):
    df, _ = compiled(semantic_db, '8月履约时长超过48小时的运单有多少？')
    assert df.iloc[0, 0] == 2


def test_brand_filters_survive_threshold_queries(semantic_db):
    df, result = compiled(semantic_db, '8月苹果和华为从发货到签收超过48小时运单有多少？')
    assert df.iloc[0, 0] == 2
    assert 'p.brand IN (?, ?)' in result.sql


def test_future_month_still_has_a_valid_empty_interval(semantic_db):
    a = Aligner(semantic_db).align('2027年1月订单量是多少？')
    assert a.time.start == pd.Timestamp('2027-01-01')
    assert a.time.end_excl == pd.Timestamp('2027-02-01')


def test_explicit_year_is_preserved_in_a_day_range(semantic_db):
    a = Aligner(semantic_db).align('2025年8月1日到2025年8月7日订单量是多少？')
    assert a.time.start == pd.Timestamp('2025-08-01')
    assert a.time.end_excl == pd.Timestamp('2025-08-08')


def test_single_day_does_not_silently_expand_to_a_month(semantic_db):
    a = Aligner(semantic_db).align('2026年8月15日订单量是多少？')
    assert a.time.start == pd.Timestamp('2026-08-15')
    assert a.time.end_excl == pd.Timestamp('2026-08-16')


def test_full_result_comparison_catches_numeric_and_missing_row_errors():
    gold = pd.DataFrame([['苹果', 4], ['华为', 9]])
    assert results_match(gold, gold.iloc[::-1])
    assert not results_match(pd.DataFrame([['苹果', 400], ['华为', 9]]), gold)
    assert not results_match(gold.head(1), gold)
    assert not results_match(pd.DataFrame([['苹果', 4], ['苹果', 4]]), gold)
    assert not results_match(gold, gold.iloc[::-1], ordered=True)
    assert results_match(pd.DataFrame([[None]]), pd.DataFrame([[float('nan')]]))
    assert results_match(pd.DataFrame([[pd.NA]]), pd.DataFrame([[None]]))


@pytest.mark.parametrize('filters', [
    {'region_ne': '华东'}, {'channel': ['App']}, {'brands': []}, {'brands': '苹果'},
    {'brands': [None]}, {'brand': '苹果', 'brands': ['华为']},
])
def test_compiler_rejects_unrepresentable_filter_payloads(semantic_db, filters):
    a = Aligner(semantic_db).align('8月订单量是多少？')
    a.filters = filters
    with pytest.raises(ValueError):
        Compiler(Aligner(semantic_db).metrics).compile(a)


@pytest.mark.parametrize('threshold', [float('nan'), float('inf'), -1, True, '48'])
def test_compiler_rejects_invalid_thresholds(semantic_db, threshold):
    a = Alignment(question='threshold', threshold_hours=threshold,
                  time=TimeRange(pd.Timestamp('2026-08-01'), pd.Timestamp('2026-09-01'), '8月'))
    with pytest.raises(ValueError, match='阈值'):
        Compiler(Aligner(semantic_db).metrics).compile(a)


@pytest.mark.parametrize('start,end', [(pd.NaT, pd.Timestamp('2026-09-01')),
                                      (pd.Timestamp('2026-09-01'), pd.Timestamp('2026-08-01'))])
def test_compiler_rejects_invalid_windows(semantic_db, start, end):
    a = Aligner(semantic_db).align('8月订单量是多少？')
    a.time = TimeRange(start, end, 'invalid')
    with pytest.raises(ValueError, match='时间范围无效'):
        Compiler(Aligner(semantic_db).metrics).compile(a)


def test_compiler_rejects_unknown_ranking_dimension(semantic_db):
    a = Aligner(semantic_db).align('8月订单量最多的品牌是哪个？')
    a.ranking['dim'] = 'unknown'
    with pytest.raises(ValueError, match='排名'):
        Compiler(Aligner(semantic_db).metrics).compile(a)


@pytest.mark.parametrize('ranking', [{}, {'dim': 'brand', 'metric': 'GMV'}, ['brand']])
def test_compiler_rejects_incomplete_or_inconsistent_ranking(semantic_db, ranking):
    a = Aligner(semantic_db).align('8月订单量是多少？')
    a.ranking = ranking
    with pytest.raises(ValueError, match='排名'):
        Compiler(Aligner(semantic_db).metrics).compile(a)
