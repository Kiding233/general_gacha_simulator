import math
from typing import List, Dict, Optional, Callable, Tuple
from dataclasses import dataclass


@dataclass
class DistributionSummary:
    mean: float
    median: float
    std: float
    min_val: float
    max_val: float
    sample_count: int
    quantiles: Dict[float, float]


class JointSamples:
    def __init__(self, paired: List[Tuple[float, float]]):
        self._paired = list(paired)
        self._n = len(paired)
        self._first = [p[0] for p in self._paired]
        self._second = [p[1] for p in self._paired]

    @property
    def n(self) -> int:
        return self._n

    def first_distribution(self) -> 'EmpiricalDistribution':
        return EmpiricalDistribution(self._first)

    def second_distribution(self) -> 'EmpiricalDistribution':
        return EmpiricalDistribution(self._second)

    def conditional_second(self, predicate_on_first: Callable[[float], bool]) -> 'EmpiricalDistribution':
        filtered = [s for f, s in self._paired if predicate_on_first(f)]
        return EmpiricalDistribution(filtered)

    def conditional_second_below_quantile(self, alpha: float = 0.05) -> 'EmpiricalDistribution':
        first_dist = self.first_distribution()
        threshold = first_dist.quantile(alpha)
        return self.conditional_second(lambda f: f <= threshold)

    def conditional_second_above_quantile(self, alpha: float = 0.05) -> 'EmpiricalDistribution':
        first_dist = self.first_distribution()
        threshold = first_dist.quantile(1 - alpha)
        return self.conditional_second(lambda f: f >= threshold)

    def conditional_first(self, predicate_on_second: Callable[[float], bool]) -> 'EmpiricalDistribution':
        filtered = [f for f, s in self._paired if predicate_on_second(s)]
        return EmpiricalDistribution(filtered)

    @staticmethod
    def from_histories(histories, first_func: Callable, second_func: Callable, ctx=None) -> 'JointSamples':
        if ctx is not None:
            paired = [(first_func(h, ctx), second_func(h, ctx)) for h in histories]
        else:
            paired = [(first_func(h), second_func(h)) for h in histories]
        return JointSamples(paired)


class EmpiricalDistribution:
    def __init__(self, samples: List[float]):
        self._sorted = sorted(samples)
        self._samples = list(samples)
        self._n = len(samples)
        self._evt_lower = None  # 下尾 GPD 拟合缓存 (ξ, β, threshold_Y, phi)
        self._evt_upper = None  # 上尾 GPD 拟合缓存 (ξ, β, threshold, phi)
        self._distinct_count = None  # 不同取值数（惰性计算 + 缓存），用于退化检测

    @property
    def n(self) -> int:
        return self._n

    @property
    def samples(self) -> List[float]:
        return list(self._samples)

    def _count_distinct(self) -> int:
        """不同取值数——惰性计算，用于退化数据检测（<20 跳过 EVT）。"""
        if self._distinct_count is None:
            if self._n == 0:
                self._distinct_count = 0
            else:
                cnt = 1
                for i in range(1, self._n):
                    if self._sorted[i] != self._sorted[i - 1]:
                        cnt += 1
                self._distinct_count = cnt
        return self._distinct_count

    def mean(self) -> float:
        if self._n == 0:
            return float('nan')
        return sum(self._samples) / self._n

    def median(self) -> float:
        return self.quantile(0.5)

    def std(self) -> float:
        if self._n < 2:
            return 0.0
        m = self.mean()
        var = sum((x - m) ** 2 for x in self._samples) / (self._n - 1)
        return math.sqrt(var)

    def min_val(self) -> float:
        return self._sorted[0] if self._n > 0 else float('nan')

    def max_val(self) -> float:
        return self._sorted[-1] if self._n > 0 else float('nan')

    def quantile(self, p: float, use_evt: bool = True) -> float:
        """分位数 —— 极端分位数自动使用 EVT GPD 外推。"""
        if self._n == 0:
            return float('nan')
        if p <= 0:
            return self._sorted[0]
        if p >= 1:
            return self._sorted[-1]
        if use_evt and (p <= 0.1 or p >= 0.9) and self._n >= 100:
            evt_result = self._evt_quantile(p)
            if evt_result is not None:
                return evt_result
        return self._empirical_quantile(p)

    def _empirical_quantile(self, p: float) -> float:
        """经验分位数（线性插值）—— EVT 回退路径。"""
        idx = p * (self._n - 1)
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return self._sorted[lo]
        frac = idx - lo
        return self._sorted[lo] * (1 - frac) + self._sorted[hi] * frac

    def _evt_quantile(self, p: float):
        """EVT GPD 外推分位数。首次调用时拟合并缓存 GPD 参数。"""
        if self._count_distinct() < 20:
            return None  # 退化/近退化数据（二元、有限格点等），GPD 拟合无意义
        from .evt_tail import fit_gpd_lower, fit_gpd_upper, evt_var_right

        if p <= 0.1:
            if self._evt_lower is None:
                self._evt_lower = fit_gpd_lower(self._samples)
            if self._evt_lower is None:
                return None
            xi, beta, u_Y, phi = self._evt_lower
            # VaR_X(p) = -VaR_Y(1-p)
            q_y = 1.0 - p
            var_y = evt_var_right(q_y, xi, beta, u_Y, phi)
            if var_y is None:
                return None
            return -var_y
        else:  # p >= 0.9
            if self._evt_upper is None:
                self._evt_upper = fit_gpd_upper(self._samples)
            if self._evt_upper is None:
                return None
            xi, beta, u, phi = self._evt_upper
            return evt_var_right(p, xi, beta, u, phi)

    def var(self, alpha: float = 0.05, use_evt: bool = True) -> float:
        return self.quantile(alpha, use_evt=use_evt)

    def cvar(self, alpha: float = 0.05, use_evt: bool = True) -> float:
        """CVaR —— 极端分位数自动使用 EVT GPD 外推。"""
        if self._n == 0:
            return float('nan')
        if use_evt and 0 < alpha <= 0.1 and self._n >= 100:
            evt_result = self._evt_cvar(alpha)
            if evt_result is not None:
                return evt_result
        return self._empirical_cvar(alpha)

    def _empirical_cvar(self, alpha: float) -> float:
        """经验 CVaR —— EVT 回退路径。"""
        n_tail = alpha * self._n
        lo = int(math.floor(n_tail))
        if lo >= self._n:
            return self._sorted[0] if self._n > 0 else float('nan')
        frac = n_tail - lo
        tail_sum = sum(self._sorted[:lo])
        if lo < self._n and frac > 0:
            tail_sum += frac * self._sorted[lo]
        denom = n_tail if n_tail > 0 else 1
        return tail_sum / denom

    def _evt_cvar(self, alpha: float):
        """EVT GPD 外推 CVaR。下尾取负法：CVaR_X(p) = -CVaR_Y(1-p)。"""
        if self._count_distinct() < 20:
            return None  # 退化/近退化数据，GPD 拟合无意义
        from .evt_tail import fit_gpd_lower, evt_cvar_right

        if self._evt_lower is None:
            self._evt_lower = fit_gpd_lower(self._samples)
        if self._evt_lower is None:
            return None
        xi, beta, u_Y, phi = self._evt_lower
        q_y = 1.0 - alpha
        cvar_y = evt_cvar_right(q_y, xi, beta, u_Y, phi)
        if cvar_y is None:
            return None
        return -cvar_y

    def var_mean_diff(self, alpha: float = 0.05) -> float:
        return self.var(alpha) - self.mean()

    def var_median_diff(self, alpha: float = 0.05) -> float:
        return self.var(alpha) - self.median()

    def cdf(self, x: float) -> float:
        if self._n == 0:
            return float('nan')
        lo, hi = 0, self._n
        while lo < hi:
            mid = (lo + hi) // 2
            if self._sorted[mid] <= x:
                lo = mid + 1
            else:
                hi = mid
        return lo / self._n

    def probability_above(self, threshold: float) -> float:
        return 1.0 - self.cdf(threshold)

    def probability_below(self, threshold: float) -> float:
        return self.cdf(threshold)

    def conditional(self, predicate: Callable[[float], bool]) -> 'EmpiricalDistribution':
        filtered = [x for x in self._samples if predicate(x)]
        return EmpiricalDistribution(filtered)

    def conditional_below(self, threshold: float) -> 'EmpiricalDistribution':
        filtered = [x for x in self._sorted if x <= threshold]
        return EmpiricalDistribution(filtered)

    def conditional_above(self, threshold: float) -> 'EmpiricalDistribution':
        filtered = [x for x in self._sorted if x >= threshold]
        return EmpiricalDistribution(filtered)

    def conditional_bottom_alpha(self, alpha: float = 0.05) -> 'EmpiricalDistribution':
        cutoff = int(math.ceil(alpha * self._n))
        if cutoff == 0:
            cutoff = 1
        return EmpiricalDistribution(self._sorted[:cutoff])

    def conditional_top_alpha(self, alpha: float = 0.05) -> 'EmpiricalDistribution':
        cutoff = int(math.ceil(alpha * self._n))
        if cutoff == 0:
            cutoff = 1
        return EmpiricalDistribution(self._sorted[-cutoff:])

    def summary(self, quantile_levels: Optional[List[float]] = None) -> DistributionSummary:
        if quantile_levels is None:
            quantile_levels = [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99]
        qdict = {p: self.quantile(p) for p in quantile_levels}
        return DistributionSummary(
            mean=self.mean(),
            median=self.median(),
            std=self.std(),
            min_val=self.min_val(),
            max_val=self.max_val(),
            sample_count=self._n,
            quantiles=qdict,
        )

    @staticmethod
    def from_gdr(histories, gdr_func: Callable, ctx) -> 'EmpiricalDistribution':
        values = [gdr_func(h, ctx) for h in histories]
        return EmpiricalDistribution(values)

    @staticmethod
    def from_resource_remaining(histories, ctx, resource: str = 'draw_resource') -> 'EmpiricalDistribution':
        from .gdr import resource_remaining
        values = [resource_remaining(h, ctx, resource) for h in histories]
        return EmpiricalDistribution(values)

    @staticmethod
    def from_batch(histories, value_func: Callable) -> 'EmpiricalDistribution':
        values = [value_func(h) for h in histories]
        return EmpiricalDistribution(values)


class WorstCaseAnalysis:
    def __init__(self, dist: EmpiricalDistribution, alpha: float = 0.05):
        self.dist = dist
        self.alpha = alpha

    def var(self) -> float:
        return self.dist.var(self.alpha)

    def cvar(self) -> float:
        return self.dist.cvar(self.alpha)

    def var_mean_diff(self) -> float:
        return self.dist.var_mean_diff(self.alpha)

    def var_median_diff(self) -> float:
        return self.dist.var_median_diff(self.alpha)

    def conditional_tail(self) -> EmpiricalDistribution:
        return self.dist.conditional_bottom_alpha(self.alpha)

    def report(self) -> Dict[str, float]:
        return {
            f'VaR({self.alpha})': self.var(),
            f'CVaR({self.alpha})': self.cvar(),
            f'VaR-均值差': self.var_mean_diff(),
            f'VaR-中位数差': self.var_median_diff(),
            '均值': self.dist.mean(),
            '中位数': self.dist.median(),
            '标准差': self.dist.std(),
        }


class BestCaseAnalysis:
    def __init__(self, dist: EmpiricalDistribution, alpha: float = 0.05):
        self.dist = dist
        self.alpha = alpha

    def upper_quantile(self) -> float:
        return self.dist.quantile(1 - self.alpha)

    def conditional_top(self) -> EmpiricalDistribution:
        return self.dist.conditional_top_alpha(self.alpha)

    def report(self) -> Dict[str, float]:
        return {
            f'上{1-self.alpha}分位数': self.upper_quantile(),
            '均值': self.dist.mean(),
            '中位数': self.dist.median(),
        }


def freedman_diaconis_bins(data, min_bins: int = 5, max_bins: int = 200) -> int:
    """Freedman-Diaconis 规则自适应 Bin 宽度: bin_width = 2 * IQR * n^(-1/3)"""
    import numpy as np
    n = len(data)
    if n < 2:
        return 1
    q75, q25 = np.percentile(data, [75, 25])
    iqr = q75 - q25
    if iqr == 0:
        return int(np.ceil(np.log2(n) + 1))
    bin_width = 2.0 * iqr / (n ** (1.0 / 3.0))
    data_range = max(data) - min(data)
    n_bins = int(np.ceil(data_range / bin_width)) if bin_width > 0 else 1
    return max(min_bins, min(max_bins, n_bins))
