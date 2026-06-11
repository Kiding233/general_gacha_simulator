from gacha_simulator.core.state import GachaState
from gacha_simulator.core.pool import Pool, parse_cost_string


def test_can_afford_dict():
    state = GachaState(resources={'draw_resource': 160, 'acronym': 0})
    assert state.can_afford({'draw_resource': 160}) is True
    assert state.can_afford({'draw_resource': 161}) is False
    assert state.can_afford({'acronym': 1}) is False


def test_can_afford_pool_cost():
    state = GachaState(resources={'draw_resource': 160, 'char_resource': 100})
    cost = parse_cost_string('draw_resource:160')
    assert state.can_afford(cost) is True
    cost2 = parse_cost_string('draw_resource:200')
    assert state.can_afford(cost2) is False


def test_can_afford_or_cost():
    state = GachaState(resources={'draw_resource': 0, 'char_resource': 200})
    cost = parse_cost_string('draw_resource:160, char_resource:160')
    assert state.can_afford(cost) is True
    state2 = GachaState(resources={'draw_resource': 0, 'char_resource': 0})
    assert state2.can_afford(cost) is False


def test_can_afford_and_cost():
    state = GachaState(resources={'draw_resource': 160, 'char_resource': 100})
    cost = parse_cost_string('draw_resource:160&char_resource:100')
    assert state.can_afford(cost) is True
    state2 = GachaState(resources={'draw_resource': 160, 'char_resource': 0})
    assert state2.can_afford(cost) is False


def test_spend_dict():
    state = GachaState(resources={'draw_resource': 1000})
    spent = state.spend({'draw_resource': 160})
    assert spent == {'draw_resource': 160}
    assert state.resources['draw_resource'] == 840


def test_spend_pool_cost_or():
    state = GachaState(resources={'draw_resource': 0, 'char_resource': 200})
    cost = parse_cost_string('draw_resource:160, char_resource:160')
    spent = state.spend(cost)
    assert spent == {'char_resource': 160}
    assert state.resources['char_resource'] == 40


def test_spend_pool_cost_and():
    state = GachaState(resources={'draw_resource': 200, 'char_resource': 100})
    cost = parse_cost_string('draw_resource:160&char_resource:50')
    spent = state.spend(cost)
    assert spent == {'draw_resource': 160, 'char_resource': 50}
    assert state.resources['draw_resource'] == 40
    assert state.resources['char_resource'] == 50


def test_spend_insufficient():
    state = GachaState(resources={'draw_resource': 100})
    spent = state.spend({'draw_resource': 160})
    assert spent is None
    assert state.resources['draw_resource'] == 100


def test_gain():
    state = GachaState(resources={'draw_resource': 1000})
    state.gain({'draw_resource': 100})
    assert state.resources['draw_resource'] == 1100


def test_get_available_pools():
    pool1 = Pool('p1', 'Pool 1', [], [], available_from=0, available_until=100)
    pool2 = Pool('p2', 'Pool 2', [], [], available_from=50, available_until=200)
    pool3 = Pool('p3', 'Pool 3', [], [], available_from=150, available_until=250)
    state = GachaState(real_time=75)
    available = state.get_available_pools([pool1, pool2, pool3])
    assert len(available) == 2
    assert available[0].id == 'p1'
    assert available[1].id == 'p2'


def test_clone():
    state = GachaState(resources={'a': 1}, pity_counters={'p1': 5}, real_time=100)
    clone = state.clone()
    assert clone.resources == {'a': 1}
    assert clone.pity_counters == {'p1': 5}
    assert clone.real_time == 100
    clone.resources['a'] = 999
    assert state.resources['a'] == 1
