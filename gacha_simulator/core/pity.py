from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
import fnmatch
import os
import math


class PityBehavior(ABC):
    @abstractmethod
    def apply(self, counter_value: int, probabilities: Dict[str, float],
              extra: Dict[str, Any] = None) -> Dict[str, float]:
        pass

    def is_active(self, counter_value: int) -> bool:
        """该保底在给定计数器值下是否影响概率。子类应覆写此方法。"""
        return False


class SoftPityBehavior(PityBehavior):
    def __init__(self, start_at: int, end_at: int,
                 func_type: str = 'linear',
                 target_distribution: Dict[str, float] = None):
        self.start_at = start_at
        self.end_at = end_at
        self.func_type = func_type
        self.target_distribution = target_distribution or {}

    def is_active(self, counter_value: int) -> bool:
        return counter_value >= self.start_at

    def _progress(self, counter_value: int) -> float:
        if counter_value < self.start_at:
            return 0.0
        raw = (counter_value - self.start_at) / max(self.end_at - self.start_at, 1)
        raw = min(raw, 1.0)
        if self.func_type == 'exp':
            return raw * raw
        elif self.func_type == 'step':
            if raw < 0.33:
                return 0.0
            elif raw < 0.66:
                return 0.5
            else:
                return 1.0
        return raw

    def apply(self, counter_value: int, probabilities: Dict[str, float],
              extra: Dict[str, Any] = None) -> Dict[str, float]:
        progress = self._progress(counter_value)
        if progress <= 0:
            return probabilities.copy()

        resolved = self.target_distribution
        if extra and 'resolved_targets' in extra:
            resolved = extra['resolved_targets']

        if resolved:
            return self._apply_targeted(progress, probabilities, resolved)
        return self._apply_first(progress, probabilities)

    def _apply_targeted(self, progress: float,
                        probabilities: Dict[str, float],
                        resolved: Dict[str, float]) -> Dict[str, float]:
        total_target_weight = sum(resolved.values())
        if total_target_weight <= 0:
            return probabilities.copy()

        current_target_prob = sum(
            probabilities.get(tid, 0.0)
            for tid in resolved
        )
        other_prob = 1.0 - current_target_prob
        new_target_prob = min(current_target_prob + progress * other_prob, 1.0)
        new_other_prob = 1.0 - new_target_prob
        scale = new_other_prob / other_prob if other_prob > 0 else 0

        result = {}
        for rid, prob in probabilities.items():
            if rid in resolved:
                w = resolved[rid] / total_target_weight
                result[rid] = new_target_prob * w
            else:
                result[rid] = prob * scale
        return result

    def _apply_first(self, progress: float,
                     probabilities: Dict[str, float]) -> Dict[str, float]:
        items = list(probabilities.items())
        if not items:
            return probabilities.copy()

        first_id, first_prob = items[0]
        other_prob = 1.0 - first_prob
        new_first_prob = min(first_prob + progress * other_prob, 1.0)
        new_other_prob = 1.0 - new_first_prob
        scale = new_other_prob / other_prob if other_prob > 0 else 0

        result = {}
        for rid, prob in probabilities.items():
            if rid == first_id:
                result[rid] = new_first_prob
            else:
                result[rid] = prob * scale
        return result


class HardPityBehavior(PityBehavior):
    def __init__(self, threshold: int,
                 target_distribution: Dict[str, float] = None):
        self.threshold = threshold
        self.target_distribution = target_distribution or {}

    def is_active(self, counter_value: int) -> bool:
        return counter_value >= self.threshold

    def apply(self, counter_value: int, probabilities: Dict[str, float],
              extra: Dict[str, Any] = None) -> Dict[str, float]:
        if counter_value < self.threshold:
            return probabilities.copy()

        resolved = self.target_distribution
        if extra and 'resolved_targets' in extra:
            resolved = extra['resolved_targets']

        if resolved:
            total = sum(resolved.values())
            if total <= 0:
                return probabilities.copy()
            result = {k: 0.0 for k in probabilities}
            for tid, w in resolved.items():
                if tid in result:
                    result[tid] = w / total
            return result

        result = {k: 0.0 for k in probabilities}
        if probabilities:
            result[list(probabilities.keys())[0]] = 1.0
        return result


@dataclass
class PityDefParsed:
    name: str
    btype: str
    params: Dict[str, str]
    target_distribution: Dict[str, float]
    reset_condition: str
    pools: str


@dataclass
class PoolPitySpec:
    pity_names: List[str]
    featured_ids: Set[str] = field(default_factory=set)
    ssr_ids: Set[str] = field(default_factory=set)
    resolved_targets: Dict[str, Dict[str, float]] = field(default_factory=dict)


class PityState:
    def __init__(self):
        self.counters: Dict[str, int] = {}

    def increment(self, name: str):
        self.counters[name] = self.counters.get(name, 0) + 1

    def reset(self, name: str):
        self.counters[name] = 0

    def get(self, name: str) -> int:
        return self.counters.get(name, 0)

    def clone(self) -> 'PityState':
        ps = PityState()
        ps.counters = self.counters.copy()
        return ps

    def to_dict(self) -> Dict[str, Any]:
        return {
            'counters': dict(self.counters),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'PityState':
        ps = cls()
        ps.counters = d.get('counters', {})
        return ps


class PityEngine:
    def __init__(self, pool_specs: Dict[str, PoolPitySpec],
                 pity_defs: Dict[str, PityDefParsed],
                 behaviors: Dict[str, PityBehavior]):
        self.pool_specs = pool_specs
        self.pity_defs = pity_defs
        self.behaviors = behaviors

    def before_draw(self, pool_id: str, state: PityState,
                    base_probabilities: Dict[str, float]) -> Dict[str, float]:
        spec = self.pool_specs.get(pool_id)
        if spec is None:
            return base_probabilities.copy()

        for pname in spec.pity_names:
            state.increment(pname)

        adjusted = base_probabilities.copy()
        for pname in spec.pity_names:
            pdef = self.pity_defs.get(pname)
            behavior = self.behaviors.get(pname)
            if pdef is None or behavior is None:
                continue

            counter_value = state.get(pname)
            extra = {}
            resolved = spec.resolved_targets.get(pname)
            if resolved:
                extra['resolved_targets'] = resolved

            adjusted = behavior.apply(counter_value, adjusted, extra if extra else None)

        return adjusted

    def after_draw(self, pool_id: str, state: PityState, reward_id: str):
        spec = self.pool_specs.get(pool_id)
        if spec is None:
            return

        is_ssr = reward_id in spec.ssr_ids
        is_featured = reward_id in spec.featured_ids

        for pname in spec.pity_names:
            pdef = self.pity_defs.get(pname)
            if pdef is None:
                continue
            if pdef.reset_condition == 'any_ssr' and is_ssr:
                state.reset(pname)
            elif pdef.reset_condition == 'featured_ssr' and is_featured:
                state.reset(pname)
            elif pdef.reset_condition == 'never':
                pass

    def get_spec(self, pool_id: str) -> Optional[PoolPitySpec]:
        return self.pool_specs.get(pool_id)


def _parse_target_distribution(text: str) -> Dict[str, float]:
    result = {}
    if not text:
        return result
    for part in text.split(','):
        part = part.strip()
        if ':' in part:
            cid, w = part.rsplit(':', 1)
            try:
                result[cid.strip()] = float(w.strip())
            except ValueError:
                result[cid.strip()] = 1.0
        else:
            result[part.strip()] = 1.0
    return result


def parse_pity_file(filepath: str) -> List[PityDefParsed]:
    pity_defs = []

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if line.startswith('pity:'):
                rest = line[len('pity:'):].strip()
                parts = [p.strip() for p in rest.split('|')]
                name = parts[0]
                params = {}
                for p in parts[1:]:
                    if '=' in p:
                        k, v = p.split('=', 1)
                        params[k.strip()] = v.strip()

                btype = params.get('type', 'soft')
                target_dist = _parse_target_distribution(params.get('target', ''))
                reset = params.get('reset', 'any_ssr')
                pools = params.get('pools', '*')

                clean_params = {k: v for k, v in params.items()
                                if k not in ('type', 'target', 'reset', 'pools')}

                pity_defs.append(PityDefParsed(
                    name=name,
                    btype=btype,
                    params=clean_params,
                    target_distribution=target_dist,
                    reset_condition=reset,
                    pools=pools,
                ))

    return pity_defs


def _build_behavior(pdef: PityDefParsed) -> PityBehavior:
    if pdef.btype == 'soft':
        return SoftPityBehavior(
            start_at=int(pdef.params.get('start', '74')),
            end_at=int(pdef.params.get('end', '90')),
            func_type=pdef.params.get('func', 'linear'),
            target_distribution=dict(pdef.target_distribution),
        )
    elif pdef.btype == 'hard':
        return HardPityBehavior(
            threshold=int(pdef.params.get('threshold', '90')),
            target_distribution=dict(pdef.target_distribution),
        )
    return SoftPityBehavior(start_at=74, end_at=90)


def build_pity_engine(config_dir: str, pool_ids: List[str],
                      featured_ids_map: Dict[str, Set[str]],
                      ssr_ids_map: Dict[str, Set[str]]) -> Optional['PityEngine']:
    pity_path = os.path.join(config_dir, 'pity.txt')
    if not os.path.exists(pity_path):
        return None

    parsed_defs = parse_pity_file(pity_path)
    if not parsed_defs:
        return None

    pity_defs: Dict[str, PityDefParsed] = {}
    behaviors: Dict[str, PityBehavior] = {}
    for pdef in parsed_defs:
        pity_defs[pdef.name] = pdef
        behaviors[pdef.name] = _build_behavior(pdef)

    pool_specs: Dict[str, PoolPitySpec] = {}
    for pool_id in pool_ids:
        matching = []
        for pdef in parsed_defs:
            if fnmatch.fnmatch(pool_id, pdef.pools):
                matching.append(pdef.name)

        pool_specs[pool_id] = PoolPitySpec(
            pity_names=matching,
            featured_ids=featured_ids_map.get(pool_id, set()),
            ssr_ids=ssr_ids_map.get(pool_id, set()),
        )

    return PityEngine(pool_specs, pity_defs, behaviors)
