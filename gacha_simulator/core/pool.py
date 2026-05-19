from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any
import random
import bisect
from itertools import product


NO_CARD_ID = "_no_card"

CostOption = Dict[str, float]
PoolCost = List[CostOption]


def _parse_atom(token: str) -> CostOption:
    result: CostOption = {}
    for part in token.split('&'):
        part = part.strip()
        if ':' in part:
            rid, amt = part.split(':', 1)
            result[rid.strip()] = float(amt.strip())
    return result


def _tokenize(cost_str: str) -> List[str]:
    tokens = []
    current = []
    depth = 0
    for ch in cost_str:
        if ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            tokens.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    tail = ''.join(current).strip()
    if tail:
        tokens.append(tail)
    return tokens


def _strip_parens(s: str) -> str:
    s = s.strip()
    while s.startswith('(') and s.endswith(')'):
        depth = 0
        matched = True
        for i, ch in enumerate(s):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            if depth == 0 and i < len(s) - 1:
                matched = False
                break
        if matched:
            s = s[1:-1].strip()
        else:
            break
    return s


def _parse_cost_expr(cost_str: str) -> PoolCost:
    cost_str = _strip_parens(cost_str)
    if not cost_str:
        return []

    or_tokens = _tokenize(cost_str)
    if len(or_tokens) > 1:
        result = []
        for token in or_tokens:
            result.extend(_parse_cost_expr(token))
        return result

    depth = 0
    and_positions = []
    for i, ch in enumerate(cost_str):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == '&' and depth == 0:
            and_positions.append(i)

    if not and_positions:
        atom = _parse_atom(cost_str)
        return [atom] if atom else []

    parts = []
    prev = 0
    for pos in and_positions:
        parts.append(cost_str[prev:pos])
        prev = pos + 1
    parts.append(cost_str[prev:])

    parsed_parts = [_parse_cost_expr(p) for p in parts]

    result = []
    for combo in product(*parsed_parts):
        merged: CostOption = {}
        for option in combo:
            for rid, amt in option.items():
                merged[rid] = merged.get(rid, 0) + amt
        if merged:
            result.append(merged)
    return result


def parse_cost_string(cost_str: str) -> PoolCost:
    if not cost_str:
        return []
    return _parse_cost_expr(cost_str)


def cost_to_string(cost: PoolCost) -> str:
    parts = []
    for option in cost:
        sub_parts = [f"{rid}:{amt}" for rid, amt in option.items()]
        parts.append('&'.join(sub_parts))
    return ','.join(parts)


@dataclass
class Reward:
    id: str
    name: str
    resources_gained: Dict[str, float] = field(default_factory=dict)
    extra_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Pool:
    id: str
    name: str
    cost: PoolCost
    rewards: List[Tuple[Reward, float]]
    available_from: Optional[float] = None
    available_until: Optional[float] = None
    is_exchange: bool = False
    is_rerun: bool = False
    original_pool_id: Optional[str] = None
    exchange_card_id: Optional[str] = None

    def __post_init__(self):
        if not self.is_exchange and self.rewards:
            self._reward_list = [r for r, _ in self.rewards]
            self._cum_weights = []
            total = 0.0
            for _, p in self.rewards:
                total += p
                self._cum_weights.append(total)
            self._total_weight = total
        else:
            self._reward_list = []
            self._cum_weights = []
            self._total_weight = 0.0

        self._adjusted_cum_weights = None
        self._adjusted_total_weight = None
        self._use_adjusted = False

    def _apply_probabilities(self, probabilities: Dict[str, float]):
        self._adjusted_cum_weights = []
        total = 0.0
        for reward in self._reward_list:
            prob = probabilities.get(reward.id, 0.0)
            total += prob
            self._adjusted_cum_weights.append(total)
        self._adjusted_total_weight = total
        self._use_adjusted = True

    def draw(self) -> Reward:
        if self.is_exchange:
            if not self.rewards:
                raise ValueError(f"Exchange pool {self.id} has no rewards")
            return self.rewards[0][0]
        
        if self._use_adjusted and self._adjusted_cum_weights and self._adjusted_total_weight > 0:
            r = random.random() * self._adjusted_total_weight
            idx = bisect.bisect_left(self._adjusted_cum_weights, r)
            if idx >= len(self._reward_list):
                idx = len(self._reward_list) - 1
            self._use_adjusted = False
            return self._reward_list[idx]
        
        if not self._cum_weights:
            raise ValueError(f"Pool {self.id} has no valid rewards")
        
        r = random.random() * self._total_weight
        idx = bisect.bisect_left(self._cum_weights, r)
        if idx >= len(self._reward_list):
            idx = len(self._reward_list) - 1
        return self._reward_list[idx]

    def is_available_at(self, time: float) -> bool:
        if self.available_from is not None and time < self.available_from:
            return False
        if self.available_until is not None and time > self.available_until:
            return False
        return True
