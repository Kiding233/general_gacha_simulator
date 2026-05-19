from abc import ABC, abstractmethod
from typing import Dict, List, Optional, TYPE_CHECKING
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

    @classmethod
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


class SmartStrategy(Strategy):
    lookahead = None

    def __init__(self, target_set: TargetCardSet, all_pools: Optional[List['Pool']] = None):
        self.target_set = target_set
        self.all_pools = all_pools or []
        self.acquired: Dict[str, int] = {}
        self._pool_to_targets: Dict[str, list] = {}
        for t in target_set.targets:
            for pid in t.pool_ids:
                if pid not in self._pool_to_targets:
                    self._pool_to_targets[pid] = []
                self._pool_to_targets[pid].append(t)

    @classmethod
    def description(cls) -> str:
        return "按需追卡：优先兑换→按目标追卡→等待下一个池"

    def _pool_needs_target(self, pool_id: str) -> bool:
        targets = self._pool_to_targets.get(pool_id, [])
        for t in targets:
            if self.acquired.get(t.card_id, 0) < t.quantity_needed:
                return True
        return False

    def _get_needed_card_exchange(self, state: 'GachaState') -> Optional[str]:
        for t in self.target_set.targets:
            if self.acquired.get(t.card_id, 0) >= t.quantity_needed:
                continue
            for pool in self.all_pools:
                if pool.is_exchange and pool.exchange_card_id == t.card_id:
                    if pool.is_available_at(state.real_time) and state.can_afford(pool.cost):
                        return pool.id
        return None

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

        exchange_pool_id = self._get_needed_card_exchange(state)
        if exchange_pool_id:
            return DrawAction(pool_id=exchange_pool_id)

        for pool in current_pools:
            if not pool.is_exchange and self._pool_needs_target(pool.id) and state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)

        wait_time = 86400
        for pool in current_pools:
            if hasattr(pool, 'available_until') and pool.available_until and pool.available_until > state.real_time:
                wait_time = min(wait_time, pool.available_until - state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)

    def observe(self, iv: 'InfoVector'):
        if iv.action_type == 'draw' and iv.card_id:
            self.acquired[iv.card_id] = self.acquired.get(iv.card_id, 0) + 1
