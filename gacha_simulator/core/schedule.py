from dataclasses import dataclass
from typing import List, Optional, Dict, Set


@dataclass
class PoolSchedule:
    pool_id: str
    available_from: float
    available_until: float
    rerun_of: Optional[str] = None

    def is_available_at(self, time: float) -> bool:
        return self.available_from <= time <= self.available_until

    def is_rerun(self) -> bool:
        return self.rerun_of is not None


class PoolScheduleManager:
    def __init__(self, schedules: List[PoolSchedule]):
        self.schedules = schedules
        self._build_index()

    def _build_index(self):
        self._pool_schedules: Dict[str, List[PoolSchedule]] = {}
        for s in self.schedules:
            if s.pool_id not in self._pool_schedules:
                self._pool_schedules[s.pool_id] = []
            self._pool_schedules[s.pool_id].append(s)

    def get_pools_at_time(self, time: float) -> List[str]:
        return [s.pool_id for s in self.schedules if s.is_available_at(time)]

    def get_future_schedules(
        self, from_time: float, lookahead: Optional[float] = None
    ) -> List[PoolSchedule]:
        future = [s for s in self.schedules if s.available_from >= from_time]
        if lookahead is not None:
            future = [s for s in future if s.available_from < from_time + lookahead]
        return sorted(future, key=lambda s: s.available_from)

    def get_schedules_for_pool(self, pool_id: str) -> List[PoolSchedule]:
        return self._pool_schedules.get(pool_id, [])

    def is_rerun(self, pool_id: str) -> bool:
        schedules = self._pool_schedules.get(pool_id, [])
        return any(s.is_rerun() for s in schedules)

    def get_original_pool(self, pool_id: str) -> Optional[str]:
        schedules = self._pool_schedules.get(pool_id, [])
        for s in schedules:
            if s.rerun_of:
                return s.rerun_of
        return None

    def get_all_pool_ids(self) -> Set[str]:
        return set(self._pool_schedules.keys())
