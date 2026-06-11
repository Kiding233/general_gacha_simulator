from gacha_simulator.core.pool import Pool, Reward, parse_cost_string


def test_pool_draw_returns_reward():
    r1 = Reward(id='r1', name='Reward 1')
    r2 = Reward(id='r2', name='Reward 2')
    pool = Pool(
        id='test_pool',
        name='Test Pool',
        cost=parse_cost_string('draw_resource:160'),
        rewards=[(r1, 0.6), (r2, 0.4)],
    )
    result = pool.draw()
    assert result in [r1, r2]


def test_exchange_pool_returns_first_reward():
    r = Reward(id='exchange', name='Exchange')
    pool = Pool(
        id='exchange_pool',
        name='Exchange Pool',
        cost=parse_cost_string('stardust:75'),
        rewards=[(r, 1.0)],
        is_exchange=True,
    )
    result = pool.draw()
    assert result == r


def test_pool_availability():
    pool = Pool(
        id='limited_pool',
        name='Limited Pool',
        cost=parse_cost_string('draw_resource:160'),
        rewards=[],
        available_from=0,
        available_until=100,
    )
    assert pool.is_available_at(50) is True
    assert pool.is_available_at(150) is False
    assert pool.is_available_at(-10) is False
