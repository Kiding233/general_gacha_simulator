"""
EVT 尾部拟合 —— 在 EmpiricalDistribution 层集成 GPD 尾部外推。

Pickands-Balkema-de Haan 定理（Balkema & de Haan 1974; Pickands 1975）：
对任何属于极值分布吸引域的分布，当阈值 u → x_F 时，超额分布收敛到
广义 Pareto 分布（GPD）：G(y; σ, ξ) = 1 - (1 + ξy/σ)_+^{-1/ξ}

上尾（p ≥ 0.9）：直接对 X - u | X > u 拟合标准 POT
下尾（p ≤ 0.1）：统一取负法——对 Y = -X 取负后拟合标准 POT，结果回原尺度
"""
from __future__ import annotations

import logging
import warnings
import numpy as np
from scipy.stats import genpareto

logger = logging.getLogger(__name__)


def _fit_gpd(exceedances):
    """对超额值拟合 GPD(ξ, β)，floc=0。

    Args:
        exceedances: 超额值数组（均已减去阈值）

    Returns:
        (ξ, β) | None —— 拟合失败或 MLE 正则性不满足时返回 None
    """
    n_exc = len(exceedances)
    if n_exc < 10:
        return None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            shape, loc, scale = genpareto.fit(exceedances, floc=0)
    except (RuntimeError, ValueError):
        return None

    xi = shape
    beta = scale

    # MLE 正则性检查（Smith 1985）：ξ < -1 时 MLE 不存在
    if xi < -1:
        logger.warning("EVT: ξ=%.3f < -1，MLE 不存在，回退经验分位数", xi)
        return None
    if xi < -0.5:
        logger.warning("EVT: ξ=%.3f ∈ [-1, -0.5)，MLE 渐近性质不成立，点估计仍可用", xi)

    return xi, beta


def fit_gpd_upper(data):
    """上尾 POT：对 X > u 拟合 GPD。

    自适应阈值：target_exc = min(max(n × 0.05, 100), 500)
    —— 保证 100-500 个超额样本，Coles (2001)「阈值尽可能高」原则。

    Args:
        data: 原始数据（1-D array-like）

    Returns:
        (ξ, β, threshold, phi) | None
    """
    x = np.asarray(data, dtype=np.float64)
    n = len(x)
    if n < 100:
        return None

    target_exc = min(max(int(n * 0.05), 100), 500)
    if target_exc >= n:
        return None

    threshold_p = 1.0 - target_exc / n
    u = float(np.quantile(x, threshold_p))
    exceedances = x[x > u] - u
    n_exc = len(exceedances)

    if n_exc < 10:
        return None

    result = _fit_gpd(exceedances)
    if result is None:
        return None

    xi, beta = result
    phi = n_exc / n
    return xi, beta, u, phi


def fit_gpd_lower(data):
    """下尾 POT（统一取负法）：Y = -X，拟合 Y 的上尾 GPD。

    VaR_X(p) = -VaR_Y(1-p)
    CVaR_X(p) = -CVaR_Y(1-p)

    Args:
        data: 原始数据（1-D array-like）

    Returns:
        (ξ, beta, threshold_Y, phi) | None —— threshold_Y 是 Y=-X 空间的阈值
    """
    x = np.asarray(data, dtype=np.float64)
    y = -x
    return fit_gpd_upper(y)


def evt_var_right(q, xi, beta, u, phi):
    """右尾 VaR 统一公式（q 接近 1）。

    对超额值拟合 GPD(ξ, β) 后，右尾分位数：
        VaR(q) = u + β × ln(φ/(1-q))          (|ξ| < 1e-6，指数极限)
               = u + (β/ξ) × [(φ/(1-q))^ξ - 1]  (|ξ| ≥ 1e-6)

    Args:
        q: 目标分位数水平（接近 1，如 0.95）
        xi: GPD shape 参数
        beta: GPD scale 参数
        u: 阈值（原始数据空间）
        phi: 超阈值概率 Nu/n

    Returns:
        VaR(q) | None —— 无需外推或越界时返回 None
    """
    tail_prob = 1.0 - q  # P(X > VaR)

    # q 在阈值覆盖范围内（不够极端），不需要外推
    # 使用容差处理浮点精度：q = 1-φ 时两方法等价，允许通过
    if tail_prob > phi * (1.0 + 1e-12):
        return None

    if abs(xi) < 1e-6:
        var = u + beta * np.log(phi / tail_prob)
    else:
        var = u + (beta / xi) * ((phi / tail_prob) ** xi - 1.0)

    # 有界支撑约束（ξ < 0 时有有限右端点 x_F = u - β/ξ）
    if xi < 0.0:
        endpoint = u - beta / xi
        if var >= endpoint:
            return None

    return float(var)


def evt_cvar_right(q, xi, beta, u, phi):
    """右尾 CVaR 统一公式（q 接近 1）。

    CVaR(q) = VaR(q) + (β + ξ×(VaR(q) - u)) / (1-ξ)  (ξ < 1)
    ξ ≥ 1 时一阶矩不存在，返回 +inf。

    Args:
        q: 目标分位数水平（接近 1，如 0.95）
        xi: GPD shape 参数
        beta: GPD scale 参数
        u: 阈值（原始数据空间）
        phi: 超阈值概率 Nu/n

    Returns:
        CVaR(q) | None
    """
    if xi >= 1.0:
        return float('inf')

    var = evt_var_right(q, xi, beta, u, phi)
    if var is None:
        return None

    cvar = var + (beta + xi * (var - u)) / (1.0 - xi)
    return float(cvar)


def gpd_threshold_stability(data, thresholds):
    """阈值稳定性诊断（可选工具）。

    对多个候选阈值分别拟合 GPD，返回各阈值下的 ξ 和修正尺度 β* = β - ξ×u，
    供手动检查参数稳定性图（Coles 2001, §4.3.4）。

    Args:
        data: 原始数据（1-D array-like）
        thresholds: 候选阈值列表

    Returns:
        [(threshold, xi, beta, n_exc), ...] 每个阈值的结果
    """
    x = np.asarray(data, dtype=np.float64)
    results = []
    for u in thresholds:
        exceedances = x[x > u] - u
        n_exc = len(exceedances)
        if n_exc < 10:
            results.append((u, None, None, n_exc))
            continue
        fit = _fit_gpd(exceedances)
        if fit is None:
            results.append((u, None, None, n_exc))
        else:
            xi, beta = fit
            results.append((u, xi, beta, n_exc))
    return results
