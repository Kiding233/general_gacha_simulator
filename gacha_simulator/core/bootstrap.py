"""Bootstrap 稳定性分析引擎。

对已有的 N 条模拟结果做有放回抽样，零额外模拟成本。
支持标准百分位法、BCa 偏差校正、m-out-of-n 厚尾回退、参数 GPD 尾部 Bootstrap。
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

import numpy as np
from scipy.stats import bootstrap as _scipy_bootstrap
from scipy.stats import genpareto


@dataclass
class BootstrapResult:
    """Bootstrap 置信区间结果。"""
    point_estimate: float
    ci_lower: float
    ci_upper: float
    bootstrap_std: float
    method: str = 'percentile'
    n_samples: int = 0
    b_replicates: int = 0

    def format_ci(self, precision: int = 3) -> str:
        """格式化为「点估计 [下界, 上界]」。"""
        fmt = f"{{:.{precision}f}}"
        return f"{fmt.format(self.point_estimate)} [{fmt.format(self.ci_lower)}, {fmt.format(self.ci_upper)}]"


class BootstrapEngine:
    """Bootstrap 重抽样引擎。

    Parameters
    ----------
    B : int
        重抽样次数，默认 1000。
    ci_level : float
        置信水平，默认 0.95。
    random_seed : int
        随机种子，保证可复现。
    """

    def __init__(self, B: int = 1000, ci_level: float = 0.95,
                 random_seed: int = 42):
        self.B = B
        self.ci_level = ci_level
        self._rng = np.random.default_rng(random_seed)
        self._alpha = 1.0 - ci_level
        self._alpha_low = self._alpha / 2.0
        self._alpha_high = 1.0 - self._alpha_low

    # ── 内部工具 ──────────────────────────────────────────────

    def _percentile_ci(self, replicates: np.ndarray, point_est: float = None
                       ) -> Tuple[float, float, float, float]:
        """百分位法置信区间。"""
        if point_est is None:
            point_est = float(np.mean(replicates))
        low = float(np.percentile(replicates, self._alpha_low * 100))
        high = float(np.percentile(replicates, self._alpha_high * 100))
        std = float(np.std(replicates, ddof=1))
        return point_est, low, high, std

    @staticmethod
    def _from_scipy_result(scipy_res, point_est: float, method: str,
                           n: int, B: int) -> BootstrapResult:
        """将 scipy BootstrapResult 转换为项目 BootstrapResult。"""
        ci_low, ci_high = scipy_res.confidence_interval
        se = scipy_res.standard_error
        return BootstrapResult(
            point_est, float(ci_low), float(ci_high),
            float(se) if se is not None else 0.0, method, n, B)

    # ── 公开方法 ──────────────────────────────────────────────

    def bootstrap_probability(self, success_flags: Union[List[bool], np.ndarray],
                              use_bca: bool = True) -> BootstrapResult:
        """二分类成功概率的 Bootstrap CI。

        Parameters
        ----------
        success_flags : list[bool] 或 ndarray
            每条模拟的成功/失败标志。
        use_bca : bool
            是否使用 BCa 校正（推荐，处理近 0/1 边界偏差）。

        Returns
        -------
        BootstrapResult
        """
        data = np.asarray(success_flags, dtype=bool)
        n = len(data)
        if n == 0:
            return BootstrapResult(float('nan'), float('nan'), float('nan'),
                                   0.0, 'percentile', 0, self.B)
        point_est = float(np.mean(data))

        if use_bca and 0.0 < point_est < 1.0:
            try:
                scipy_res = _scipy_bootstrap(
                    (data.astype(np.float64),), np.mean,
                    n_resamples=self.B, confidence_level=self.ci_level,
                    method='BCa', random_state=self._rng)
                return self._from_scipy_result(scipy_res, point_est, 'BCa', n, self.B)
            except Exception:
                pass

        scipy_res = _scipy_bootstrap(
            (data.astype(np.float64),), np.mean,
            n_resamples=self.B, confidence_level=self.ci_level,
            method='percentile', random_state=self._rng)
        return self._from_scipy_result(scipy_res, point_est, 'percentile', n, self.B)

    def bootstrap_mean(self, values: Union[List[float], np.ndarray],
                       use_bca: bool = True,
                       auto_heavy_tail: bool = False) -> BootstrapResult:
        """连续量均值的 Bootstrap CI。

        Parameters
        ----------
        values : list[float] 或 ndarray
            每条模拟的连续量值。
        use_bca : bool
            是否使用 BCa 校正。

        Returns
        -------
        BootstrapResult
        """
        data = np.asarray(values, dtype=np.float64)
        n = len(data)
        if n == 0:
            return BootstrapResult(float('nan'), float('nan'), float('nan'),
                                   0.0, 'percentile', 0, self.B)
        point_est = float(np.mean(data))

        if auto_heavy_tail:
            ht = self.detect_heavy_tail(data)
            if ht['heavy_tail']:
                m = self._select_m(n)
                return self._bootstrap_mean_m_out_of_n(data, m)

        if use_bca:
            try:
                scipy_res = _scipy_bootstrap(
                    (data,), np.mean,
                    n_resamples=self.B, confidence_level=self.ci_level,
                    method='BCa', random_state=self._rng)
                return self._from_scipy_result(scipy_res, point_est, 'BCa', n, self.B)
            except Exception:
                pass

        scipy_res = _scipy_bootstrap(
            (data,), np.mean,
            n_resamples=self.B, confidence_level=self.ci_level,
            method='percentile', random_state=self._rng)
        return self._from_scipy_result(scipy_res, point_est, 'percentile', n, self.B)

    def bootstrap_quantile(self, values: Union[List[float], np.ndarray],
                           q: float = 0.5, use_gpd: bool = False,
                           auto_heavy_tail: bool = False,
                           ) -> BootstrapResult:
        """分位数的 Bootstrap CI。

        Parameters
        ----------
        values : list[float] 或 ndarray
            连续量样本。
        q : float
            目标分位数（0-1）。
        use_gpd : bool
            尾部低分位数 (q<0.1) 使用参数 GPD Bootstrap，否则使用标准百分位法。

        Returns
        -------
        BootstrapResult
        """
        data = np.asarray(values, dtype=np.float64)
        n = len(data)
        if n == 0:
            return BootstrapResult(float('nan'), float('nan'), float('nan'),
                                   0.0, 'percentile', 0, self.B)
        point_est = float(np.quantile(data, q))

        if auto_heavy_tail:
            ht = self.detect_heavy_tail(data)
            if ht['heavy_tail'] and q <= 0.1:
                use_gpd = True

        if use_gpd and q <= 0.1:
            return self._bootstrap_tail_gpd(data, q)

        def _quantile_stat(x):
            return float(np.quantile(x, q))

        scipy_res = _scipy_bootstrap(
            (data,), _quantile_stat,
            n_resamples=self.B, confidence_level=self.ci_level,
            method='percentile', random_state=self._rng)
        return self._from_scipy_result(scipy_res, point_est, 'percentile', n, self.B)

    def _bootstrap_tail_gpd(self, data: np.ndarray, q: float) -> BootstrapResult:
        """参数 Bootstrap：从 GPD 拟合抽样估计分位数 CI。

        对尾部低分位数（如 VaR_0.05），标准 Bootstrap 因尾部稀疏不可靠。
        从拟合的 GPD 分布中抽样 B 次，计算每次的分位数。
        """
        n = len(data)
        u = float(np.quantile(data, 0.2))
        excess = data[data <= u] - u
        if len(excess) < 20:
            return self.bootstrap_quantile(data, q, use_gpd=False)

        try:
            shape, loc, scale = genpareto.fit(-excess, floc=0)
        except Exception:
            return self.bootstrap_quantile(data, q, use_gpd=False)

        point_est = float(np.quantile(data, q))
        n_excess = len(excess)
        n_total = len(data)
        boot_quants = np.zeros(self.B)

        for b in range(self.B):
            exc_sample = genpareto.rvs(shape, loc=loc, scale=scale, size=n_excess)
            exc_sample = -exc_sample + u
            non_exc = self._rng.choice(data[data > u], size=n_total - n_excess, replace=True)
            boot_sample = np.concatenate([exc_sample, non_exc])
            boot_quants[b] = float(np.quantile(boot_sample, q))

        _, ci_low, ci_high, std = self._percentile_ci(boot_quants, point_est)
        return BootstrapResult(point_est, ci_low, ci_high, std,
                               'GPD-param', n, self.B)

    @staticmethod
    def _select_m(n: int) -> int:
        """m-out-of-n bootstrap 的 m 选择 (Bickel & Sakov 2008)。

        m = n^(2/3) 兼顾偏差缩减与方差控制，厚尾时比标准 Bootstrap 更稳健。
        """
        return max(20, int(n ** (2.0 / 3.0)))

    def _bootstrap_mean_m_out_of_n(self, data: np.ndarray, m: int
                                   ) -> BootstrapResult:
        """m-out-of-n Bootstrap 均值——厚尾分布下的一致性估计。

        m-out-of-n 对无限方差分布（α<2）给出渐近正确的抽样分布，
        无需方差缩放（因为 CLT 的 √n 收敛率在厚尾下不成立）。
        """
        n = len(data)
        point_est = float(np.mean(data))
        indices = self._rng.integers(0, n, size=(self.B, m))
        boot_means = np.mean(data[indices], axis=1)
        _, ci_low, ci_high, std = self._percentile_ci(boot_means, point_est)
        alpha = self.hill_estimator(data)
        return BootstrapResult(point_est, ci_low, ci_high, std,
                               f'm-out-of-n (m={m}, auto: heavy tail α={alpha:.2f})',
                               n, self.B)

    def hill_estimator(self, values: Union[List[float], np.ndarray],
                       k: int = None) -> float:
        """Hill 尾部指数估计量 (Hill 1975)。

        α > 2 表示有限方差（标准 Bootstrap 安全）；
        α < 2 表示厚尾（建议 m-out-of-n 或参数 Bootstrap）。

        k 为 None 时自动选择——在 Hill 图上搜索稳定区域（拐点检测）。
        """
        data = np.asarray(values, dtype=np.float64)
        data = data[data > 0]  # Hill 估计量仅适用于正数数据
        n = len(data)
        if n < 20:
            return float('inf')
        if k is None:
            k = self._select_hill_k(data)
        k = max(5, min(k, n // 5))
        sorted_data = np.sort(data)[::-1]
        threshold = sorted_data[k]
        log_ratios = np.log(sorted_data[:k]) - np.log(threshold)
        log_ratios = log_ratios[log_ratios > 1e-15]
        if len(log_ratios) < 3:
            return float('inf')
        return float(len(log_ratios) / np.sum(log_ratios))

    def _select_hill_k(self, data: np.ndarray) -> int:
        """Hill 图拐点检测——选择使 α 估计最稳定的 k。

        在 k ∈ [k_min, k_max] 范围内计算 Hill α，选择一阶差分绝对值
        最小区域的中位 k 作为最优顺序统计量个数。
        """
        n = len(data)
        k_max = n // 5
        k_min = max(10, int(math.sqrt(n)) // 2)
        if k_max <= k_min:
            return int(math.sqrt(n))

        n_grid = min(30, k_max - k_min)
        ks = np.linspace(k_min, k_max, n_grid, dtype=int)
        ks = np.unique(np.clip(ks, k_min, k_max))
        if len(ks) < 5:
            return int(math.sqrt(n))

        sorted_data = np.sort(data)[::-1]
        alphas = np.full(len(ks), float('inf'))
        for j, kval in enumerate(ks):
            threshold = sorted_data[kval]
            log_ratios = np.log(sorted_data[:kval]) - np.log(threshold)
            log_ratios = log_ratios[log_ratios > 1e-15]
            if len(log_ratios) >= 3:
                alphas[j] = float(len(log_ratios) / np.sum(log_ratios))

        diffs = np.abs(np.diff(alphas))
        finite_mask = np.isfinite(diffs)
        if not np.any(finite_mask):
            return int(math.sqrt(n))

        # 在前半段（倾向较小 k）选择最稳定的区域
        half = max(3, len(diffs) // 2)
        valid_diffs = diffs[:half].copy()
        valid_diffs[~finite_mask[:half]] = float('inf')
        best_idx = int(np.argmin(valid_diffs))
        return int(ks[best_idx])

    def detect_heavy_tail(self, values: Union[List[float], np.ndarray],
                          k: int = None) -> dict:
        """厚尾检测：返回 Hill α 估计 + 建议方法。

        Returns
        -------
        dict
            {'alpha': float, 'heavy_tail': bool, 'recommendation': str}
        """
        alpha = self.hill_estimator(values, k)
        heavy = alpha < 2.0
        if heavy:
            rec = 'm-out-of-n 或参数 GPD Bootstrap 推荐'
        else:
            rec = '标准 Bootstrap + BCa 安全'
        return {'alpha': alpha, 'heavy_tail': heavy, 'recommendation': rec}

    def total_variation_distance(self, p: dict, q: dict) -> float:
        """两个离散概率分布的总变差距离。

        TVD(P, Q) = (1/2) Σ_x |P(x) - Q(x)|
        """
        all_keys = set(p.keys()) | set(q.keys())
        diff_sum = sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in all_keys)
        return 0.5 * diff_sum
