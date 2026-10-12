"""Independent small warehouse: hand-checkable counts and intervention arithmetic."""
import json
import math

import duckdb
import pytest

from src.decision_lab import diagnose_carriers, simulate_intervention, wilson_interval


@pytest.fixture
def tiny_warehouse():
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE meta (key VARCHAR, value VARCHAR)")
    conn.execute("INSERT INTO meta VALUES ('dataset_end', '2026-07-01')")
    conn.execute("CREATE TABLE customers (customer_id VARCHAR, region VARCHAR)")
    conn.execute("INSERT INTO customers VALUES ('CE', '华东'), ('CW', '华西')")
    conn.execute("CREATE TABLE products (product_id VARCHAR)")
    conn.execute("INSERT INTO products VALUES ('P')")
    conn.execute("CREATE TABLE carriers (carrier_id VARCHAR, carrier_name VARCHAR)")
    conn.execute("INSERT INTO carriers VALUES ('A', '大样本'), ('B', '中样本'), ('C', '小样本')")
    conn.execute("CREATE TABLE orders (order_id VARCHAR, customer_id VARCHAR, product_id VARCHAR)")
    conn.execute("""CREATE TABLE shipments (shipment_id VARCHAR, order_id VARCHAR, carrier_id VARCHAR,
        ship_time TIMESTAMP, promised_time TIMESTAMP, delivery_time TIMESTAMP, status VARCHAR)""")
    orders, shipments = [], []
    for carrier, region, delivered, delayed, transit in (
            ('A', 'CE', 100, 20, 20), ('B', 'CE', 40, 12, 5), ('C', 'CE', 2, 2, 3),
            ('A', 'CW', 10, 1, 0)):
        for i in range(delivered + transit):
            number = len(orders) + 1
            orders.append((f'O{number}', region, 'P'))
            delivery = None if i >= delivered else ('2026-06-04' if i < delayed else '2026-06-02')
            shipments.append((f'S{number}', f'O{number}', carrier, '2026-06-01', '2026-06-03',
                              delivery, '运输中' if delivery is None else '已签收'))
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?)", orders)
    conn.executemany("INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?, ?)", shipments)
    yield conn
    conn.close()


def diagnose(conn, **kwargs):
    options = dict(region='华东', coverage=.5, effectiveness=.5,
                   cost_per_covered_shipment=10, budget=500)
    options.update(kwargs)
    return diagnose_carriers(conn, '2026-06-01', '2026-06-30', **options)


def test_exact_counts_denominator_and_budget(tiny_warehouse):
    result = diagnose(tiny_warehouse)
    assert result['status'] == 'ok', result
    assert result['overall']['shipment_count'] == 170
    assert result['overall']['delivered_count'] == 142
    assert result['overall']['delayed_count'] == 34
    assert result['overall']['in_transit_count'] == 28
    assert result['overall']['delay_rate'] == pytest.approx(34 / 142)
    assert result['overall']['in_transit_share'] == pytest.approx(28 / 170)
    groups = {g['carrier_id']: g for g in result['groups']}
    assert groups['A']['delay_rate'] == .2
    assert groups['B']['delay_rate'] == .3
    assert groups['C']['delay_rate'] == 1
    assert not groups['C']['eligible_for_intervention']
    assert [p['carrier_id'] for p in result['priority']] == ['A', 'B']
    simulation = result['simulation']
    assert simulation['excluded_small_sample_delivered_count'] == 2
    assert simulation['scenarios']['base']['covered_shipments'] == 50
    assert simulation['scenarios']['base']['expected_avoided_delays'] == pytest.approx(6)
    assert simulation['scenarios']['worst']['expected_avoided_delays'] == pytest.approx(4.8)
    assert simulation['scenarios']['best']['expected_avoided_delays'] == pytest.approx(7.2)
    assert simulation['scenarios']['base']['estimated_cost'] == 500
    assert simulation['scenarios']['base']['breakeven_value_per_avoided_delay'] == pytest.approx(500 / 6)
    assert simulation['scenarios']['base']['expected_remaining_delays'] == 28
    assert simulation['unspent_budget'] == 0
    assert any(q['sql'].startswith('SELECT k.carrier_id') for q in result['executed_queries'])
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_one_shared_budget_and_fully_funded(tiny_warehouse):
    result = diagnose(tiny_warehouse, budget=1500)
    scenario = result['simulation']['scenarios']['base']
    assert scenario['covered_shipments'] == 70
    assert scenario['estimated_cost'] == 700
    assert scenario['expected_avoided_delays'] == pytest.approx(8)
    assert result['simulation']['unspent_budget'] == 800


@pytest.mark.parametrize('field', ['coverage', 'effectiveness', 'cost_per_covered_shipment', 'budget'])
@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), float('-inf')])
def test_invalid_assumptions_fail_closed(tiny_warehouse, field, value):
    result = diagnose(tiny_warehouse, **{field: value})
    assert result['status'] == 'blocked'
    assert 'simulation' not in result
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('kwargs', [{'coverage': 1.1}, {'effectiveness': 1.1}, {'min_sample': 0},
                                    {'min_sample': 1.5}, {'min_sample': True}, {'region': '不存在'},
                                    {'region': ''}, {'group_by_region': 'yes'}])
def test_invalid_options(tiny_warehouse, kwargs):
    assert diagnose(tiny_warehouse, **kwargs)['status'] == 'blocked'


@pytest.mark.parametrize('start,end', [('invalid', '2026-06-30'), ('2026-02-30', '2026-06-30'),
                                      ('2026-07-01', '2026-06-30'), ('2026-06-01', '2026-07-02'),
                                      ('20260601', '2026-06-30')])
def test_invalid_dates(tiny_warehouse, start, end):
    assert diagnose_carriers(tiny_warehouse, start, end)['status'] == 'blocked'


def test_zero_denominator_and_future_delivery(tiny_warehouse):
    tiny_warehouse.execute("UPDATE shipments SET delivery_time='2026-07-02'")
    result = diagnose(tiny_warehouse)
    assert result['status'] == 'blocked'
    assert result['overall']['delay_rate'] is None
    assert result['overall']['in_transit_count'] == 170
    assert 'simulation' not in result


@pytest.mark.parametrize('budget,cost', [(0, 10), (0, 0), (100, 0)])
def test_zero_budget_and_zero_cost(tiny_warehouse, budget, cost):
    result = diagnose(tiny_warehouse, budget=budget, cost_per_covered_shipment=cost)
    scenario = result['simulation']['scenarios']['base']
    assert scenario['estimated_cost'] == 0
    assert scenario['covered_shipments'] == (70 if budget else 0)
    assert scenario['breakeven_value_per_avoided_delay'] == (0 if budget else None)


def test_zero_effectiveness_and_cap(tiny_warehouse):
    zero = diagnose(tiny_warehouse, effectiveness=0)['simulation']['scenarios']['base']
    assert zero['expected_avoided_delays'] == 0
    assert zero['breakeven_value_per_avoided_delay'] is None
    assert diagnose(tiny_warehouse, effectiveness=.95)['simulation']['scenarios']['best']['effectiveness'] == 1


def test_group_by_region_and_overall_weighting(tiny_warehouse):
    result = diagnose(tiny_warehouse, region=None, group_by_region=True)
    assert result['overall']['delay_rate'] == pytest.approx(35 / 152)
    assert len(result['groups']) == 4
    assert {g['region'] for g in result['groups']} == {'华东', '华西'}


def test_relationship_violation_blocks_before_join(tiny_warehouse):
    tiny_warehouse.execute("INSERT INTO carriers VALUES ('A', '重复行')")
    result = diagnose(tiny_warehouse)
    assert result['status'] == 'blocked'
    assert result['relationship_violations']
    assert result['groups'] == []


def test_relationship_validator_exception_fails_closed(tiny_warehouse, monkeypatch):
    def fail(_conn):
        raise RuntimeError('validation unavailable')
    monkeypatch.setattr('src.decision_lab.validate_relationships', fail)
    result = diagnose(tiny_warehouse)
    assert result['status'] == 'blocked'
    assert result['groups'] == []
    assert result['executed_queries'] == []


def test_no_matching_shipments_zero_denominator(tiny_warehouse):
    result = diagnose_carriers(tiny_warehouse, '2026-06-10', '2026-06-30')
    assert result['status'] == 'blocked'
    assert result['overall']['delivered_count'] == 0
    assert result['overall']['wilson95'] is None


def test_sql_parameters_not_interpolated(tiny_warehouse):
    result = diagnose(tiny_warehouse, region="华东' OR 1=1 --")
    assert result['status'] == 'blocked'
    assert tiny_warehouse.execute('SELECT COUNT(*) FROM shipments').fetchone()[0] == 180
    assert result['executed_queries'][-1]['parameters'] == ["华东' OR 1=1 --"]


def test_wilson_interval_known_values():
    lower, upper = wilson_interval(20, 100)
    assert lower == pytest.approx(.1333669, abs=1e-6)
    assert upper == pytest.approx(.2888292, abs=1e-6)
    assert wilson_interval(0, 0) is None
    assert wilson_interval(0, 100)[0] == pytest.approx(0, abs=1e-15)
    assert math.isfinite(wilson_interval(2, 2)[0])


def test_budget_strategy_counterexample_uses_unit_benefit():
    # Volume-first would cover A: 100 × .05 × .5 = 2.5 avoided delays.
    # Rate-first covers B: 100 × .40 × .5 = 20 avoided delays.
    groups = [dict(carrier_id='A', carrier_name='规模大', region=None,
                   delivered_count=1000, delayed_count=50, delay_rate=.05, eligible_for_intervention=True),
              dict(carrier_id='B', carrier_name='单位收益高', region=None,
                   delivered_count=100, delayed_count=40, delay_rate=.4, eligible_for_intervention=True)]
    simulation = simulate_intervention(groups, coverage=1, effectiveness=.5,
                                       cost_per_covered_shipment=1, budget=100)
    assert simulation['allocations'][0]['carrier_id'] == 'B'
    assert simulation['allocations'][0]['covered_shipments'] == 100
    assert simulation['scenarios']['base']['expected_avoided_delays'] == 20


def test_decimal_cost_does_not_lose_whole_shipment_to_binary_rounding(tiny_warehouse):
    result = diagnose(tiny_warehouse, budget=.3, cost_per_covered_shipment=.1)
    assert result['simulation']['scenarios']['base']['covered_shipments'] == 3
    assert result['simulation']['unspent_budget'] == 0
