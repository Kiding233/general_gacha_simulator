"""EmpiricalDistribution EVT 集成测试。"""

import numpy as np
import pytest

from gacha_simulator.core.distribution import EmpiricalDistribution


class TestEmpiricalDistributionEVT:
    """quantile / var / cvar 的 EVT 路径测试。"""

    @pytest.fixture
    def large_dist(self):
        """5000 样本的正态分布——足够触发 EVT。"""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=100, scale=15, size=5000)
        return EmpiricalDistribution(list(data))

    @pytest.fixture
    def small_dist(self):
        """50 样本——不触发 EVT。"""
        rng = np.random.default_rng(42)
        data = rng.normal(loc=100, scale=15, size=50)
        return EmpiricalDistribution(list(data))

    def test_extreme_quantile_uses_evt(self, large_dist):
        """p≤0.1 时走 EVT 路径，结果与经验分位数接近。"""
        evt_val = large_dist.quantile(0.05, use_evt=True)
        emp_val = large_dist.quantile(0.05, use_evt=False)
        assert evt_val == pytest.approx(emp_val, rel=0.15)  # 不应偏差过大

    def test_upper_extreme_quantile_uses_evt(self, large_dist):
        """p≥0.9 上尾走 EVT 路径。"""
        evt_val = large_dist.quantile(0.95, use_evt=True)
        emp_val = large_dist.quantile(0.95, use_evt=False)
        assert evt_val == pytest.approx(emp_val, rel=0.10)

    def test_non_extreme_quantile_no_evt(self, large_dist):
        """非极端分位数（p=0.5）不走 EVT，与 use_evt=False 完全一致。"""
        val_evt = large_dist.quantile(0.5, use_evt=True)
        val_emp = large_dist.quantile(0.5, use_evt=False)
        assert val_evt == pytest.approx(val_emp)

    def test_small_sample_no_evt(self, small_dist):
        """n<100 时不触发 EVT。"""
        val_evt = small_dist.quantile(0.05, use_evt=True)
        val_emp = small_dist.quantile(0.05, use_evt=False)
        assert val_evt == pytest.approx(val_emp)

    def test_use_evt_false_bypasses_evt(self, large_dist):
        """use_evt=False 时走纯经验分位数。"""
        val = large_dist.quantile(0.05, use_evt=False)
        emp = large_dist._empirical_quantile(0.05)
        assert val == pytest.approx(emp)

    def test_var_is_quantile_alias(self, large_dist):
        """var() 仍是 quantile() 的别名。"""
        assert large_dist.var(0.05, use_evt=True) == large_dist.quantile(0.05, use_evt=True)
        assert large_dist.var(0.05, use_evt=False) == large_dist.quantile(0.05, use_evt=False)

    def test_cvar_evt_extreme(self, large_dist):
        """CVaR EVT 路径与经验 CVaR 接近。"""
        evt_val = large_dist.cvar(0.05, use_evt=True)
        emp_val = large_dist.cvar(0.05, use_evt=False)
        assert evt_val == pytest.approx(emp_val, rel=0.15)

    def test_cvar_no_evt_for_non_extreme(self, large_dist):
        """α>0.1 的 CVaR 不走 EVT。"""
        # α=0.25 不触发 EVT，两点应一致
        val_evt = large_dist.cvar(0.25, use_evt=True)
        val_emp = large_dist.cvar(0.25, use_evt=False)
        assert val_evt == pytest.approx(val_emp)

    def test_cvar_small_sample_no_evt(self, small_dist):
        """n<100 时 CVaR 不触发 EVT。"""
        val_evt = small_dist.cvar(0.05, use_evt=True)
        val_emp = small_dist.cvar(0.05, use_evt=False)
        assert val_evt == pytest.approx(val_emp)

    def test_empty_distribution(self):
        """空分布不崩溃。"""
        dist = EmpiricalDistribution([])
        assert np.isnan(dist.quantile(0.05, use_evt=True))
        assert np.isnan(dist.cvar(0.05, use_evt=True))
        assert dist.var(0.05, use_evt=True) != dist.var(0.05, use_evt=True)  # NaN != NaN

    def test_evt_caching(self, large_dist):
        """多次调用使用缓存，不重复拟合。"""
        val1 = large_dist.quantile(0.05, use_evt=True)
        # 检查缓存已填充
        assert large_dist._evt_lower is not None
        val2 = large_dist.quantile(0.05, use_evt=True)
        assert val1 == val2

    def test_upper_and_lower_cache_independent(self, large_dist):
        """上下尾各自独立缓存。"""
        large_dist.quantile(0.05, use_evt=True)
        lower_cache = large_dist._evt_lower
        assert lower_cache is not None
        # 上尾尚未拟合，应为 None
        assert large_dist._evt_upper is None
        large_dist.quantile(0.95, use_evt=True)
        assert large_dist._evt_upper is not None
        # 下尾缓存未被覆盖
        assert large_dist._evt_lower is lower_cache

    # ── 退化数据检测 ──

    def test_binary_data_skips_evt(self):
        """二元数据（如 all_targets）跳过 EVT，回退经验分位数。"""
        rng = np.random.default_rng(42)
        data = rng.choice([0.0, 1.0], size=5000, p=[0.4, 0.6])
        dist = EmpiricalDistribution(list(data))
        val_evt = dist.quantile(0.05, use_evt=True)
        val_emp = dist.quantile(0.05, use_evt=False)
        assert val_evt == pytest.approx(val_emp)  # 应走经验路径

    def test_binary_data_evt_cache_remains_none(self):
        """二元数据调用 EVT 路径后，缓存仍为 None（未触发拟合）。"""
        rng = np.random.default_rng(42)
        data = rng.choice([0.0, 1.0], size=5000, p=[0.4, 0.6])
        dist = EmpiricalDistribution(list(data))
        dist.quantile(0.05, use_evt=True)
        assert dist._evt_lower is None  # 未触发 EVT 拟合
        assert dist._evt_upper is None

    def test_constant_data_skips_evt(self):
        """退化数据（恒为常数）跳过 EVT。"""
        data = [5.0] * 5000
        dist = EmpiricalDistribution(data)
        val = dist.quantile(0.05, use_evt=True)
        assert val == 5.0  # 经验分位数直接返回

    def test_few_distinct_values_skips_evt(self):
        """< 20 个不同取值时跳过 EVT。"""
        # 模拟 target_collection 5 种目标 → 6 个不同取值
        rng = np.random.default_rng(42)
        data = rng.choice([0.0, 0.2, 0.4, 0.6, 0.8, 1.0], size=5000)
        dist = EmpiricalDistribution(list(data))
        val_evt = dist.quantile(0.05, use_evt=True)
        val_emp = dist.quantile(0.05, use_evt=False)
        assert val_evt == pytest.approx(val_emp)  # 回退经验路径

    def test_many_distinct_values_uses_evt(self, large_dist):
        """≥ 20 个不同取值时正常走 EVT 路径。"""
        assert large_dist._count_distinct() >= 20
        large_dist.quantile(0.05, use_evt=True)
        assert large_dist._evt_lower is not None  # 触发了 EVT

    def test_distinct_count_cached(self):
        """_count_distinct 惰性计算且缓存。"""
        dist = EmpiricalDistribution([1.0, 2.0, 3.0, 1.0, 2.0])
        assert dist._distinct_count is None
        assert dist._count_distinct() == 3
        assert dist._distinct_count == 3  # 已缓存
        # 再次调用不重新计算
        assert dist._count_distinct() == 3

    def test_cvar_binary_skips_evt(self):
        """二元数据 CVaR 也跳过 EVT。"""
        rng = np.random.default_rng(42)
        data = rng.choice([0.0, 1.0], size=5000)
        dist = EmpiricalDistribution(list(data))
        val_evt = dist.cvar(0.05, use_evt=True)
        val_emp = dist.cvar(0.05, use_evt=False)
        assert val_evt == pytest.approx(val_emp)
