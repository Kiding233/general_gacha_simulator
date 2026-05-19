import pytest
from gacha_simulator.core.action import Action, DrawAction, WaitAction


def test_draw_action_repr():
    action = DrawAction(pool_id='standard')
    assert "DrawAction" in repr(action)
    assert "standard" in repr(action)


def test_wait_action_repr():
    action = WaitAction(duration=3600)
    assert "WaitAction" in repr(action)
    assert "3600" in repr(action)


def test_action_type():
    draw = DrawAction(pool_id='test')
    wait = WaitAction(duration=100)
    assert draw.type == 'draw'
    assert wait.type == 'wait'
