from abc import ABC, abstractmethod
from typing import List, Dict, Any
from ..core.schedule import PoolSchedule, PoolScheduleManager


class PoolScheduleGenerator(ABC):
    @abstractmethod
    def generate(self, config: Dict[str, Any], pool_ids: List[str]) -> List[PoolSchedule]:
        pass


class UserDefinedScheduleGenerator(PoolScheduleGenerator):
    def __init__(self, schedules: List[PoolSchedule]):
        self.schedules = schedules

    def generate(self, config: Dict[str, Any], pool_ids: List[str]) -> List[PoolSchedule]:
        return self.schedules


class PeriodicScheduleGenerator(PoolScheduleGenerator):
    def __init__(self, period: float, active_duration: float, start_offset: float = 0):
        self.period = period
        self.active_duration = active_duration
        self.start_offset = start_offset

    def generate(self, config: Dict[str, Any], pool_ids: List[str]) -> List[PoolSchedule]:
        schedules = []
        total_duration = config.get('total_duration', 86400 * 30)
        for pool_id in pool_ids:
            t = self.start_offset
            while t < total_duration:
                schedules.append(PoolSchedule(
                    pool_id=pool_id,
                    available_from=t,
                    available_until=t + self.active_duration,
                ))
                t += self.period
        return schedules
