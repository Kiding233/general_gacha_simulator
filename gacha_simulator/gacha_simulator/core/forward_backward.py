#!/usr/bin/env python3
"""
前进法/后退法目标优化算法
每次目标集合变化都必须重新运行完整模拟
"""

from typing import List, Dict, Set
from dataclasses import dataclass


@dataclass
class ForwardStep:
    added_card_id: str
    target_set: Set[str]
    success_probability: float
    target_specs: Dict[str, int]


@dataclass
class BackwardStep:
    removed_card_id: str
    target_set: Set[str]
    success_probability: float
    target_specs: Dict[str, int]


@dataclass
class ForwardResult:
    steps: List[ForwardStep]
    final_target_set: Set[str]
    final_success_probability: float
    final_target_specs: Dict[str, int]


@dataclass
class BackwardResult:
    steps: List[BackwardStep]
    final_target_set: Set[str]
    final_success_probability: float
    final_target_specs: Dict[str, int]


@dataclass
class ResourceSearchStep:
    iteration: int
    resource_value: float
    success_probability: float
    phase: str
    lo_bound: float
    hi_bound: float


@dataclass
class ResourceSearchResult:
    steps: List[ResourceSearchStep]
    min_resource: float
    final_success_probability: float
    cost_per_draw: float
    target_specs: Dict[str, int]
    total_iterations: int
