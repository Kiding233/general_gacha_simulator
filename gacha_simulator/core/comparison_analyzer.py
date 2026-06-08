"""比较分析引擎——L1 描述统计 / L2 DD Bootstrap / L3 假设检验 / L4 帕累托前沿"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy import stats as sp_stats


@dataclass
class DescriptiveStats:
    """L1 描述统计——单数据集单 GDR 的摘要"""
    name: str
    gdr_key: str
    mean: float
    median: float
    std: float
    skewness: float
    kurtosis: float
    var_05: float
    cvar_05: float
    success_rate: float
    min_val: float
    max_val: float
    n: int

    @classmethod
    def compute(cls, name: str, gdr_key: str, values: np.ndarray,
                threshold: float, lower_is_better: bool = False) -> DescriptiveStats:
        n = len(values)
        if n == 0:
            return cls(name=name, gdr_key=gdr_key, mean=float('nan'),
                       median=float('nan'), std=float('nan'), skewness=float('nan'),
                       kurtosis=float('nan'), var_05=float('nan'), cvar_05=float('nan'),
                       success_rate=float('nan'),
                       min_val=float('nan'), max_val=float('nan'), n=0)

        mean_v = float(np.mean(values))
        median_v = float(np.median(values))
        std_v = float(np.std(values, ddof=1)) if n > 1 else 0.0
        # 偏度：Fisher-Pearson 标准化矩
        if std_v > 1e-15 and n > 2:
            skewness_v = float(sp_stats.skew(values, bias=False))
            kurtosis_v = float(sp_stats.kurtosis(values, bias=False))
        else:
            skewness_v = 0.0
            kurtosis_v = 0.0

        # VaR₀.₀₅（5% 分位数） + CVaR₀.₀₅（尾部条件均值）
        alpha = 0.05
        sorted_v = np.sort(values)
        if lower_is_better:
            tail = sorted_v[-int(n * alpha):] if n > 1 else values
            cvar_v = float(np.mean(tail))
            var_v = float(sorted_v[-max(1, int(n * alpha))])
        else:
            tail = sorted_v[:max(1, int(n * alpha))]
            cvar_v = float(np.mean(tail))
            var_v = float(sorted_v[max(0, int(n * alpha) - 1)])

        # 成功率
        if lower_is_better:
            success_count = np.sum(values <= threshold)
        else:
            success_count = np.sum(values >= threshold)
        success_rate_v = float(success_count / n)

        return cls(
            name=name, gdr_key=gdr_key,
            mean=mean_v, median=median_v, std=std_v,
            skewness=skewness_v, kurtosis=kurtosis_v,
            var_05=var_v, cvar_05=cvar_v,
            success_rate=success_rate_v,
            min_val=float(np.min(values)), max_val=float(np.max(values)),
            n=n,
        )


def compute_gdr_values_for_datasets(
    datasets: List[Any],     # List[StoredDataset]
    gdr_key: str,
    target_specs_list: List[Dict[str, int]],
    threshold: float = 1.0,
) -> Tuple[List[np.ndarray], List[str], bool]:
    """从多个数据集提取指定 GDR 的逐次模拟值。

    返回: (values_list, names_list, lower_is_better)
    """
    from gacha_simulator.core.gdr import UNIFIED_GDR_REGISTRY

    defn = UNIFIED_GDR_REGISTRY.get(gdr_key)
    if defn is None:
        return [], [], False

    lower_is_better = defn.lower_is_better
    names = []
    values_list = []

    for ds, specs in zip(datasets, target_specs_list):
        vals = []
        for compact in ds.aggregate_data:
            if compact is None:
                continue
            v = defn.compute_from_compact(compact, target_specs=specs)
            if not np.isnan(v):
                vals.append(v)
        names.append(ds.name)
        values_list.append(np.array(vals, dtype=float))

    return values_list, names, lower_is_better


@dataclass
class ParetoFrontier:
    """L4 双 GDR 帕累托前沿"""
    x_gdr: str
    y_gdr: str
    points: List[Dict[str, Any]] = field(default_factory=list)
    frontier_indices: List[int] = field(default_factory=list)
    dominated_indices: List[int] = field(default_factory=list)

    @classmethod
    def compute(cls,
                x_values: List[np.ndarray],
                y_values: List[np.ndarray],
                names: List[str],
                x_gdr: str, y_gdr: str,
                x_lower_is_better: bool = False,
                y_lower_is_better: bool = False,
                ) -> ParetoFrontier:
        """计算帕累托前沿。x_lower_is_better=True 时对该维取反。"""
        n = len(names)
        # 构建坐标（越大越好）
        xs = np.array([np.mean(v) for v in x_values])
        ys = np.array([np.mean(v) for v in y_values])
        if x_lower_is_better:
            xs = -xs
        if y_lower_is_better:
            ys = -ys

        points = []
        for i in range(n):
            points.append({
                'name': names[i],
                'x': float(xs[i]),
                'x_raw': float(np.mean(x_values[i])),
                'y': float(ys[i]),
                'y_raw': float(np.mean(y_values[i])),
                'x_std': float(np.std(x_values[i], ddof=1)) if len(x_values[i]) > 1 else 0.0,
                'y_std': float(np.std(y_values[i], ddof=1)) if len(y_values[i]) > 1 else 0.0,
            })

        # 帕累托前沿：不被任何其他点同时在两维上严格支配
        is_dominated = [False] * n
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                if xs[j] >= xs[i] and ys[j] >= ys[i] and (xs[j] > xs[i] or ys[j] > ys[i]):
                    is_dominated[i] = True
                    break

        frontier_indices = [i for i, d in enumerate(is_dominated) if not d]
        dominated_indices = [i for i, d in enumerate(is_dominated) if d]

        # 前沿按 x 排序
        frontier_indices.sort(key=lambda i: points[i]['x'])

        return cls(
            x_gdr=x_gdr, y_gdr=y_gdr,
            points=points,
            frontier_indices=frontier_indices,
            dominated_indices=dominated_indices,
        )


def dd_bootstrap_test(
    samples_a: np.ndarray,
    samples_b: np.ndarray,
    order: int = 1,
    n_bootstrap: int = 2000,
    rng_seed: int = 42,
) -> Dict[str, Any]:
    """Davidson-Duclos Bootstrap 随机占优检验。

    H₀: A 不 j 阶占优 B (A 的 j 阶积分 CDF 不总是 ≤ B 的 j 阶积分 CDF)
    拒绝 H₀ ⇒ A j 阶随机占优 B

    Args:
        samples_a: 策略 A 的样本
        samples_b: 策略 B 的样本
        order: 占优阶数 (1=FSD, 2=SSD, 3=TSD)
        n_bootstrap: Bootstrap 重抽样次数
        rng_seed: 随机种子

    Returns:
        dict with keys: p_value, observed_max_diff, bootstrap_diffs, order, n_bootstrap
    """
    n_a = len(samples_a)
    n_b = len(samples_b)
    rng = np.random.default_rng(rng_seed)

    # 网格点：自适应样本量
    n_grid = min(200, n_a + n_b)
    combined = np.concatenate([samples_a, samples_b])
    grid = np.linspace(np.min(combined), np.max(combined), n_grid)

    # 经验 CDF
    def ecdf(samples, x):
        return np.mean(samples <= x, axis=-1) if samples.ndim > 1 else np.mean(samples <= x)

    # 构建 j 阶积分 CDF
    def integrated_cdf(samples, x, order):
        F = np.array([ecdf(samples, xi) for xi in x])
        for _ in range(order - 1):
            # 累积梯形积分
            F = np.array([np.trapz(F[:k+1], x[:k+1]) for k in range(len(x))])
        return F

    F_a = integrated_cdf(samples_a, grid, order)
    F_b = integrated_cdf(samples_b, grid, order)

    # 观察到的最大差异 (A 超出 B 的部分)
    diff = F_a - F_b
    observed_max = np.max(diff)

    # Bootstrap: H₀ = A 不占优 B，即 diff 的最大值 ≤ 0
    # 中心化后重抽样
    F_a_centered = F_a - np.mean(F_a)
    F_b_centered = F_b - np.mean(F_b)

    bootstrap_maxes = np.empty(n_bootstrap)
    for b in range(n_bootstrap):
        idx_a = rng.integers(0, n_a, size=n_a)
        idx_b = rng.integers(0, n_b, size=n_b)
        boot_a = integrated_cdf(samples_a[idx_a], grid, order) - F_a_centered
        boot_b = integrated_cdf(samples_b[idx_b], grid, order) - F_b_centered
        bootstrap_maxes[b] = np.max(boot_a - boot_b)

    # p 值：Bootstrap 分布在 H₀ 下观察到 ≥ observed_max 的概率
    p_value = np.mean(bootstrap_maxes >= observed_max)

    return {
        'p_value': float(p_value),
        'observed_max_diff': float(observed_max),
        'bootstrap_diffs': bootstrap_maxes,
        'order': order,
        'n_bootstrap': n_bootstrap,
        'dominates': p_value < 0.05,
    }


def compute_dominance_matrix(
    values_list: List[np.ndarray],
    names: List[str],
    order: int = 1,
    n_bootstrap: int = 2000,
    rng_seed: int = 42,
) -> Dict[str, Any]:
    """计算 n×n j 阶占优矩阵（双向，含下三角）。

    matrix[i][j] = p 值，检验行 i 是否 j 阶随机占优列 j。
    上下三角分别独立 bootstrap——行 i 占优列 j 不等价于列 j 被行 i 占优。

    Returns:
        dict with keys:
            matrix: List[List[Optional[float]]] — p 值矩阵（非对角满）
            dominates: List[List[bool]] — 行是否占优列
            names: List[str]
            order: int
    """
    n = len(names)
    matrix = [[None] * n for _ in range(n)]
    dominates = [[False] * n for _ in range(n)]

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            result = dd_bootstrap_test(
                values_list[i], values_list[j],
                order=order, n_bootstrap=n_bootstrap, rng_seed=rng_seed,
            )
            matrix[i][j] = result['p_value']
            dominates[i][j] = result['dominates']

    # 双向裁决：双方均 p<0.05 → 占优关系不确定（分布交叉或样本噪声），双方均判 False
    for i in range(n):
        for j in range(i + 1, n):
            if dominates[i][j] and dominates[j][i]:
                dominates[i][j] = False
                dominates[j][i] = False

    return {
        'matrix': matrix,
        'dominates': dominates,
        'names': names,
        'order': order,
    }


@dataclass
class HypothesisTestResult:
    """单对比较的假设检验结果"""
    method: str           # 'KS' | 'MWU' | 'ttest'
    statistic: float
    p_value: float
    direction: str        # '↑' (row better) | '↓' (row worse) | '—' (not significant)
    row_better: bool      # 行均值是否优于列均值

    @classmethod
    def from_samples(cls, samples_a: np.ndarray, samples_b: np.ndarray,
                     method: str, lower_is_better: bool = False,
                     alpha: float = 0.05) -> HypothesisTestResult:
        if method == 'KS':
            stat, p = sp_stats.ks_2samp(samples_a, samples_b)
            statistic = float(stat)
        elif method == 'MWU':
            stat, p = sp_stats.mannwhitneyu(samples_a, samples_b, alternative='two-sided')
            statistic = float(stat)
        elif method == 'ttest':
            stat, p = sp_stats.ttest_ind(samples_a, samples_b, equal_var=False)
            statistic = float(stat)
        else:
            raise ValueError(f"Unknown method: {method}")

        p_value = float(p)
        mean_a = np.mean(samples_a)
        mean_b = np.mean(samples_b)

        if p_value >= alpha:
            direction = '—'
            row_better = False
        elif lower_is_better:
            row_better = mean_a < mean_b
            direction = '↑' if row_better else '↓'
        else:
            row_better = mean_a > mean_b
            direction = '↑' if row_better else '↓'

        return cls(method=method, statistic=statistic, p_value=p_value,
                   direction=direction, row_better=row_better)


def holm_bonferroni(p_values: List[float]) -> List[float]:
    """Holm-Bonferroni 校正。返回校正后 p 值（截断到 [0,1]）。"""
    n = len(p_values)
    if n == 0:
        return []
    sorted_idx = np.argsort(p_values)
    corrected = np.ones(n)
    for rank, idx in enumerate(sorted_idx):
        corrected[idx] = min(1.0, p_values[idx] * (n - rank))
    # 单调性约束
    for rank in range(1, n):
        prev_idx = sorted_idx[rank - 1]
        curr_idx = sorted_idx[rank]
        corrected[curr_idx] = max(corrected[curr_idx], corrected[prev_idx])
    return [float(v) for v in corrected]


def benjamini_hochberg(p_values: List[float]) -> List[float]:
    """Benjamini-Hochberg FDR 校正。返回 q 值。"""
    n = len(p_values)
    if n == 0:
        return []
    sorted_idx = np.argsort(p_values)
    corrected = np.ones(n)
    for rank, idx in enumerate(sorted_idx):
        corrected[idx] = min(1.0, p_values[idx] * n / (rank + 1))
    # 单调性约束（从后往前）
    for rank in range(n - 2, -1, -1):
        curr_idx = sorted_idx[rank]
        next_idx = sorted_idx[rank + 1]
        corrected[curr_idx] = min(corrected[curr_idx], corrected[next_idx])
    return [float(v) for v in corrected]


def compute_pvalue_matrix(
    values_list: List[np.ndarray],
    names: List[str],
    method: str = 'MWU',
    lower_is_better: bool = False,
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """计算 n×n p 值矩阵（含三种校正）。

    Returns:
        dict with:
            raw_matrix: p 值
            holm_matrix: Holm-Bonferroni 校正
            bh_matrix: Benjamini-Hochberg 校正
            direction_matrix: '↑' / '↓' / '—'
            names, method, alpha
    """
    n = len(names)
    raw = [[None] * n for _ in range(n)]
    direction = [[''] * n for _ in range(n)]

    all_pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            result = HypothesisTestResult.from_samples(
                values_list[i], values_list[j],
                method=method, lower_is_better=lower_is_better, alpha=alpha,
            )
            raw[i][j] = result.p_value
            direction[i][j] = result.direction
            all_pairs.append((i, j, result.p_value))

    # 提取所有非对角 p 值用于校正
    flat_p = [p for _, _, p in all_pairs if p is not None]
    if flat_p:
        holm_p = holm_bonferroni(flat_p)
        bh_p = benjamini_hochberg(flat_p)
    else:
        holm_p, bh_p = [], []

    holm = [[None] * n for _ in range(n)]
    bh = [[None] * n for _ in range(n)]
    p_idx = 0
    for i, j, _ in all_pairs:
        holm[i][j] = holm_p[p_idx] if p_idx < len(holm_p) else None
        bh[i][j] = bh_p[p_idx] if p_idx < len(bh_p) else None
        p_idx += 1

    return {
        'raw_matrix': raw,
        'holm_matrix': holm,
        'bh_matrix': bh,
        'direction_matrix': direction,
        'names': names,
        'method': method,
        'alpha': alpha,
    }
