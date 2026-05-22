import pytest
from gacha_simulator.core.strategy import (
    Strategy, FixedCountStrategy, TargetHuntingStrategy, CompositeStrategy,
    StrategyContext,
)
from gacha_simulator.core.action import DrawAction, WaitAction
from gacha_simulator.core.state import GachaState
from gacha_simulator.core.stop_condition import FixedActionCountCondition
from gacha_simulator.core.target_card import TargetCardSet


def _make_ctx(state, pools, total_draws=0, stop_condition=None):
    return StrategyContext(
        state=state,
        current_pools=pools,
        all_pools=pools,
        future_schedules=[],
        target_cards=TargetCardSet([]),
        stop_condition=stop_condition or FixedActionCountCondition(100),
        total_draws=total_draws,
    )


def test_fixed_count_strategy():
    state = GachaState(resources={'draw_resource': 1000})
    strategy = FixedCountStrategy(count=10)
    pools = []

    ctx = _make_ctx(state, pools, total_draws=0)
    action = strategy.select_action(ctx)
    assert isinstance(action, WaitAction)

    ctx2 = _make_ctx(state, pools, total_draws=10)
    action2 = strategy.select_action(ctx2)
    assert action2.duration == 0


def test_target_hunting_strategy():
    state = GachaState(resources={'draw_resource': 160})
    strategy = TargetHuntingStrategy(target_pool_ids=['standard'])
    from gacha_simulator.core.pool import Pool, Reward
    pools = [Pool('standard', 'Standard', {'draw_resource': 160}, [(Reward('r1', 'R1'), 1.0)])]

    ctx = _make_ctx(state, pools)
    action = strategy.select_action(ctx)
    assert isinstance(action, DrawAction)
    assert action.pool_id == 'standard'
