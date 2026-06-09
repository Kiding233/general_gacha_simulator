from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional, Dict, Set, TYPE_CHECKING

from .action import Action
from .schedule import PoolSchedule
from .target_card import TargetCardSet

if TYPE_CHECKING:
    from .state import GachaState
    from .pool import Pool
    from .stop_condition import StopCondition
    from .pity import PityEngine, PityState


@dataclass
class StrategyContext:
    state: 'GachaState'
    current_pools: List['Pool']
    all_pools: List['Pool']
    future_schedules: List[PoolSchedule]
    target_cards: TargetCardSet
    stop_condition: 'StopCondition'
    _pity_engine: Optional['PityEngine'] = field(default=None, repr=False)
    _pity_state: Optional['PityState'] = field(default=None, repr=False)
    acquired: Dict[str, int] = field(default_factory=dict)
    pool_draw_counts: Dict[str, int] = field(default_factory=dict)
    total_draws: int = 0
    last_draw_pity_triggered: bool = False
    ssr_ids: Set[str] = field(default_factory=set)
    _pity_cache: Dict[str, Dict[str, float]] = field(default_factory=dict, repr=False)

    def get_pity_probabilities(self, pool_id: str) -> Dict[str, float]:
        if self._pity_engine is None:
            return {}
        cached = self._pity_cache.get(pool_id)
        if cached is not None:
            return cached
        pool = next((p for p in self.current_pools if p.id == pool_id), None)
        if pool is None or pool.is_exchange:
            return {}
        probs = {r.id: p for r, p in pool.rewards}
        result = self._pity_engine.get_probabilities(pool_id, self._pity_state, probs)
        self._pity_cache[pool_id] = result
        return result


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
    def select_action(self, ctx: StrategyContext) -> Action:
        pass


class SmartStrategy(Strategy):
    lookahead = None

    def __init__(self):
        self._pool_to_targets: Dict[str, list] = {}
        self._last_target_cards_id: int = 0

    @classmethod
    def description(cls) -> str:
        return "按需追卡：优先兑换→按目标追卡→等待下一个池"

    def _ensure_pool_to_targets(self, ctx: StrategyContext):
        tc_id = id(ctx.target_cards)
        if tc_id != self._last_target_cards_id:
            self._pool_to_targets.clear()
            for t in ctx.target_cards.targets:
                for pid in t.pool_ids:
                    if pid not in self._pool_to_targets:
                        self._pool_to_targets[pid] = []
                    self._pool_to_targets[pid].append(t)
            self._last_target_cards_id = tc_id

    def _pool_needs_target(self, pool_id: str, ctx: StrategyContext) -> bool:
        self._ensure_pool_to_targets(ctx)
        for t in self._pool_to_targets.get(pool_id, []):
            if ctx.acquired.get(t.card_id, 0) < t.quantity_needed:
                return True
        return False

    def _get_needed_card_exchange(self, ctx: StrategyContext) -> Optional[str]:
        for t in ctx.target_cards.targets:
            if ctx.acquired.get(t.card_id, 0) >= t.quantity_needed:
                continue
            for pool in ctx.all_pools:
                if pool.is_exchange and pool.exchange_card_id == t.card_id:
                    if pool.is_available_at(ctx.state.real_time) and ctx.state.can_afford(pool.cost):
                        return pool.id
        return None

    def select_action(self, ctx: StrategyContext) -> Action:
        from .action import DrawAction, WaitAction

        exchange_pool_id = self._get_needed_card_exchange(ctx)
        if exchange_pool_id:
            return DrawAction(pool_id=exchange_pool_id)

        for pool in ctx.current_pools:
            if not pool.is_exchange and self._pool_needs_target(pool.id, ctx) and ctx.state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)

        wait_time = 86400
        for pool in ctx.current_pools:
            if hasattr(pool, 'available_until') and pool.available_until and pool.available_until > ctx.state.real_time:
                wait_time = min(wait_time, pool.available_until - ctx.state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)


class PoolQuotaStrategy(Strategy):
    lookahead = None

    def __init__(self, pool_quotas: Optional[Dict[str, int]] = None):
        self.pool_quotas = pool_quotas or {}

    @classmethod
    def description(cls) -> str:
        return "指定池配额：在指定池子抽指定数量后切换"

    def _pool_needs_target(self, pool_id: str, ctx: StrategyContext) -> bool:
        for t in ctx.target_cards.targets:
            if pool_id in t.pool_ids and ctx.acquired.get(t.card_id, 0) < t.quantity_needed:
                return True
        return False

    def select_action(self, ctx: StrategyContext) -> Action:
        from .action import DrawAction, WaitAction

        for t in ctx.target_cards.targets:
            if ctx.acquired.get(t.card_id, 0) >= t.quantity_needed:
                continue
            for pool in ctx.all_pools:
                if pool.is_exchange and pool.exchange_card_id == t.card_id:
                    if pool.is_available_at(ctx.state.real_time) and ctx.state.can_afford(pool.cost):
                        return DrawAction(pool_id=pool.id)

        for pool in ctx.current_pools:
            if pool.is_exchange or not ctx.state.can_afford(pool.cost):
                continue
            pid = pool.id
            quota = self.pool_quotas.get(pid)
            drawn = ctx.pool_draw_counts.get(pid, 0)
            if quota is None or drawn < quota:
                if self._pool_needs_target(pool.id, ctx):
                    return DrawAction(pool_id=pid)

        for pool in ctx.current_pools:
            if not pool.is_exchange and ctx.state.can_afford(pool.cost):
                pid = pool.id
                quota = self.pool_quotas.get(pid)
                drawn = ctx.pool_draw_counts.get(pid, 0)
                if quota is None or drawn < quota:
                    return DrawAction(pool_id=pid)

        wait_time = 86400
        for pool in ctx.current_pools:
            if hasattr(pool, 'available_until') and pool.available_until and pool.available_until > ctx.state.real_time:
                wait_time = min(wait_time, pool.available_until - ctx.state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)


class PityReserveStrategy(Strategy):
    lookahead = None

    def __init__(self, pity_threshold_pct: float = 80.0):
        self.pity_threshold_pct = pity_threshold_pct / 100.0

    @classmethod
    def description(cls) -> str:
        return "保底预留：只在大保底概率≥阈值时才抽卡"

    def _pool_needs_target(self, pool_id: str, ctx: StrategyContext) -> bool:
        for t in ctx.target_cards.targets:
            if pool_id in t.pool_ids and ctx.acquired.get(t.card_id, 0) < t.quantity_needed:
                return True
        return False

    def select_action(self, ctx: StrategyContext) -> Action:
        from .action import DrawAction, WaitAction

        for t in ctx.target_cards.targets:
            if ctx.acquired.get(t.card_id, 0) >= t.quantity_needed:
                continue
            for pool in ctx.all_pools:
                if pool.is_exchange and pool.exchange_card_id == t.card_id:
                    if pool.is_available_at(ctx.state.real_time) and ctx.state.can_afford(pool.cost):
                        return DrawAction(pool_id=pool.id)

        for pool in ctx.current_pools:
            if pool.is_exchange or not ctx.state.can_afford(pool.cost):
                continue
            if not self._pool_needs_target(pool.id, ctx):
                continue

            pool_probs = ctx.get_pity_probabilities(pool.id)
            if pool_probs:
                ssr_prob = sum(p for cid, p in pool_probs.items() if cid in ctx.ssr_ids)
                if ssr_prob >= self.pity_threshold_pct:
                    return DrawAction(pool_id=pool.id)
            else:
                return DrawAction(pool_id=pool.id)

        wait_time = 86400
        for pool in ctx.current_pools:
            if hasattr(pool, 'available_until') and pool.available_until and pool.available_until > ctx.state.real_time:
                wait_time = min(wait_time, pool.available_until - ctx.state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)


class StopOnTargetStrategy(Strategy):
    lookahead = None

    def __init__(self, stop_on_featured: bool = True, stop_on_any_target: bool = False):
        self.stop_on_featured = stop_on_featured
        self.stop_on_any_target = stop_on_any_target

    @classmethod
    def description(cls) -> str:
        return "目标即停：抽到当期up/目标卡就停止"

    def _pool_needs_target(self, pool_id: str, ctx: StrategyContext) -> bool:
        for t in ctx.target_cards.targets:
            if pool_id in t.pool_ids and ctx.acquired.get(t.card_id, 0) < t.quantity_needed:
                return True
        return False

    def select_action(self, ctx: StrategyContext) -> Action:
        from .action import DrawAction, WaitAction

        if self.stop_on_featured and ctx.last_draw_pity_triggered:
            return WaitAction(duration=0)
        if self.stop_on_any_target:
            for t in ctx.target_cards.targets:
                if ctx.acquired.get(t.card_id, 0) >= t.quantity_needed:
                    return WaitAction(duration=0)

        for t in ctx.target_cards.targets:
            if ctx.acquired.get(t.card_id, 0) >= t.quantity_needed:
                continue
            for pool in ctx.all_pools:
                if pool.is_exchange and pool.exchange_card_id == t.card_id:
                    if pool.is_available_at(ctx.state.real_time) and ctx.state.can_afford(pool.cost):
                        return DrawAction(pool_id=pool.id)

        for pool in ctx.current_pools:
            if not pool.is_exchange and self._pool_needs_target(pool.id, ctx) and ctx.state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)

        wait_time = 86400
        for pool in ctx.current_pools:
            if hasattr(pool, 'available_until') and pool.available_until and pool.available_until > ctx.state.real_time:
                wait_time = min(wait_time, pool.available_until - ctx.state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)


class FixedCountStrategy(Strategy):
    def __init__(self, count: int):
        self.count = count

    @classmethod
    def description(cls) -> str:
        return "抽指定次数后停止"

    def select_action(self, ctx: StrategyContext) -> Action:
        from .action import WaitAction, DrawAction
        if ctx.total_draws >= self.count:
            return WaitAction(duration=0)
        if not ctx.current_pools:
            return WaitAction(duration=1)
        return DrawAction(pool_id=ctx.current_pools[0].id)


class TargetHuntingStrategy(Strategy):
    def __init__(self, target_pool_ids: List[str]):
        self.target_pool_ids = target_pool_ids

    @classmethod
    def description(cls) -> str:
        return "指定池抽卡：只从指定池子抽卡"

    def select_action(self, ctx: StrategyContext) -> Action:
        from .action import DrawAction, WaitAction
        target_pools = [p for p in ctx.current_pools if p.id in self.target_pool_ids]
        for pool in target_pools:
            if ctx.state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)
        return WaitAction(duration=3600)


class NoDrawStrategy(Strategy):
    """不抽卡策略：始终等待，一次都不抽。用于计算不抽卡基线资源水平。"""

    @classmethod
    def description(cls) -> str:
        return "不抽卡：始终等待，用于计算基线资源水平"

    def select_action(self, ctx: StrategyContext) -> Action:
        from .action import WaitAction
        wait_time = 86400
        for pool in ctx.current_pools:
            if hasattr(pool, 'available_until') and pool.available_until and pool.available_until > ctx.state.real_time:
                wait_time = min(wait_time, pool.available_until - ctx.state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)


class CompositeStrategy(Strategy):
    def __init__(self, strategies: List[Strategy], mode: str = 'first_valid'):
        self.strategies = strategies
        self.mode = mode

    @classmethod
    def description(cls) -> str:
        return "组合多个策略"

    def select_action(self, ctx: StrategyContext) -> Action:
        for strategy in self.strategies:
            action = strategy.select_action(ctx)
            if self.mode == 'first_valid' and action is not None:
                return action
        from .action import WaitAction
        return WaitAction(duration=0)


STRATEGY_REGISTRY = {
    'smart': {
        'display_name': '按需追卡',
        'description': '优先兑换→按目标追卡→等待下一个池',
        'class': SmartStrategy,
        'params': {},
    },
    'pool_quota': {
        'display_name': '指定池配额',
        'description': '在指定池子抽指定数量后切换',
        'class': PoolQuotaStrategy,
        'params': {
            'pool_quotas': {
                'type': 'pool_int_map',
                'display_name': '各池配额',
                'default': {},
            },
        },
    },
    'pity_reserve': {
        'display_name': '保底预留',
        'description': '只在大保底概率≥阈值时才抽卡',
        'class': PityReserveStrategy,
        'params': {
            'pity_threshold_pct': {
                'type': 'float',
                'display_name': '保底概率阈值(%)',
                'default': 80.0,
                'min': 0.0,
                'max': 100.0,
            },
        },
    },
    'stop_on_target': {
        'display_name': '目标即停',
        'description': '抽到当期up/目标卡就停止',
        'class': StopOnTargetStrategy,
        'params': {
            'stop_on_featured': {
                'type': 'bool',
                'display_name': '抽到up即停',
                'default': True,
            },
            'stop_on_any_target': {
                'type': 'bool',
                'display_name': '抽到任意目标即停',
                'default': False,
            },
        },
    },
    'target_hunting': {
        'display_name': '指定池追卡',
        'description': '只从指定池子抽卡',
        'class': TargetHuntingStrategy,
        'params': {
            'target_pool_ids': {
                'type': 'string_list',
                'display_name': '目标池ID列表',
                'default': [],
            },
        },
    },
    'fixed_count': {
        'display_name': '固定次数',
        'description': '抽指定次数后停止',
        'class': FixedCountStrategy,
        'params': {
            'count': {
                'type': 'int',
                'display_name': '抽卡次数',
                'default': 100,
                'min': 1,
            },
        },
    },
    'no_draw': {
        'display_name': '不抽卡基线',
        'description': '不抽卡：始终等待，用于计算基线资源水平',
        'class': NoDrawStrategy,
        'params': {},
        'internal': True,
    },
    'draw_target': {
        'display_name': '目标池抽卡',
        'description': '最差影响分析专用：从目标池抽卡',
        'class': None,
        'params': {
            'target_card_ids': {
                'type': 'string_list',
                'display_name': '目标卡ID列表',
                'default': [],
            },
            'pool_id': {
                'type': 'str',
                'display_name': '目标池ID',
                'default': '',
            },
        },
        'internal': True,
    },
}


def create_strategy(strategy_name: str, params: Optional[Dict[str, Any]] = None) -> Strategy:
    entry = STRATEGY_REGISTRY.get(strategy_name)
    if entry is None:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    if entry.get('internal') and entry.get('class') is None:
        raise ValueError(f"Cannot create internal strategy '{strategy_name}': no instantiable class")
    cls = entry['class']
    p = params or {}
    if strategy_name == 'smart':
        return cls()
    elif strategy_name == 'pool_quota':
        return cls(pool_quotas=p.get('pool_quotas', {}))
    elif strategy_name == 'pity_reserve':
        return cls(pity_threshold_pct=p.get('pity_threshold_pct', 80.0))
    elif strategy_name == 'stop_on_target':
        return cls(
            stop_on_featured=p.get('stop_on_featured', True),
            stop_on_any_target=p.get('stop_on_any_target', False),
        )
    elif strategy_name == 'target_hunting':
        return cls(target_pool_ids=p.get('target_pool_ids', []))
    elif strategy_name == 'fixed_count':
        return cls(count=p.get('count', 100))
    elif strategy_name == 'draw_target':
        return cls(
            target_card_ids=set(p.get('target_card_ids', [])),
            pool_id=p.get('pool_id', ''),
        )
    return cls()


def strategy_type_to_key(display_name: str) -> str:
    for key, entry in STRATEGY_REGISTRY.items():
        if entry['display_name'] == display_name:
            return key
    return 'smart'


def strategy_key_to_type(key: str) -> str:
    entry = STRATEGY_REGISTRY.get(key)
    return entry['display_name'] if entry else '按需追卡'
