from typing import List, Dict, Callable, Optional, Any
from .distribution import EmpiricalDistribution, WorstCaseAnalysis, BestCaseAnalysis
from .gdr import GDRContext, resource_remaining


class RiskAnalyzer:
    def __init__(self, histories: List[list], ctx: GDRContext):
        self.histories = histories
        self.ctx = ctx

    def gdr_distribution(self, gdr_func: Callable, **kwargs) -> EmpiricalDistribution:
        values = [gdr_func(h, self.ctx, **kwargs) for h in self.histories]
        return EmpiricalDistribution(values)

    def resource_remaining_distribution(self, resource: str = 'draw_resource') -> EmpiricalDistribution:
        values = [resource_remaining(h, self.ctx, resource) for h in self.histories]
        return EmpiricalDistribution(values)

    def custom_distribution(self, value_func: Callable) -> EmpiricalDistribution:
        values = [value_func(h) for h in self.histories]
        return EmpiricalDistribution(values)

    def var(self, gdr_func: Callable = None, dist: EmpiricalDistribution = None,
            alpha: float = 0.05, **kwargs) -> float:
        if dist is None:
            dist = self.gdr_distribution(gdr_func, **kwargs)
        return dist.var(alpha)

    def cvar(self, gdr_func: Callable = None, dist: EmpiricalDistribution = None,
             alpha: float = 0.05, **kwargs) -> float:
        if dist is None:
            dist = self.gdr_distribution(gdr_func, **kwargs)
        return dist.cvar(alpha)

    def var_mean_diff(self, gdr_func: Callable = None, dist: EmpiricalDistribution = None,
                      alpha: float = 0.05, **kwargs) -> float:
        if dist is None:
            dist = self.gdr_distribution(gdr_func, **kwargs)
        return dist.var_mean_diff(alpha)

    def var_median_diff(self, gdr_func: Callable = None, dist: EmpiricalDistribution = None,
                        alpha: float = 0.05, **kwargs) -> float:
        if dist is None:
            dist = self.gdr_distribution(gdr_func, **kwargs)
        return dist.var_median_diff(alpha)

    def never_fail_probability(self, gdr_func: Callable = None, threshold: float = 1.0,
                               **kwargs) -> float:
        if gdr_func is None:
            from .gdr import all_targets_obtained
            gdr_func = all_targets_obtained
        dist = self.gdr_distribution(gdr_func, **kwargs)
        return dist.probability_above(threshold - 1e-9)

    def worst_case_analysis(self, gdr_func: Callable = None, dist: EmpiricalDistribution = None,
                            alpha: float = 0.05, **kwargs) -> Dict[str, Any]:
        if dist is None:
            dist = self.gdr_distribution(gdr_func, **kwargs)
        wca = WorstCaseAnalysis(dist, alpha)
        tail_dist = wca.conditional_tail()
        return {
            'VaR': wca.var(),
            'CVaR': wca.cvar(),
            'VaR-均值差': wca.var_mean_diff(),
            'VaR-中位数差': wca.var_median_diff(),
            '均值': dist.mean(),
            '中位数': dist.median(),
            '标准差': dist.std(),
            '最差情形条件分布': tail_dist,
            '最差情形条件均值': tail_dist.mean(),
        }

    def best_case_analysis(self, gdr_func: Callable = None, dist: EmpiricalDistribution = None,
                           alpha: float = 0.05, **kwargs) -> Dict[str, Any]:
        if dist is None:
            dist = self.gdr_distribution(gdr_func, **kwargs)
        bca = BestCaseAnalysis(dist, alpha)
        top_dist = bca.conditional_top()
        return {
            f'上{1-alpha}分位数': bca.upper_quantile(),
            '最好情形条件分布': top_dist,
            '最好情形条件均值': top_dist.mean(),
        }

    def full_report(self, gdr_func: Callable = None, dist: EmpiricalDistribution = None,
                    alpha: float = 0.05, **kwargs) -> Dict[str, Any]:
        if dist is None:
            dist = self.gdr_distribution(gdr_func, **kwargs)
        report = {
            '分布摘要': dist.summary(),
            '最差情形分析': self.worst_case_analysis(dist=dist, alpha=alpha),
            '最好情形分析': self.best_case_analysis(dist=dist, alpha=alpha),
        }
        report['最差情形分析'].pop('最差情形条件分布', None)
        report['最好情形分析'].pop('最好情形条件分布', None)
        return report
