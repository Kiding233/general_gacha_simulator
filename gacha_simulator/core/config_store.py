from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class PoolDistEntry:
    card_id: str
    probability: float
    rarity: str = 'R'
    featured: bool = False
    resources_gained: Dict[str, float] = field(default_factory=dict)


@dataclass
class PoolEntry:
    enabled: bool = True
    pool_id: str = ''
    name: str = ''
    start_day: int = 0
    end_day: int = 21
    cost: str = 'draw_resource:160'
    distribution_file: str = ''
    bindings: Dict[str, str] = field(default_factory=dict)
    target_specs: List[tuple] = field(default_factory=list)
    rerun_of: Optional[str] = None
    exchange_card_id: Optional[str] = None
    distribution: List[PoolDistEntry] = field(default_factory=list)


@dataclass
class PityDef:
    name: str
    btype: str = 'soft'
    params: Dict[str, str] = field(default_factory=dict)
    target_distribution: Dict[str, float] = field(default_factory=dict)
    reset_condition: str = 'any_ssr'
    pools: str = '*'


@dataclass
class PityConfig:
    enabled: bool = True
    pities: List[PityDef] = field(default_factory=list)
    counter_init: Dict[str, int] = field(default_factory=dict)


@dataclass
class GainRule:
    rule_type: str = 'every_n_days'
    param: str = '1'
    gains: Dict[str, float] = field(default_factory=dict)


@dataclass
class DayOverride:
    day: int = 0
    gains: Dict[str, float] = field(default_factory=dict)


@dataclass
class TargetCardEntry:
    card_id: str
    quantity: int = 1
    pool_ids: List[str] = field(default_factory=list)


@dataclass
class CardDefEntry:
    card_id: str
    name: str = ''
    rarity: str = 'r'
    pools: List[str] = field(default_factory=list)


@dataclass
class CardWeightEntry:
    desire_weight: float = 1.0
    miss_cost_weight: float = 1.0
    card_value: float = 1.0


@dataclass
class ConfigStore:
    card_defs: List[CardDefEntry] = field(default_factory=list)
    resource_defs: Dict[str, str] = field(default_factory=dict)
    pools: List[PoolEntry] = field(default_factory=list)
    pity: PityConfig = field(default_factory=PityConfig)
    gain_rules: List[GainRule] = field(default_factory=list)
    day_overrides: List[DayOverride] = field(default_factory=list)
    initial_resources: Dict[str, float] = field(default_factory=dict)
    target_cards: List[TargetCardEntry] = field(default_factory=list)
    strategy_type: str = '按需追卡'
    auto_wait: bool = True
    card_weights: Dict[str, CardWeightEntry] = field(default_factory=dict)

    def clear(self):
        self.card_defs.clear()
        self.resource_defs.clear()
        self.pools.clear()
        self.pity = PityConfig()
        self.gain_rules.clear()
        self.day_overrides.clear()
        self.initial_resources.clear()
        self.target_cards.clear()
        self.strategy_type = '按需追卡'
        self.auto_wait = True
        self.card_weights.clear()
