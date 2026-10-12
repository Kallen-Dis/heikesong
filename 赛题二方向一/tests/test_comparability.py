"""Independent arithmetic and joint-support counterexamples, no external services."""
import copy
import json

import pytest

from src.comparability import SYNTHETIC_EXAMPLE, compare_carriers


def example():
    return copy.deepcopy(SYNTHETIC_EXAMPLE)


def test_no_weights_requires_explicit_declaration():
    result = compare_carriers(example())
    assert result['status'] == 'needs_weights'
    assert result['raw_pooled_rates'] == {'A': .028, 'B': .082}
    assert 'weighted_rates' not in result
    assert not result['reversal_evaluated']
    assert result['recommendation']['action'] == 'blocked_causal_recommendation'


def test_simpson_reversal_equal_common_weights():
    result = compare_carriers(example(), {'华东': .5, '华南': .5})
    assert result['status'] == 'ok'
    assert result['weighted_rates']['A'] == pytest.approx(.06)
    assert result['weighted_rates']['B'] == pytest.approx(.05)
    assert result['reversal'] is True
    assert all(row['rates']['A'] > row['rates']['B'] for row in result['by_region'])
    assert result['recommendation']['action'] == 'blocked_causal_recommendation'
    json.dumps(result, allow_nan=False)


def test_no_reversal():
    records = [{'carrier': c, 'region': r, 'delivered': 100, 'delayed': k}
               for c, r, k in [('A', '东', 10), ('A', '南', 10), ('B', '东', 20), ('B', '南', 30)]]
    result = compare_carriers(records, {'东': .5, '南': .5})
    assert result['status'] == 'ok'
    assert result['reversal'] is False
    assert result['weighted_rates']['A'] == .1
    assert result['weighted_rates']['B'] == .25


def test_zero_weight_permitted_but_support_still_required():
    result = compare_carriers(example(), {'华东': 1, '华南': 0})
    assert result['status'] == 'ok'
    assert result['weighted_rates'] == {'A': .02, 'B': .01}
    assert result['reversal'] is True
    missing = example()[:-1]
    assert compare_carriers(missing, {'华东': 1, '华南': 0})['code'] == 'missing_joint_support'


def test_duplicate_pair_blocked():
    records = example()
    records.append(records[0].copy())
    assert compare_carriers(records)['code'] == 'duplicate_pair'


def test_zero_denominator_blocked_even_when_weight_is_zero():
    records = example()
    records[1].update(delivered=0, delayed=0)
    result = compare_carriers(records, {'华东': 1, '华南': 0})
    assert result['code'] == 'zero_denominator'


@pytest.mark.parametrize('payload', [None, [], 'records', [{}]])
def test_invalid_payload(payload):
    result = compare_carriers(payload)
    assert result['status'] == 'blocked'
    json.dumps(result, allow_nan=False)


def test_invalid_counts():
    for delivered, delayed in [(10, 11), (-1, 0), (10, -1), (10., 1), (True, 1), (10, float('nan'))]:
        records = example()
        records[0].update(delivered=delivered, delayed=delayed)
        result = compare_carriers(records)
        assert result['code'] == 'invalid_counts'
        json.dumps(result, allow_nan=False)


def test_exact_weight_region_set():
    for weights in [{'华东': 1}, {'华东': .5, '华南': .5, '华北': 0}, []]:
        assert compare_carriers(example(), weights)['code'] == 'invalid_weight_regions'


def test_invalid_weight_values_and_sum():
    for value in [-1, float('nan'), float('inf'), '0.5', True]:
        result = compare_carriers(example(), {'华东': value, '华南': .5})
        assert result['code'] == 'invalid_weight'
        json.dumps(result, allow_nan=False)
    assert compare_carriers(example(), {'华东': .2, '华南': .2})['code'] == 'invalid_weight_sum'


def test_float_tolerance_is_explicit():
    result = compare_carriers(example(), {'华东': .5, '华南': .5000000001})
    assert result['status'] == 'ok'
    assert result['weight_sum'] == pytest.approx(1.0000000001)
    assert result['weights']['华南'] == .5000000001


def test_requires_two_carriers_and_multiple_regions():
    assert compare_carriers(example()[:2])['code'] == 'carrier_count'
    assert compare_carriers([example()[0], example()[2]])['code'] == 'region_count'
    records = example()
    records.append({'carrier': 'C', 'region': '华东', 'delivered': 1, 'delayed': 0})
    assert compare_carriers(records)['code'] == 'carrier_count'


def test_input_not_mutated_and_tie_not_reversal():
    records = [{'carrier': c, 'region': r, 'delivered': 10, 'delayed': 1}
               for c in ['A', 'B'] for r in ['东', '南']]
    original = copy.deepcopy(records)
    weights = {'东': .5, '南': .5}
    result = compare_carriers(records, weights)
    assert result['reversal'] is False
    assert records == original
    assert weights == {'东': .5, '南': .5}


def test_general_three_region_weights():
    records = [{'carrier': c, 'region': r, 'delivered': 100, 'delayed': k}
               for c, r, k in [('A', '东', 10), ('A', '南', 20), ('A', '北', 30),
                               ('B', '东', 20), ('B', '南', 30), ('B', '北', 40)]]
    result = compare_carriers(records, {'东': .2, '南': .3, '北': .5})
    assert result['status'] == 'ok'
    assert result['weighted_rates']['A'] == pytest.approx(.23)
    assert result['weighted_rates']['B'] == pytest.approx(.33)


def test_invalid_identifiers_and_boolean_delayed():
    for carrier, region, delayed in [('', '华东', 1), ('A', None, 1), ('A', '华东', True)]:
        records = example()
        records[0].update(carrier=carrier, region=region, delayed=delayed)
        assert compare_carriers(records)['status'] == 'blocked'
