from gacha_simulator.core.stop_condition import (
    FixedActionCountCondition, ResourceThresholdCondition,
    TargetAcquiredCondition, CompositeStopCondition
)
from gacha_simulator.core.state import GachaState


def test_fixed_action_count():
    cond = FixedActionCountCondition(max_actions=10)
    state = GachaState()
    assert cond.check(state, []) is False
    assert cond.check(state, [None] * 10) is True


def test_resource_threshold():
    cond = ResourceThresholdCondition('draw_resource', 100, '<=')
    state = GachaState(resources={'draw_resource': 50})
    assert cond.check(state, []) is True
    state.resources['draw_resource'] = 200
    assert cond.check(state, []) is False


def test_target_acquired():
    cond = TargetAcquiredCondition('character_a', quantity=2)
    state = GachaState()
    from gacha_simulator.core.info_vector import InfoVector
    history = [
        InfoVector('draw', 'character_a', 'p1', action_index=0, session_id='s1'),
        InfoVector('draw', 'character_b', 'p1', action_index=1, session_id='s1'),
    ]
    assert cond.check(state, history) is False
    history.append(InfoVector('draw', 'character_a', 'p1', action_index=2, session_id='s1'))
    assert cond.check(state, history) is True


def test_composite_any():
    cond1 = FixedActionCountCondition(5)
    cond2 = ResourceThresholdCondition('draw_resource', 0, '<=')
    composite = CompositeStopCondition([cond1, cond2], mode='any')
    state = GachaState(resources={'draw_resource': 0})
    assert composite.check(state, []) is True
