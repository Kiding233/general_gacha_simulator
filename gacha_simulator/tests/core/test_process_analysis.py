import pytest
from gacha_simulator.core.process_trace import PoolEvent, SampleTrace, infer_events
from gacha_simulator.core.process_analysis import (
    compute_aa, compute_bb, compute_ab, compute_ba,
    to_event_type_sequence, to_event_type_set, to_event_count_set,
    to_custom_pattern,
    to_raw_trajectory, to_success_sequence, to_success_set, to_success_count,
    to_success_custom,
    _hashable, _unhashable,
)


def _make_trace(events, pool_success=None, is_success=False, gdr_value=0.0):
    return SampleTrace(
        events=events,
        pool_success=pool_success or {},
        is_success=is_success,
        gdr_value=gdr_value,
    )


def _make_event(pool_id, event_type, pity_name=None, draws=0, counter_max=0):
    return PoolEvent(
        pool_id=pool_id,
        pool_type='draw',
        event_type=event_type,
        pity_name=pity_name,
        draws=draws,
        counter_max=counter_max,
    )


class TestInferEvents:
    def test_early_hit(self):
        compact = {
            'draw_pool_ids': ['pool_a', 'pool_a'],
            'draw_card_ids': ['_no_card', 'target_1'],
            'draw_pity': [False, False],
            'draw_pity_names': [None, None],
            'draw_pity_counter_max': [30, 45],
            'pool_card_counts': {'pool_a': {'target_1': 1}},
            'pool_draw_counts': {'pool_a': 2},
        }
        result = infer_events(compact, {'target_1'})
        assert result['pool_a'].event_type == 'early_hit'
        assert result['pool_a'].draws == 2
        assert result['pool_a'].counter_max == 45

    def test_pity_hit(self):
        compact = {
            'draw_pool_ids': ['pool_a', 'pool_a'],
            'draw_card_ids': ['_no_card', 'target_1'],
            'draw_pity': [False, True],
            'draw_pity_names': [None, 'ssr_soft'],
            'draw_pity_counter_max': [75, 90],
            'pool_card_counts': {'pool_a': {'target_1': 1}},
            'pool_draw_counts': {'pool_a': 2},
        }
        result = infer_events(compact, {'target_1'})
        assert result['pool_a'].event_type == 'pity_hit'
        assert result['pool_a'].pity_name == 'ssr_soft'

    def test_miss(self):
        compact = {
            'draw_pool_ids': ['pool_a', 'pool_a'],
            'draw_card_ids': ['_no_card', '_no_card'],
            'draw_pity': [False, False],
            'draw_pity_names': [None, None],
            'draw_pity_counter_max': [10, 20],
            'pool_card_counts': {'pool_a': {}},
            'pool_draw_counts': {'pool_a': 2},
        }
        result = infer_events(compact, {'target_1'})
        assert result['pool_a'].event_type == 'miss'

    def test_skip(self):
        compact = {
            'draw_pool_ids': [],
            'draw_card_ids': [],
            'draw_pity': [],
            'draw_pity_names': [],
            'draw_pity_counter_max': [],
            'pool_card_counts': {'pool_a': {}},
            'pool_draw_counts': {'pool_a': 0},
        }
        result = infer_events(compact, {'target_1'})
        assert result['pool_a'].event_type == 'skip'

    def test_ignore(self):
        compact = {
            'draw_pool_ids': [],
            'draw_card_ids': [],
            'draw_pity': [],
            'draw_pity_names': [],
            'draw_pity_counter_max': [],
            'pool_card_counts': {},
            'pool_draw_counts': {'pool_a': 0},
        }
        result = infer_events(compact, set())
        assert result['pool_a'].event_type == 'ignore'


class TestInferEventsFromAggregate:
    def test_early_hit_aggregate(self):
        compact = {
            'pool_draw_counts': {'pool_a': 10, 'pool_b': 5},
            'pool_card_counts': {'pool_a': {'target_1': 2}, 'pool_b': {}},
            'pool_pity_counts': {'pool_a': 0, 'pool_b': 0},
        }
        result = infer_events(compact, {'target_1'})
        assert result['pool_a'].event_type == 'early_hit'
        assert result['pool_a'].draws == 10
        assert result['pool_b'].event_type == 'miss'
        assert result['pool_b'].draws == 5

    def test_pity_hit_aggregate(self):
        compact = {
            'pool_draw_counts': {'pool_a': 20},
            'pool_card_counts': {'pool_a': {'target_1': 1}},
            'pool_pity_counts': {'pool_a': 3},
        }
        result = infer_events(compact, {'target_1'})
        assert result['pool_a'].event_type == 'pity_hit'

    def test_miss_aggregate(self):
        compact = {
            'pool_draw_counts': {'pool_a': 15, 'pool_b': 8},
            'pool_card_counts': {'pool_a': {}, 'pool_b': {}},
            'pool_pity_counts': {'pool_a': 0, 'pool_b': 0},
        }
        result = infer_events(compact, {'target_1'})
        assert result['pool_a'].event_type == 'miss'
        assert result['pool_b'].event_type == 'miss'

    def test_skip_aggregate(self):
        compact = {
            'pool_draw_counts': {'pool_a': 0, 'pool_b': 0},
            'pool_card_counts': {'pool_a': {'target_1': 0}, 'pool_b': {}},
            'pool_pity_counts': {},
        }
        result = infer_events(compact, {'target_1'})
        assert result['pool_a'].event_type == 'skip'
        assert result['pool_b'].event_type == 'skip'

    def test_ignore_aggregate_empty_target(self):
        compact = {
            'pool_draw_counts': {'pool_a': 0},
            'pool_card_counts': {},
            'pool_pity_counts': {},
        }
        result = infer_events(compact, set())
        assert result['pool_a'].event_type == 'ignore'


class TestEventModeConversions:
    def test_to_event_type_sequence(self):
        events = [
            _make_event('a', 'early_hit'),
            _make_event('b', 'miss'),
            _make_event('c', 'pity_hit', pity_name='ssr_soft'),
        ]
        assert to_event_type_sequence(events) == ('early_hit', 'miss', 'pity_hit')

    def test_to_event_type_set(self):
        events = [
            _make_event('a', 'early_hit'),
            _make_event('b', 'miss'),
            _make_event('c', 'early_hit'),
        ]
        result = to_event_type_set(events)
        assert set(result) == {'early_hit', 'miss'}

    def test_to_custom_pattern_no_constraints(self):
        events = [
            _make_event('a', 'early_hit'),
            _make_event('b', 'miss'),
            _make_event('c', 'early_hit'),
        ]
        result = to_custom_pattern(events)
        assert result == {
            'pity_hit': '保底出=0',
            'early_hit': '提前出=2',
            'miss': '没出=1',
            'skip': '跳过=0',
            'ignore': '忽略=0',
        }

    def test_to_custom_pattern_with_constraints(self):
        events = [
            _make_event('a', 'early_hit'),
            _make_event('b', 'miss'),
            _make_event('c', 'early_hit'),
            _make_event('d', 'pity_hit'),
        ]
        result = to_custom_pattern(events, constraints={
            'pity_hit': ('>=', 2),
            'early_hit': ('=', 2),
            'miss': ('<', 2),
            'skip': ('any', 0),
        })
        assert result['pity_hit'] == '保底出<2'
        assert result['early_hit'] == '提前出=2'
        assert result['miss'] == '没出<2'
        assert 'skip' not in result
        assert 'ignore' not in result

    def test_to_event_count_set(self):
        events = [
            _make_event('a', 'early_hit'),
            _make_event('b', 'miss'),
            _make_event('c', 'early_hit'),
        ]
        result = to_event_count_set(events)
        assert result == (0, 2, 1, 0, 0)

    def test_unhashable_restores_dict(self):
        d = {'a': '1', 'b': '2'}
        h = _hashable(d)
        u = _unhashable(h)
        assert isinstance(u, dict)
        assert u == d

    def test_compute_aa_with_custom_constraints(self):
        events = [
            _make_event('pool1', 'early_hit'),
            _make_event('pool2', 'miss'),
        ]
        trace = _make_trace(events, is_success=True)
        results = compute_aa([trace], 'custom', constraints={'early_hit': ('>=', 1), 'miss': ('=', 1)})
        assert len(results) >= 1
        pattern = results[0]['pattern']
        assert isinstance(pattern, dict)

    def test_compute_aa_custom_shows_all_combinations(self):
        events = [
            _make_event('pool1', 'early_hit'),
            _make_event('pool2', 'miss'),
        ]
        trace = _make_trace(events, is_success=True)
        results = compute_aa([trace], 'custom', constraints={'early_hit': ('>=', 1), 'miss': ('=', 1)})
        patterns = [r['pattern'] for r in results]
        has_nonzero = any(r['count'] > 0 for r in results)
        has_zero = any(r['count'] == 0 for r in results)
        assert has_nonzero
        assert has_zero
        assert len(results) == 4

    def test_to_raw_trajectory(self):
        events = [
            _make_event('a', 'early_hit', draws=45),
            _make_event('b', 'pity_hit', pity_name='ssr_soft'),
            _make_event('c', 'miss'),
        ]
        result = to_raw_trajectory(events)
        assert result == ('early_hit(45)', 'pity_hit:ssr_soft', 'miss')

    def test_to_raw_trajectory_counter_max_zero(self):
        events = [
            _make_event('a', 'early_hit', counter_max=0),
            _make_event('b', 'miss'),
        ]
        result = to_raw_trajectory(events)
        assert result == ('early_hit', 'miss')


class TestSuccessModeConversions:
    def test_to_success_sequence(self):
        ps = {'pool_a': True, 'pool_b': False, 'pool_c': True}
        assert to_success_sequence(ps) == (True, False, True)

    def test_to_success_set(self):
        ps = {'pool_a': True, 'pool_b': False, 'pool_c': True}
        assert to_success_set(ps) == (2, 1)

    def test_to_success_count(self):
        ps = {'pool_a': True, 'pool_b': False, 'pool_c': True}
        assert to_success_count(ps) == 2

    def test_to_success_custom_equal(self):
        ps = {'pool_a': True, 'pool_b': False, 'pool_c': True}
        assert to_success_custom(ps, op='=', n=2) == '=2'
        assert to_success_custom(ps, op='=', n=3) == '≠3'

    def test_to_success_custom_at_most(self):
        ps = {'pool_a': True, 'pool_b': False, 'pool_c': True}
        assert to_success_custom(ps, op='<=', n=2) == '≤2'
        assert to_success_custom(ps, op='<=', n=1) == '>1'

    def test_to_success_custom_at_least(self):
        ps = {'pool_a': True, 'pool_b': False, 'pool_c': True}
        assert to_success_custom(ps, op='>=', n=2) == '≥2'
        assert to_success_custom(ps, op='>=', n=3) == '<3'

    def test_to_success_custom_greater(self):
        ps = {'pool_a': True, 'pool_b': False, 'pool_c': True}
        assert to_success_custom(ps, op='>', n=1) == '>1'
        assert to_success_custom(ps, op='>', n=2) == '≤2'

    def test_to_success_custom_less(self):
        ps = {'pool_a': True, 'pool_b': False, 'pool_c': True}
        assert to_success_custom(ps, op='<', n=3) == '<3'
        assert to_success_custom(ps, op='<', n=2) == '≥2'


class TestComputeAA:
    def test_basic(self):
        traces = [
            _make_trace([_make_event('a', 'early_hit'), _make_event('b', 'miss')]),
            _make_trace([_make_event('a', 'early_hit'), _make_event('b', 'miss')]),
            _make_trace([_make_event('a', 'pity_hit'), _make_event('b', 'early_hit')]),
        ]
        results = compute_aa(traces, 'sequence')
        assert len(results) == 2
        assert results[0]['pattern'] == ['early_hit', 'miss']
        assert results[0]['count'] == 2
        assert results[0]['probability'] == pytest.approx(2 / 3)

    def test_empty(self):
        assert compute_aa([], 'sequence') == []

    def test_set_mode(self):
        traces = [
            _make_trace([_make_event('a', 'early_hit'), _make_event('b', 'miss')]),
            _make_trace([_make_event('a', 'miss'), _make_event('b', 'early_hit')]),
        ]
        results = compute_aa(traces, 'set')
        assert len(results) == 1
        assert set(results[0]['pattern']) == {'early_hit', 'miss'}
        assert results[0]['count'] == 2


class TestComputeBB:
    def test_basic(self):
        traces = [
            _make_trace([], pool_success={'a': True, 'b': True}, is_success=True),
            _make_trace([], pool_success={'a': True, 'b': False}, is_success=False),
            _make_trace([], pool_success={'a': False, 'b': False}, is_success=False),
        ]
        results = compute_bb(traces, 'count')
        assert results['total'] == 3
        assert results['never_fail_prob'] == pytest.approx(1 / 3)
        assert results['never_success_prob'] == pytest.approx(1 / 3)
        assert results['pool_success_rates']['a'] == pytest.approx(2 / 3)
        assert results['pool_success_rates']['b'] == pytest.approx(1 / 3)

    def test_custom_mode_shows_all_buckets(self):
        traces = [
            _make_trace([], pool_success={'a': True, 'b': True}, is_success=True),
            _make_trace([], pool_success={'a': True, 'b': False}, is_success=False),
            _make_trace([], pool_success={'a': False, 'b': False}, is_success=False),
        ]
        results = compute_bb(traces, 'custom', success_n=2, success_op='>=')
        patterns = [r['pattern'] for r in results['pattern_table']]
        assert '≥2' in patterns
        assert '<2' in patterns
        assert len(results['pattern_table']) == 2

    def test_empty(self):
        results = compute_bb([], 'count')
        assert results['pattern_table'] == []


class TestComputeAB:
    def test_basic(self):
        traces = [
            _make_trace([_make_event('a', 'early_hit')], pool_success={'a': True}, is_success=True),
            _make_trace([_make_event('a', 'early_hit')], pool_success={'a': True}, is_success=True),
            _make_trace([_make_event('a', 'early_hit')], pool_success={'a': False}, is_success=False),
            _make_trace([_make_event('a', 'miss')], pool_success={'a': True}, is_success=True),
        ]
        results = compute_ab(traces, 'sequence', 'count')
        assert len(results) == 2

        early_hit_row = next(r for r in results if r['event_pattern'] == ['early_hit'])
        assert early_hit_row['count'] == 3
        assert early_hit_row['success_count'] == 2
        assert early_hit_row['overall_success_prob'] == pytest.approx(2 / 3)


class TestComputeBA:
    def test_basic(self):
        traces = [
            _make_trace([_make_event('a', 'early_hit')], pool_success={'a': True}, is_success=True),
            _make_trace([_make_event('a', 'early_hit')], pool_success={'a': True}, is_success=True),
            _make_trace([_make_event('a', 'miss')], pool_success={'a': False}, is_success=False),
        ]
        results = compute_ba(traces, 'sequence')
        assert len(results) == 2

        early_hit_row = next(r for r in results if r['event_pattern'] == ['early_hit'])
        assert early_hit_row['p_given_success'] == pytest.approx(1.0)
        assert early_hit_row['p_given_failure'] == pytest.approx(0.0)

        miss_row = next(r for r in results if r['event_pattern'] == ['miss'])
        assert miss_row['p_given_success'] == pytest.approx(0.0)
        assert miss_row['p_given_failure'] == pytest.approx(1.0)
