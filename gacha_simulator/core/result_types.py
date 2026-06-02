from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


_RESULT_VERSION = 1


@dataclass
class CompactResult:
    draw_card_ids: List[str] = field(default_factory=list)
    draw_pool_ids: List[str] = field(default_factory=list)
    draw_times: List[float] = field(default_factory=list)
    draw_pity: List[bool] = field(default_factory=list)
    draw_pity_names: List[Optional[str]] = field(default_factory=list)
    draw_pity_counter_max: List[int] = field(default_factory=list)
    draw_resources_consumed: List[Dict[str, float]] = field(default_factory=list)
    draw_resources_gained: List[Dict[str, float]] = field(default_factory=list)
    wait_durations: List[float] = field(default_factory=list)
    total_consumed: Dict[str, float] = field(default_factory=dict)
    total_gained: Dict[str, float] = field(default_factory=dict)
    card_counts: Dict[str, int] = field(default_factory=dict)
    pool_draw_counts: Dict[str, int] = field(default_factory=dict)
    pool_card_counts: Dict[str, Dict[str, int]] = field(default_factory=dict)
    pool_pity_counts: Dict[str, int] = field(default_factory=dict)
    total_draws: int = 0
    total_waits: int = 0
    pity_triggers: int = 0
    final_resources: Dict[str, float] = field(default_factory=dict)
    final_time: float = 0.0
    final_pity_state: Dict[str, Any] = field(default_factory=dict)
    pool_end_resources: Dict[str, Dict[str, float]] = field(default_factory=dict)
    pool_end_pity_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    pool_types: Dict[str, str] = field(default_factory=dict)
    strategy_name: str = ''
    result_version: int = _RESULT_VERSION
    generated_at: float = 0.0

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return default

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) and not key.startswith('_')

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CompactResult:
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)
