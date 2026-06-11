from gacha_simulator.generator.schedule_generator import PeriodicScheduleGenerator
from gacha_simulator.core.schedule import PoolSchedule


def test_periodic_schedule():
    gen = PeriodicScheduleGenerator(period=100, active_duration=50, start_offset=0)
    schedules = gen.generate({'total_duration': 300}, ['pool1', 'pool2'])
    assert len(schedules) == 6
    assert all(isinstance(s, PoolSchedule) for s in schedules)
