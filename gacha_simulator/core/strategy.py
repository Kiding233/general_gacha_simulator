from abc import ABC, abstractmethod
from typing import List, Optional, TYPE_CHECKING
from .action import Action
from .schedule import PoolSchedule
from .target_card import TargetCardSet

if TYPE_CHECKING:
    from .state import GachaState
    from .info_vector import InfoVector
    from .pool import Pool
    from .stop_condition import StopCondition


class Strategy(ABC):
    lookahead: Optional[float] = None

    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @abstractmethod
    def description(cls) -> str:
        return ""

    @abstractmethod
    def select_action(
        self,
        state: 'GachaState',
        history: List['InfoVector'],
        current_pools: List['Pool'],
        future_schedules: List[PoolSchedule],
        target_cards: TargetCardSet,
        stop_condition: 'StopCondition',
    ) -> Action:
        pass


class FixedCountStrategy(Strategy):
    def __init__(self, count: int):
        self.count = count

    @classmethod
    def description(cls) -> str:
        return "抽指定次数后停止"

    def select_action(
        self,
        state: 'GachaState',
        history: List['InfoVector'],
        current_pools: List['Pool'],
        future_schedules: List[PoolSchedule],
        target_cards: TargetCardSet,
        stop_condition: 'StopCondition',
    ) -> Action:
        from .action import WaitAction
        if len(history) >= self.count:
            return WaitAction(duration=0)
        if not current_pools:
            return WaitAction(duration=1)
        from .action import DrawAction
        return DrawAction(pool_id=current_pools[0].id)


class TargetHuntingStrategy(Strategy):
    def __init__(self, target_pool_ids: List[str]):
        self.target_pool_ids = target_pool_ids

    @classmethod
    def description(cls) -> str:
        return "指定池抽卡：只从指定池子抽卡"

    def select_action(
        self,
        state: 'GachaState',
        history: List['InfoVector'],
        current_pools: List['Pool'],
        future_schedules: List[PoolSchedule],
        target_cards: TargetCardSet,
        stop_condition: 'StopCondition',
    ) -> Action:
        from .action import DrawAction, WaitAction
        target_pools = [p for p in current_pools if p.id in self.target_pool_ids]
        for pool in target_pools:
            if state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)
        return WaitAction(duration=3600)


class CompositeStrategy(Strategy):
    def __init__(self, strategies: List[Strategy], mode: str = 'first_valid'):
        self.strategies = strategies
        self.mode = mode

    @classmethod
    def description(cls) -> str:
        return "组合多个策略"

    def select_action(
        self,
        state: 'GachaState',
        history: List['InfoVector'],
        current_pools: List['Pool'],
        future_schedules: List[PoolSchedule],
        target_cards: TargetCardSet,
        stop_condition: 'StopCondition',
    ) -> Action:
        for strategy in self.strategies:
            action = strategy.select_action(
                state, history, current_pools, future_schedules, target_cards, stop_condition
            )
            if self.mode == 'first_valid' and action is not None:
                return action
        from .action import WaitAction
        return WaitAction(duration=0)
