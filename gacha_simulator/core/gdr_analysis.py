"""成功概率分析模块

功能：
1. 给定广义出率 GDR(t) 和阈值 c，计算 P(GDR(t) > c)
2. 给定成功概率 p，反向计算阈值 c 使得 P(GDR(t) > c) = p
"""

import numpy as np
from typing import List, Callable, Tuple, Optional
from .info_vector import InfoVector


class SuccessProbabilityAnalyzer:
    """成功概率分析器"""
    
    def __init__(self, gdr_function: Callable[[int, List[InfoVector]], float]):
        """
        Args:
            gdr_function: 广义出率函数，签名为 gdr(t, history) -> float
        """
        self.gdr_function = gdr_function
    
    def compute_success_probability(
        self,
        histories: List[List[InfoVector]],
        threshold: float,
        t: Optional[int] = None
    ) -> float:
        """
        计算在时间t广义出率超过阈值threshold的成功概率
        
        Args:
            histories: 多次模拟的历史记录列表
            threshold: 阈值c
            t: 时间点，如果为None则在最后一次行动计算
        
        Returns:
            P(GDR(t) > c)
        """
        if not histories:
            return 0.0
        
        successes = 0
        total = len(histories)
        
        for history in histories:
            if t is None:
                t_calc = len(history) - 1
            else:
                t_calc = t
            
            if t_calc < 0 or t_calc >= len(history):
                continue
            
            gdr_value = self.gdr_function(t_calc, history)
            if gdr_value > threshold:
                successes += 1
        
        return successes / total
    
    def compute_threshold_from_probability(
        self,
        histories: List[List[InfoVector]],
        target_probability: float,
        t: Optional[int] = None
    ) -> float:
        """
        反向计算：给定成功概率，计算对应的阈值
        
        Args:
            histories: 多次模拟的历史记录列表
            target_probability: 目标成功概率 (0-1)
            t: 时间点
        
        Returns:
            阈值c，使得 P(GDR(t) > c) ≈ target_probability
        """
        gdr_values = []
        for history in histories:
            if t is None:
                t_calc = len(history) - 1
            else:
                t_calc = t
            
            if t_calc < 0 or t_calc >= len(history):
                continue
            
            gdr_value = self.gdr_function(t_calc, history)
            gdr_values.append(gdr_value)
        
        if not gdr_values:
            return 0.0
        
        sorted_values = np.sort(gdr_values)
        n = len(sorted_values)
        idx = int((1 - target_probability) * n)
        idx = max(0, min(idx, n - 1))
        
        return sorted_values[idx]
    
    def compute_full_distribution(
        self,
        histories: List[List[InfoVector]],
        t: Optional[int] = None
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        计算广义出率的完整分布
        
        Args:
            histories: 多次模拟的历史记录列表
            t: 时间点
        
        Returns:
            (values, probabilities) 累积分布
        """
        gdr_values = []
        for history in histories:
            if t is None:
                t_calc = len(history) - 1
            else:
                t_calc = t
            
            if t_calc < 0 or t_calc >= len(history):
                continue
            
            gdr_value = self.gdr_function(t_calc, history)
            gdr_values.append(gdr_value)
        
        if not gdr_values:
            return np.array([]), np.array([])
        
        sorted_values = np.sort(gdr_values)
        probabilities = np.arange(1, len(sorted_values) + 1) / len(sorted_values)
        
        return sorted_values, probabilities
    
    def compute_quantiles(
        self,
        histories: List[List[InfoVector]],
        quantiles: List[float],
        t: Optional[int] = None
    ) -> List[float]:
        """
        计算广义出率的分位数
        
        Args:
            histories: 多次模拟的历史记录列表
            quantiles: 分位数列表 [0.25, 0.5, 0.75, ...]
            t: 时间点
        
        Returns:
            对应的分位数值
        """
        gdr_values = []
        for history in histories:
            if t is None:
                t_calc = len(history) - 1
            else:
                t_calc = t
            
            if t_calc < 0 or t_calc >= len(history):
                continue
            
            gdr_value = self.gdr_function(t_calc, history)
            gdr_values.append(gdr_value)
        
        if not gdr_values:
            return [0.0] * len(quantiles)
        
        return [np.percentile(gdr_values, q * 100) for q in quantiles]


def compute_gdr_efficiency(history: List[InfoVector], target_ids: List[str], base_cost: float = 160.0) -> float:
    """计算目标卡出卡效率（用于直接调用）"""
    draw_history = [iv for iv in history if iv.action_type == 'draw']
    if not draw_history:
        return 0.0
    
    target_count = sum(1 for iv in draw_history if iv.card_id in target_ids)
    total_consumed = sum(sum(iv.resources_consumed.values()) for iv in draw_history)
    
    if total_consumed == 0:
        return 0.0
    
    return (target_count / total_consumed) * base_cost


def compute_gdr_count(history: List[InfoVector], target_ids: List[str]) -> float:
    """计算目标卡数量"""
    draw_history = [iv for iv in history if iv.action_type == 'draw']
    return float(sum(1 for iv in draw_history if iv.card_id in target_ids))


def compute_gdr_percentage(history: List[InfoVector], target_ids: List[str]) -> float:
    """计算目标卡百分比"""
    draw_history = [iv for iv in history if iv.action_type == 'draw']
    total = len(draw_history)
    if total == 0:
        return 0.0
    target = sum(1 for iv in draw_history if iv.card_id in target_ids)
    return (target / total) * 100.0


class LegacyGDRCalculator:
    """[DEPRECATED] 旧版 GDR 计算器（InfoVector 路径）——已被 core.gdr.GDRCalculator 取代。"""
    
    TYPE_COUNT = 'count'
    TYPE_PERCENTAGE = 'percentage'
    TYPE_EFFICIENCY = 'efficiency'
    
    def __init__(self, gdr_type: str, target_ids: List[str], **kwargs):
        self.gdr_type = gdr_type
        self.target_ids = target_ids
        self.base_cost = kwargs.get('base_cost', 160.0)
    
    def compute(self, t: int, history: List[InfoVector]) -> float:
        if self.gdr_type == self.TYPE_COUNT:
            return compute_gdr_count(history[:t+1], self.target_ids)
        elif self.gdr_type == self.TYPE_PERCENTAGE:
            return compute_gdr_percentage(history[:t+1], self.target_ids)
        elif self.gdr_type == self.TYPE_EFFICIENCY:
            return compute_gdr_efficiency(history[:t+1], self.target_ids, self.base_cost)
        else:
            return 0.0
    
    def get_analyzer(self, histories: List[List[InfoVector]]) -> SuccessProbabilityAnalyzer:
        def gdr_func(t: int, history: List[InfoVector]) -> float:
            return self.compute(t, history)
        return SuccessProbabilityAnalyzer(gdr_func)