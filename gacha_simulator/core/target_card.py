from dataclasses import dataclass, field
from typing import List


@dataclass
class TargetCard:
    card_id: str
    pool_ids: List[str]
    quantity_needed: int
    priority: int = 0

    def is_in_pool(self, pool_id: str) -> bool:
        return pool_id in self.pool_ids


@dataclass
class TargetCardSet:
    targets: List[TargetCard] = field(default_factory=list)

    def get_quantity_needed(self, card_id: str) -> int:
        for t in self.targets:
            if t.card_id == card_id:
                return t.quantity_needed
        return 0

    def get_cards_by_pool(self, pool_id: str) -> List[TargetCard]:
        return [t for t in self.targets if t.is_in_pool(pool_id)]

    def get_unfinished_targets(self, acquired: dict) -> List[TargetCard]:
        result = []
        for t in self.targets:
            current = acquired.get(t.card_id, 0)
            if current < t.quantity_needed:
                result.append(t)
        return sorted(result, key=lambda x: x.priority, reverse=True)
