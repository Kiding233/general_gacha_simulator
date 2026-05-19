from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from ..core.schedule import PoolSchedule
from ..core.pool import Pool
from ..core.target_card import TargetCard, TargetCardSet


class TargetCardGenerator(ABC):
    @abstractmethod
    def generate(
        self,
        future_schedules: List[PoolSchedule],
        pools: List[Pool],
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> TargetCardSet:
        pass


class UserDefinedTargetGenerator(TargetCardGenerator):
    def __init__(self, targets: TargetCardSet):
        self.targets = targets

    def generate(
        self,
        future_schedules: List[PoolSchedule],
        pools: List[Pool],
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> TargetCardSet:
        return self.targets


class RuleBasedTargetGenerator(TargetCardGenerator):
    def __init__(self, rules: List[Dict[str, Any]]):
        self.rules = rules

    def generate(
        self,
        future_schedules: List[PoolSchedule],
        pools: List[Pool],
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> TargetCardSet:
        targets = []
        for rule in self.rules:
            rule_type = rule.get('type')
            if rule_type == 'all_in_pool':
                pool_id = rule.get('pool_id')
                quantity = rule.get('quantity', 1)
                for pool in pools:
                    if pool.id == pool_id:
                        for reward, _ in pool.rewards:
                            targets.append(TargetCard(
                                card_id=reward.id,
                                pool_ids=[pool_id],
                                quantity_needed=quantity,
                            ))
        return TargetCardSet(targets)
