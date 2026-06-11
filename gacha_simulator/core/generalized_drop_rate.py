from abc import ABC, abstractmethod
from typing import List, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from .info_vector import InfoVector


class GeneralizedDropRate(ABC):
    @abstractmethod
    def compute(self, t: int, history: List['InfoVector']) -> float:
        pass

    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @classmethod
    @abstractmethod
    def description(cls) -> str:
        pass


class RarityValueAtT(GeneralizedDropRate):
    def __init__(self, rarity_values: Dict[str, float]):
        self.rarity_values = rarity_values

    @classmethod
    def description(cls) -> str:
        return "返回第t次抽卡的稀有度价值"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        if t >= len(history):
            return 0
        iv = history[t]
        return self.rarity_values.get(iv.card_id or '', 0)


class CumulativeResourceEfficiency(GeneralizedDropRate):
    @classmethod
    def description(cls) -> str:
        return "累计资源效率 = 总获得资源 / 总消耗资源"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        if t == 0:
            return 0
        total_consumed = sum(
            sum(iv.resources_consumed.values()) for iv in history[:t]
        )
        total_gained = sum(
            sum(iv.resources_gained.values()) for iv in history[:t]
        )
        if total_consumed == 0:
            return 0
        return total_gained / total_consumed


class PityProgressAtT(GeneralizedDropRate):
    def __init__(self, counter_name: str, threshold: int):
        self.counter_name = counter_name
        self.threshold = threshold

    @classmethod
    def description(cls) -> str:
        return "保底进度 = 当前计数 / 保底阈值"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        if t >= len(history):
            return 0
        pity_state = history[t].pity_state
        count = pity_state.get(self.counter_name, 0)
        return min(count / self.threshold, 1.0)


class DropRateBetweenT1T2(GeneralizedDropRate):
    def __init__(self, t1: int, t2: int, target_id: str):
        self.t1 = t1
        self.t2 = t2
        self.target_id = target_id

    def description(self) -> str:
        return f"{self.t1}到{self.t2}次抽卡之间的平均出率"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        start = max(0, self.t1)
        end = min(len(history), t)
        if end <= start:
            return 0
        count = sum(1 for iv in history[start:end] if iv.card_id == self.target_id)
        return count / (end - start)


class TotalValueAtT(GeneralizedDropRate):
    def __init__(self, value_functions: List[GeneralizedDropRate], weights: List[float] = None):
        self.value_functions = value_functions
        self.weights = weights or [1.0] * len(value_functions)

    @classmethod
    def description(cls) -> str:
        return "多个价值函数的加权和"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        total = 0
        for vf, weight in zip(self.value_functions, self.weights):
            total += vf.compute(t, history) * weight
        return total


class TargetCardCountAtT(GeneralizedDropRate):
    """在第t次行动之前（包括t）抽中目标卡的数量"""

    def __init__(self, target_card_ids: List[str]):
        self.target_card_ids = target_card_ids

    @classmethod
    def description(cls) -> str:
        return "累计抽中目标卡的数量"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        if t < 0:
            return 0
        end = min(t + 1, len(history))
        draw_history = [iv for iv in history[:end] if iv.action_type == 'draw']
        count = sum(1 for iv in draw_history if iv.card_id in self.target_card_ids)
        return float(count)


class TargetCardPercentageAtT(GeneralizedDropRate):
    """在第t次行动之前（包括t）抽中目标卡的百分比"""

    def __init__(self, target_card_ids: List[str]):
        self.target_card_ids = target_card_ids

    @classmethod
    def description(cls) -> str:
        return "目标卡占总抽卡的百分比"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        if t < 0:
            return 0.0
        end = min(t + 1, len(history))
        draw_history = [iv for iv in history[:end] if iv.action_type == 'draw']
        total_draws = len(draw_history)
        if total_draws == 0:
            return 0.0
        target_count = sum(1 for iv in draw_history if iv.card_id in self.target_card_ids)
        return (target_count / total_draws) * 100.0


class TargetCardEfficiencyAtT(GeneralizedDropRate):
    """目标卡出卡效率: 目标卡出卡数 / 消耗的抽卡资源

    效率 = 抽中的目标卡数量 / 消耗的石头数 * 基准资源量(通常为160)
    或者简化为: 目标卡数量 / 抽卡次数
    
    Args:
        target_card_ids: 目标卡ID列表
        base_cost: 基准单抽消耗资源量，默认为160
    """

    def __init__(self, target_card_ids: List[str], base_cost: float = 160.0):
        self.target_card_ids = target_card_ids
        self.base_cost = base_cost

    @classmethod
    def description(cls) -> str:
        return "目标卡出卡效率 = 目标卡数 / 消耗资源 * 基准量"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        if t < 0:
            return 0.0
        end = min(t + 1, len(history))
        draw_history = [iv for iv in history[:end] if iv.action_type == 'draw']
        
        if not draw_history:
            return 0.0
        
        target_count = sum(1 for iv in draw_history if iv.card_id in self.target_card_ids)
        
        total_consumed = sum(
            sum(iv.resources_consumed.values()) 
            for iv in draw_history
        )
        
        if total_consumed == 0:
            return 0.0
        
        efficiency = (target_count / total_consumed) * self.base_cost
        return efficiency
