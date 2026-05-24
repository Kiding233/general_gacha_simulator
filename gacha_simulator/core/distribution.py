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

    @property
    def n(self) -> int:
        return self._n

    @property
    def samples(self) -> List[float]:
        return list(self._samples)

    def mean(self) -> float:
        if self._n == 0:
            return 0.0
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
        return self._sorted[0] if self._n > 0 else 0.0

    def max_val(self) -> float:
        return self._sorted[-1] if self._n > 0 else 0.0

    def quantile(self, p: float) -> float:
        if self._n == 0:
            return 0.0
        if p <= 0:
            return self._sorted[0]
        if p >= 1:
            return self._sorted[-1]
        idx = p * (self._n - 1)
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return self._sorted[lo]
        frac = idx - lo
        return self._sorted[lo] * (1 - frac) + self._sorted[hi] * frac

    def var(self, alpha: float = 0.05) -> float:
        return self.quantile(alpha)

    def cvar(self, alpha: float = 0.05) -> float:
        if self._n == 0:
            return 0.0
        cutoff = int(math.ceil(alpha * self._n))
        if cutoff == 0:
            cutoff = 1
        tail = self._sorted[:cutoff]
        return sum(tail) / len(tail)

    def var_mean_diff(self, alpha: float = 0.05) -> float:
        return self.var(alpha) - self.mean()

    def var_median_diff(self, alpha: float = 0.05) -> float:
        return self.var(alpha) - self.median()

    def cdf(self, x: float) -> float:
        if self._n == 0:
            return 0.0
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
