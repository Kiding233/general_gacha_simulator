from gacha_simulator.core.worst_impact import (
    ConditionalResourceDistribution,
    WorstImpactResult,
)


def _check_success_from_counts(obtained, target_specs):
    if not target_specs:
        return True
    for card_id, needed in target_specs.items():
        if obtained.get(card_id, 0) < needed:
            return False
    return True


def test_check_success_from_counts_all_obtained():
    assert _check_success_from_counts(
        {'char_a': 1, 'char_b': 2}, {'char_a': 1, 'char_b': 2}
    ) is True


def test_check_success_from_counts_partial():
    assert _check_success_from_counts(
        {'char_a': 1, 'char_b': 0}, {'char_a': 1, 'char_b': 1}
    ) is False


def test_check_success_from_counts_empty_targets():
    assert _check_success_from_counts({'char_a': 1}, {}) is True


def test_check_success_from_counts_missing_card():
    assert _check_success_from_counts(
        {'char_a': 1}, {'char_b': 1}
    ) is False


def test_conditional_resource_distribution():
    simulation_results = [
        {
            'card_counts': {'char_a': 1, 'char_b': 1},
            'final_resources': {'draw_resource': 1000},
        },
        {
            'card_counts': {'char_a': 0, 'char_b': 1},
            'final_resources': {'draw_resource': 200},
        },
        {
            'card_counts': {'char_a': 1, 'char_b': 1},
            'final_resources': {'draw_resource': 800},
        },
    ]
    target_specs = {'char_a': 1, 'char_b': 1}

    def checker(r):
        return _check_success_from_counts(r.get('card_counts', {}), target_specs)

    dist = ConditionalResourceDistribution(simulation_results, checker)

    assert len(dist.success_resources) == 2
    assert len(dist.failure_resources) == 1
    assert dist.success_resources == [1000, 800]
    assert dist.failure_resources == [200]


def test_conditional_distribution_all_condition():
    simulation_results = [
        {'card_counts': {'a': 1}, 'final_resources': {'draw_resource': 1000}},
        {'card_counts': {'a': 0}, 'final_resources': {'draw_resource': 200}},
    ]
    target_specs = {'a': 1}

    def checker(r):
        return _check_success_from_counts(r.get('card_counts', {}), target_specs)

    dist = ConditionalResourceDistribution(simulation_results, checker)

    all_dist = dist.get_conditional_distribution('all')
    assert all_dist.n == 2
    assert all_dist.mean() == 600.0


def test_worst_case_resource_failure():
    simulation_results = [
        {'card_counts': {'a': 1}, 'final_resources': {'draw_resource': 1000}},
        {'card_counts': {'a': 0}, 'final_resources': {'draw_resource': 200}},
        {'card_counts': {'a': 0}, 'final_resources': {'draw_resource': 100}},
    ]
    target_specs = {'a': 1}

    def checker(r):
        return _check_success_from_counts(r.get('card_counts', {}), target_specs)

    dist = ConditionalResourceDistribution(simulation_results, checker)
    worst = dist.get_worst_case_resource('failure', 0.5)
    assert worst == 150.0


def test_worst_impact_result_dataclass():
    result = WorstImpactResult(
        worst_resource=500.0,
        pity_coverage=0.35,
        pool_distribution={0: 0.3, 1: 0.5, 2: 0.2},
        expected_pools=0.9,
    )
    assert result.worst_resource == 500.0
    assert result.pity_coverage == 0.35
    assert result.expected_pools == 0.9


def test_worst_impact_result_get_p_ge():
    result = WorstImpactResult(
        worst_resource=500.0,
        pity_coverage=0.35,
        pool_distribution={0: 0.1, 1: 0.35, 2: 0.4, 3: 0.15},
        expected_pools=1.6,
    )
    assert abs(result.get_p_ge(0) - 1.0) < 1e-9
    assert abs(result.get_p_ge(1) - 0.9) < 1e-9
    assert abs(result.get_p_ge(2) - 0.55) < 1e-9
    assert abs(result.get_p_ge(3) - 0.15) < 1e-9
    assert abs(result.get_p_ge(4) - 0.0) < 1e-9


def test_worst_impact_result_max_consecutive_at_threshold():
    result = WorstImpactResult(
        worst_resource=500.0,
        pity_coverage=0.35,
        pool_distribution={0: 0.1, 1: 0.35, 2: 0.4, 3: 0.15},
        expected_pools=1.6,
    )
    assert result.get_max_consecutive_at_threshold(1.0) == 0
    assert result.get_max_consecutive_at_threshold(0.9) == 1
    assert result.get_max_consecutive_at_threshold(0.5) == 2
    assert result.get_max_consecutive_at_threshold(0.1) == 3


def test_worst_impact_result_empty_distribution():
    result = WorstImpactResult(
        worst_resource=0.0,
        pity_coverage=0.0,
    )
    assert result.get_p_ge(0) == 0.0
    assert result.get_p_ge(1) == 0.0
    assert result.get_max_consecutive_at_threshold(0.5) == 0
