from gacha_simulator.core.strategy import (
    FixedCountStrategy, TargetHuntingStrategy, StrategyContext
)
from gacha_simulator.core.action import DrawAction, WaitAction
from gacha_simulator.core.state import GachaState
from gacha_simulator.core.stop_condition import FixedActionCountCondition
from gacha_simulator.core.target_card import TargetCardSet
from gacha_simulator.core.pool import Pool, Reward


def _make_ctx(state, current_pools, total_draws=0, acquired=None):
    return StrategyContext(
        state=state,
        current_pools=current_pools,
        all_pools=current_pools,
        future_schedules=[],
        target_cards=TargetCardSet([]),
        stop_condition=FixedActionCountCondition(100),
        total_draws=total_draws,
        acquired=acquired or {},
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
    assert isinstance(action2, WaitAction)
    assert action2.duration == 0


def test_target_hunting_strategy():
    state = GachaState(resources={'draw_resource': 160})
    strategy = TargetHuntingStrategy(target_pool_ids=['standard'])
    pools = [Pool('standard', 'Standard', [{'draw_resource': 160}], [(Reward('r1', 'R1'), 1.0)])]

    ctx = _make_ctx(state, pools)
    action = strategy.select_action(ctx)
    assert isinstance(action, DrawAction)
    assert action.pool_id == 'standard'
