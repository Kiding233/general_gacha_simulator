from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, List, Dict, Set, Tuple

if TYPE_CHECKING:
    from .state import GachaState
    from .info_vector import InfoVector
    from ..service.gacha_service import SimulationStats


class StopCondition(ABC):
    @abstractmethod
    def check(self, state: 'GachaState', history: List['InfoVector'], 
              stats: Optional['SimulationStats'] = None) -> bool:
        pass

    @abstractmethod
    def description(self) -> str:
        pass


class FixedActionCountCondition(StopCondition):
    def __init__(self, max_actions: int):
        self.max_actions = max_actions

    def check(self, state: 'GachaState', history: List['InfoVector'],
              stats: Optional['SimulationStats'] = None) -> bool:
        if stats:
            return stats.total_actions >= self.max_actions
        return len(history) >= self.max_actions

    def description(self) -> str:
        return f"抽满 {self.max_actions} 次后停止"


class ResourceThresholdCondition(StopCondition):
    def __init__(self, resource: str, threshold: float, operator: str = '<='):
        self.resource = resource
        self.threshold = threshold
        self.operator = operator

    def check(self, state: 'GachaState', history: List['InfoVector'],
              stats: Optional['SimulationStats'] = None) -> bool:
        current = state.resources.get(self.resource, 0)
        if self.operator == '<=':
            return current <= self.threshold
        elif self.operator == '>=':
            return current >= self.threshold
        elif self.operator == '==':
            return current == self.threshold
        return False

    def description(self) -> str:
        return f"资源 {self.resource} {self.operator} {self.threshold}"


class TargetAcquiredCondition(StopCondition):
    def __init__(self, target_id: str, quantity: int = 1):
        self.target_id = target_id
        self.quantity = quantity

    def check(self, state: 'GachaState', history: List['InfoVector'],
              stats: Optional['SimulationStats'] = None) -> bool:
        if stats:
            return stats.card_counts.get(self.target_id, 0) >= self.quantity
        count = sum(1 for iv in history if iv.card_id == self.target_id)
        return count >= self.quantity

    def description(self) -> str:
        return f"获得 {self.quantity} 张 {self.target_id}"


class LastDrawCardCondition(StopCondition):
    def __init__(self, card_id: str):
        self.card_id = card_id

    def check(self, state: 'GachaState', history: List['InfoVector'],
              stats: Optional['SimulationStats'] = None) -> bool:
        if stats:
            return stats.last_draw_card_id == self.card_id
        if not history:
            return False
        return history[-1].card_id == self.card_id

    def description(self) -> str:
        return f"抽到 {self.card_id} 后停止"


class TimeLimitCondition(StopCondition):
    def __init__(self, max_time: float):
        self.max_time = max_time

    def check(self, state: 'GachaState', history: List['InfoVector'],
              stats: Optional['SimulationStats'] = None) -> bool:
        return state.real_time >= self.max_time

    def description(self) -> str:
        return f"现实时间达到 {self.max_time} 秒"


class CompositeStopCondition(StopCondition):
    def __init__(self, conditions: list, mode: str = 'any'):
        self.conditions = conditions
        self.mode = mode

    def check(self, state: 'GachaState', history: List['InfoVector'],
              stats: Optional['SimulationStats'] = None) -> bool:
        if self.mode == 'any':
            return any(c.check(state, history, stats) for c in self.conditions)
        else:
            return all(c.check(state, history, stats) for c in self.conditions)

    def description(self) -> str:
        ops = ' 或 ' if self.mode == 'any' else ' 且 '
        return ops.join(c.description() for c in self.conditions)


class PoolFailedCondition(StopCondition):
    def __init__(self, pool_end_times: List[Tuple[str, float]],
                 featured_ids_map: Dict[str, Set[str]]):
        self.pool_end_times = sorted(pool_end_times, key=lambda x: x[1])
        self.featured_ids_map = featured_ids_map
        self._last_failed_pool_end: Optional[float] = None

    def check(self, state: 'GachaState', history: List['InfoVector'],
              stats: Optional['SimulationStats'] = None) -> bool:
        current_time = state.real_time
        card_counts = stats.card_counts if stats else {}
        for pool_id, end_time in self.pool_end_times:
            if current_time <= end_time:
                break
            featured = self.featured_ids_map.get(pool_id, set())
            if not featured:
                continue
            success = all(card_counts.get(fid, 0) >= 1 for fid in featured)
            if not success:
                return True
        return False

    def description(self) -> str:
        return "某池子结束但未获得目标卡"
