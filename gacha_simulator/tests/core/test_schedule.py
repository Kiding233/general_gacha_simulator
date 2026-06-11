from gacha_simulator.core.schedule import PoolSchedule, PoolScheduleManager


def test_pool_schedule():
    schedule = PoolSchedule('pool1', available_from=0, available_until=100)
    assert schedule.is_available_at(50) is True
    assert schedule.is_available_at(150) is False


def test_schedule_manager():
    schedules = [
        PoolSchedule('pool1', 0, 100),
        PoolSchedule('pool2', 50, 150),
        PoolSchedule('pool3', 200, 300),
    ]
    manager = PoolScheduleManager(schedules)
    assert manager.get_pools_at_time(75) == ['pool1', 'pool2']
    future = manager.get_future_schedules(100)
    assert len(future) == 1
    assert future[0].pool_id == 'pool3'
