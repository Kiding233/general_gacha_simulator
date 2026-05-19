import pytest
from gacha_simulator.generator.target_generator import RuleBasedTargetGenerator
from gacha_simulator.core.pool import Pool, Reward
from gacha_simulator.core.schedule import PoolSchedule
from gacha_simulator.core.target_card import TargetCardSet


def test_rule_based_generator():
    pools = [
        Pool('p1', 'Pool 1', {}, [(Reward('r1', 'R1'), 1.0), (Reward('r2', 'R2'), 1.0)])
    ]
    gen = RuleBasedTargetGenerator([
        {'type': 'all_in_pool', 'pool_id': 'p1', 'quantity': 1}
    ])
    result = gen.generate([], pools)
    assert len(result.targets) == 2
    assert result.get_quantity_needed('r1') == 1
