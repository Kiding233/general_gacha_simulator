from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from .pool import Pool, PoolCost, CostOption


@dataclass
class GachaState:
    resources: Dict[str, float] = field(default_factory=dict)
    pity_counters: Dict[str, int] = field(default_factory=dict)
    real_time: float = 0.0
    total_actions: int = 0
    extra_state: Dict[str, Any] = field(default_factory=dict)

    def can_afford(self, cost) -> bool:
        if isinstance(cost, dict):
            return self._can_afford_option(cost)
        if isinstance(cost, list):
            return any(self._can_afford_option(opt) for opt in cost)
        return False

    def _can_afford_option(self, option: CostOption) -> bool:
        for resource, amount in option.items():
            if self.resources.get(resource, 0) < amount:
                return False
        return True

    def choose_cost_option(self, cost) -> Optional[CostOption]:
        if isinstance(cost, dict):
            if self._can_afford_option(cost):
                return cost
            return None
        if isinstance(cost, list):
            for option in cost:
                if self._can_afford_option(option):
                    return option
            return None
        return None

    def spend(self, cost) -> Optional[CostOption]:
        chosen = self.choose_cost_option(cost)
        if chosen is None:
            return None
        for resource, amount in chosen.items():
            if resource in self.resources:
                self.resources[resource] -= amount
                if self.resources[resource] < 0:
                    self.resources[resource] = 0
        return chosen

    def gain(self, gains: Dict[str, float]) -> None:
        for resource, amount in gains.items():
            self.resources[resource] = self.resources.get(resource, 0) + amount

    def get_available_pools(self, pools: List[Pool]) -> List[Pool]:
        return [pool for pool in pools if pool.is_available_at(self.real_time)]

    def clone(self) -> 'GachaState':
        return GachaState(
            resources=self.resources.copy(),
            pity_counters=self.pity_counters.copy(),
            real_time=self.real_time,
            total_actions=self.total_actions,
            extra_state=self.extra_state.copy(),
        )
