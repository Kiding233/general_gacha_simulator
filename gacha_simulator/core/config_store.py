from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from .strategy import strategy_type_to_key, strategy_key_to_type, STRATEGY_REGISTRY


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
    strategy_name: str = 'smart'
    strategy_params: Dict[str, Any] = field(default_factory=dict)
    stop_condition_type: str = '所有池结束'
    stop_condition_params: Dict[str, Any] = field(default_factory=dict)
    auto_wait: bool = True
    card_weights: Dict[str, CardWeightEntry] = field(default_factory=dict)
    simulation_count: int = 1000
    max_workers: int = 4
    seed: int = 42

    def __post_init__(self):
        if self.strategy_type:
            if self.strategy_type in STRATEGY_REGISTRY:
                self.strategy_name = self.strategy_type
            else:
                resolved = strategy_type_to_key(self.strategy_type)
                if resolved != self.strategy_name:
                    self.strategy_name = resolved

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
        self.strategy_name = 'smart'
        self.strategy_params.clear()
        self.stop_condition_type = '所有池结束'
        self.stop_condition_params.clear()
        self.auto_wait = True
        self.card_weights.clear()
        self.simulation_count = 1000
        self.max_workers = 4
        self.seed = 42
