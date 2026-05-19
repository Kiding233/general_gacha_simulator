import pytest
from gacha_simulator.core.strategy import (
    Strategy, FixedCountStrategy, TargetHuntingStrategy, CompositeStrategy
)
from gacha_simulator.core.action import DrawAction, WaitAction
from gacha_simulator.core.state import GachaState
from gacha_simulator.core.stop_condition import FixedActionCountCondition
from gacha_simulator.core.target_card import TargetCardSet


def test_fixed_count_strategy():
    state = GachaState(resources={'draw_resource': 1000})
    strategy = FixedCountStrategy(count=10)
    stop = FixedActionCountCondition(max_actions=10)
    pools = []

    action = strategy.select_action(state, [], pools, [], TargetCardSet([]), stop)
    assert isinstance(action, WaitAction)

    history = [None] * 10
    action = strategy.select_action(state, history, pools, [], TargetCardSet([]), stop)
    assert action.duration == 0


def test_target_hunting_strategy():
    state = GachaState(resources={'draw_resource': 160})
    strategy = TargetHuntingStrategy(target_pool_ids=['standard'])
    pools = []
    from gacha_simulator.core.pool import Pool, Reward
    pools.append(Pool('standard', 'Standard', {'draw_resource': 160}, [(Reward('r1', 'R1'), 1.0)]))

    action = strategy.select_action(state, [], pools, [], TargetCardSet([]), FixedActionCountCondition(100))
    assert isinstance(action, DrawAction)
    assert action.pool_id == 'standard'
