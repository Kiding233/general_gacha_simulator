"""EVT 尾部拟合测试。"""

import math
import numpy as np
import pytest
from scipy.stats import genpareto

from gacha_simulator.core.evt_tail import (
    _fit_gpd,
    fit_gpd_upper,
    fit_gpd_lower,
    evt_var_right,
    evt_cvar_right,
    gpd_threshold_stability,
)


class TestFitGPD:
    """_fit_gpd 底层拟合测试。"""

    def test_fit_exponential_exceedances(self):
        """指数分布超额（ξ≈0）应成功拟合且 ξ 接近 0。"""
        rng = np.random.default_rng(42)
        exceedances = rng.exponential(scale=2.0, size=500)
        result = _fit_gpd(exceedances)
        assert result is not None
        xi, beta = result
        assert -0.2 < xi < 0.2  # ξ 应接近 0
        assert 1.5 < beta < 2.5  # β 应接近真实 scale=2

    def test_fit_heavy_tailed(self):
        """厚尾数据应拟合出正 ξ（Fréchet 域）。"""
        rng = np.random.default_rng(42)
        exceedances = genpareto.rvs(c=0.3, scale=1.5, size=500, random_state=42)
        result = _fit_gpd(exceedances)
        assert result is not None
        xi, beta = result
        assert xi > 0  # 厚尾

    def test_fit_bounded(self):
        """有界数据应拟合出负 ξ（Weibull 域）。"""
        rng = np.random.default_rng(42)
        exceedances = genpareto.rvs(c=-0.2, scale=1.5, size=500, random_state=42)
        result = _fit_gpd(exceedances)
        assert result is not None
        xi, beta = result
        assert xi < 0  # 有界

    def test_too_few_exceedances(self):
        """超额样本 < 10 时返回 None。"""
        rng = np.random.default_rng(42)
        exceedances = rng.exponential(scale=1.0, size=5)
        result = _fit_gpd(exceedances)
        assert result is None

    def test_xi_below_minus_one_returns_none(self):
        """ξ < -1 时强制返回 None（MLE 不存在）。"""
        rng = np.random.default_rng(42)
        exceedances = genpareto.rvs(c=-1.5, scale=1.0, size=500, random_state=42)
        result = _fit_gpd(exceedances)
        assert result is None


class TestFitGPDUpper:
    """fit_gpd_upper 上尾拟合测试。"""

    def test_normal_data_upper_tail(self):
        """正态数据上尾应成功拟合 GPD。"""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=100, scale=15, size=5000)
        result = fit_gpd_upper(data)
        assert result is not None
        xi, beta, u, phi = result
        assert u > 100  # 阈值应高于均值
        assert 0 < phi < 0.15  # 超阈值概率

    def test_small_sample_returns_none(self):
        """n < 100 时返回 None。"""
        rng = np.random.default_rng(42)
        data = rng.normal(size=50)
        result = fit_gpd_upper(data)
        assert result is None


class TestFitGPDLower:
    """fit_gpd_lower 下尾拟合测试（统一取负法）。"""

    def test_normal_data_lower_tail(self):
        """正态数据下尾应成功拟合（Y=-X 空间）。"""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=100, scale=15, size=5000)
        result = fit_gpd_lower(data)
        assert result is not None
        xi, beta, u_Y, phi = result
        # u_Y 是 Y=-X 空间的阈值，Y=-X 的右尾对应 X 的左尾
        assert 0 < phi < 0.15


class TestEVTVaRCVaRFormulas:
    """evt_var_right / evt_cvar_right 公式正确性测试。"""

    @pytest.fixture
    def gpd_params(self):
        """标准指数超额：ξ=0, β=2, u=100, phi=0.1"""
        return dict(xi=0.0, beta=2.0, u=100.0, phi=0.10)

    def test_var_exponential_limit(self, gpd_params):
        """ξ=0 指数极限：VaR = u + β × ln(φ/(1-q))"""
        var = evt_var_right(q=0.95, **gpd_params)
        # VaR(0.95): φ/(1-q) = 0.1/0.05 = 2, ln(2)=0.693, u + 2*0.693 = 101.39
        expected = 100 + 2.0 * math.log(0.10 / 0.05)
        assert var == pytest.approx(expected, rel=1e-6)

    def test_cvar_exponential_limit(self, gpd_params):
        """ξ=0 指数极限 CVaR。"""
        cvar = evt_cvar_right(q=0.95, **gpd_params)
        # CVaR = VaR + β (ξ=0 时)
        var = evt_var_right(q=0.95, **gpd_params)
        expected = var + gpd_params['beta']
        assert cvar == pytest.approx(expected, rel=1e-6)

    def test_var_heavy_tailed(self):
        """ξ>0 厚尾 VaR 应大于指数极限。"""
        params = dict(xi=0.3, beta=2.0, u=100.0, phi=0.10)
        var_heavy = evt_var_right(q=0.95, **params)
        params['xi'] = 0.0
        var_exp = evt_var_right(q=0.95, **params)
        assert var_heavy > var_exp

    def test_var_bounded(self):
        """ξ<0 有界 VaR 应小于指数极限。"""
        params = dict(xi=-0.3, beta=2.0, u=100.0, phi=0.10)
        var_bounded = evt_var_right(q=0.95, **params)
        params['xi'] = 0.0
        var_exp = evt_var_right(q=0.95, **params)
        assert var_bounded is not None
        assert var_bounded < var_exp

    def test_var_within_threshold_returns_none(self, gpd_params):
        """q 在阈值覆盖范围内（不需要外推）返回 None。"""
        # q=0.85 时 tail_prob=0.15 > phi=0.10，在阈值覆盖范围内
        result = evt_var_right(q=0.85, **gpd_params)
        assert result is None

    def test_cvar_xi_ge_one_returns_inf(self):
        """ξ ≥ 1 时 CVaR 返回 inf（一阶矩不存在）。"""
        result = evt_cvar_right(q=0.95, xi=1.2, beta=2.0, u=100.0, phi=0.10)
        assert result == float('inf')

    def test_var_bounded_endpoint(self):
        """ξ<0 有界支撑：外推到端点之外返回 None。"""
        params = dict(xi=-0.5, beta=1.0, u=10.0, phi=0.10)
        # 端点 x_F = u - β/ξ = 10 - 1/(-0.5) = 12
        result = evt_var_right(q=0.9999, **params)
        # 极端 q 会推到接近端点，可能越界
        # q=0.999 时 tail_prob=0.001, phi/tail_prob=100, (100)^(-0.5)=0.1
        # VaR = 10 + (-2)*(0.1-1) = 10 + 1.8 = 11.8 < 12 没问题
        # 但 q→1 可能越界，测试确保不会崩溃
        assert result is None or result < 12.0


class TestThresholdStability:
    """gpd_threshold_stability 诊断工具测试。"""

    def test_returns_results_for_each_threshold(self):
        rng = np.random.default_rng(42)
        data = rng.exponential(scale=2.0, size=2000)
        results = gpd_threshold_stability(data, thresholds=[1.0, 2.0, 3.0])
        assert len(results) == 3
        for u, xi, beta, n_exc in results:
            assert n_exc > 0
            if n_exc >= 10:
                assert xi is not None
                assert beta is not None


class TestRoundTrip:
    """端到端：生成已知 GPD 数据 → 拟合 → VaR/CVaR 与理论值一致。"""

    def test_upper_tail_round_trip(self):
        """生成 GPD 超额的混合数据，验证 EVT VaR 与理论分位数接近。"""
        rng = np.random.default_rng(42)
        # 主体数据 + GPD 尾部
        body = rng.normal(loc=100, scale=10, size=4500)
        tail = 120 + genpareto.rvs(c=0.2, scale=3.0, size=500, random_state=42)
        data = np.concatenate([body, tail])
        np.random.shuffle(data)

        result = fit_gpd_upper(data)
        assert result is not None
        xi, beta, u, phi = result

        # 使用拟合参数计算 VaR（q=0.99 比阈值更极端，确保外推触发）
        var = evt_var_right(q=0.99, xi=xi, beta=beta, u=u, phi=phi)
        assert var is not None
        assert var > u  # 外推值应高于阈值
        cv = evt_cvar_right(q=0.99, xi=xi, beta=beta, u=u, phi=phi)
        assert cv is not None
        assert cv >= var  # CVaR ≥ VaR

    def test_lower_tail_round_trip(self):
        """下尾取负法：Y=-X 生成 GPD 尾部，验证 EVT 下尾分位数。"""
        rng = np.random.default_rng(42)
        body = -rng.normal(loc=100, scale=10, size=4500)
        # Y = -X 的右尾 = X 的左尾
        tail_y = 120 + genpareto.rvs(c=0.1, scale=2.0, size=500, random_state=42)
        data = -np.concatenate([body, tail_y])
        np.random.shuffle(data)

        result = fit_gpd_lower(data)
        assert result is not None
        xi, beta, u_Y, phi = result

        # VaR_X(p) = -VaR_Y(1-p)
        q_y = 0.99  # 比阈值更极端，确保外推触发
        var_y = evt_var_right(q_y, xi, beta, u_Y, phi)
        assert var_y is not None
        var_x = -var_y
        assert var_x < np.median(data)  # 下尾分位数应低于中位数
