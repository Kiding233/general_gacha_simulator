"""BootstrapEngine 测试。"""

import math

import numpy as np
import pytest

from gacha_simulator.core.bootstrap import BootstrapEngine, BootstrapResult


class TestBootstrapProbability:
    """bootstrap_probability 二分类成功概率的 Bootstrap CI。"""

    @pytest.fixture
    def engine(self):
        return BootstrapEngine(B=2000, ci_level=0.95, random_seed=42)

    def test_normal_binary(self, engine):
        """正常二分类数据：BCa 置信区间落在合理范围。"""
        rng = np.random.default_rng(123)
        flags = rng.random(200) < 0.3
        result = engine.bootstrap_probability(flags, use_bca=True)
        assert 0.0 < result.point_estimate < 1.0
        assert 0.0 <= result.ci_lower <= result.point_estimate <= result.ci_upper <= 1.0
        assert result.bootstrap_std >= 0.0
        assert result.method == 'BCa'
        assert result.n_samples == 200
        assert result.b_replicates == 2000

    def test_percentile_method(self, engine):
        """use_bca=False 时使用百分位法。"""
        rng = np.random.default_rng(123)
        flags = rng.random(100) < 0.5
        result = engine.bootstrap_probability(flags, use_bca=False)
        assert result.method == 'percentile'

    def test_all_success(self, engine):
        """全成功：point_est=1，走百分位回退路径。"""
        flags = [True] * 50
        result = engine.bootstrap_probability(flags, use_bca=True)
        assert result.point_estimate == 1.0
        assert result.ci_lower == 1.0
        assert result.ci_upper == 1.0
        assert result.bootstrap_std == 0.0

    def test_all_failure(self, engine):
        """全失败：point_est=0，走百分位回退路径。"""
        flags = [False] * 50
        result = engine.bootstrap_probability(flags, use_bca=True)
        assert result.point_estimate == 0.0
        assert result.ci_lower == 0.0
        assert result.ci_upper == 0.0
        assert result.bootstrap_std == 0.0

    def test_empty_data(self, engine):
        """空数据返回 NaN。"""
        result = engine.bootstrap_probability([], use_bca=True)
        assert math.isnan(result.point_estimate)
        assert math.isnan(result.ci_lower)
        assert math.isnan(result.ci_upper)

    def test_small_sample_bca_ok(self, engine):
        """scipy BCa 对小样本也能成功计算（不强制 n<50 限制）。"""
        rng = np.random.default_rng(42)
        flags = rng.random(30) < 0.5
        result = engine.bootstrap_probability(flags, use_bca=True)
        assert result.method == 'BCa'
        assert 0.0 <= result.ci_lower <= result.ci_upper <= 1.0

    def test_reproducibility(self):
        """相同种子产生相同结果。"""
        rng = np.random.default_rng(99)
        flags = rng.random(150) < 0.25
        e1 = BootstrapEngine(B=1000, random_seed=42)
        e2 = BootstrapEngine(B=1000, random_seed=42)
        r1 = e1.bootstrap_probability(flags, use_bca=False)
        r2 = e2.bootstrap_probability(flags, use_bca=False)
        assert r1.point_estimate == r2.point_estimate
        assert r1.ci_lower == r2.ci_lower
        assert r1.ci_upper == r2.ci_upper


class TestBootstrapMean:
    """bootstrap_mean 连续量均值的 Bootstrap CI。"""

    @pytest.fixture
    def engine(self):
        return BootstrapEngine(B=2000, ci_level=0.95, random_seed=42)

    def test_normal_continuous(self, engine):
        """正态分布数据：BCa CI 覆盖真实均值。"""
        rng = np.random.default_rng(123)
        values = rng.normal(100, 15, 200)
        result = engine.bootstrap_mean(values, use_bca=True)
        assert 90 < result.point_estimate < 110
        assert result.ci_lower < result.point_estimate < result.ci_upper
        assert result.bootstrap_std > 0
        assert result.method == 'BCa'

    def test_percentile_method(self, engine):
        """use_bca=False 时使用百分位法。"""
        rng = np.random.default_rng(123)
        values = rng.normal(0, 1, 100)
        result = engine.bootstrap_mean(values, use_bca=False)
        assert result.method == 'percentile'

    def test_empty_data(self, engine):
        """空数据返回 NaN。"""
        result = engine.bootstrap_mean([], use_bca=True)
        assert math.isnan(result.point_estimate)

    def test_auto_heavy_tail_normal(self, engine):
        """正态数据不应触发厚尾路径。"""
        rng = np.random.default_rng(42)
        values = rng.normal(0, 1, 500)
        result = engine.bootstrap_mean(values, use_bca=True, auto_heavy_tail=True)
        # 正态数据 Hill α 应很大，不触发 m-out-of-n
        assert 'm-out-of-n' not in result.method

    def test_auto_heavy_tail_pareto(self, engine):
        """Pareto 厚尾数据应触发 m-out-of-n。"""
        rng = np.random.default_rng(42)
        values = rng.pareto(1.5, 500)
        result = engine.bootstrap_mean(values, use_bca=False, auto_heavy_tail=True)
        assert 'm-out-of-n' in result.method
        assert result.n_samples == 500

    def test_small_sample_bca_ok(self, engine):
        """scipy BCa 对小样本也能成功计算。"""
        rng = np.random.default_rng(42)
        values = rng.normal(0, 1, 25)
        result = engine.bootstrap_mean(values, use_bca=True)
        assert result.method == 'BCa'
        assert result.ci_lower < result.point_estimate < result.ci_upper


class TestBootstrapQuantile:
    """bootstrap_quantile 分位数的 Bootstrap CI。"""

    @pytest.fixture
    def engine(self):
        return BootstrapEngine(B=2000, ci_level=0.95, random_seed=42)

    def test_median(self, engine):
        """中位数 Bootstrap。"""
        rng = np.random.default_rng(123)
        values = rng.normal(100, 15, 200)
        result = engine.bootstrap_quantile(values, q=0.5)
        assert 90 < result.point_estimate < 110
        assert result.ci_lower < result.point_estimate < result.ci_upper
        assert result.method == 'percentile'

    def test_low_quantile_gpd(self, engine):
        """低分位数 GPD 参数 Bootstrap。"""
        rng = np.random.default_rng(42)
        values = rng.exponential(10, 500)
        result = engine.bootstrap_quantile(values, q=0.05, use_gpd=True)
        assert result.point_estimate > 0
        assert result.ci_lower <= result.point_estimate <= result.ci_upper
        assert result.method == 'GPD-param'

    def test_low_quantile_auto_heavy_tail(self, engine):
        """auto_heavy_tail 在厚尾低分位数时自动启用 GPD。"""
        rng = np.random.default_rng(42)
        values = rng.pareto(1.8, 500)
        result = engine.bootstrap_quantile(values, q=0.05, auto_heavy_tail=True)
        assert result.point_estimate > 0
        # 应该触发 GPD 路径
        assert result.method in ('GPD-param', 'percentile')

    def test_high_quantile_no_gpd(self, engine):
        """高分位数 (q>0.1) 不应触发 GPD，即使 use_gpd=True。"""
        rng = np.random.default_rng(123)
        values = rng.normal(0, 1, 200)
        result = engine.bootstrap_quantile(values, q=0.9, use_gpd=True)
        assert 'GPD' not in result.method

    def test_empty_data(self, engine):
        """空数据返回 NaN。"""
        result = engine.bootstrap_quantile([], q=0.5)
        assert math.isnan(result.point_estimate)

    def test_edge_quantile_zero(self, engine):
        """q=0 分位数 Bootstrap。"""
        rng = np.random.default_rng(123)
        values = rng.normal(0, 1, 200)
        result = engine.bootstrap_quantile(values, q=0.0)
        assert result.point_estimate <= result.ci_upper


class TestHillEstimator:
    """hill_estimator 尾部指数估计。"""

    @pytest.fixture
    def engine(self):
        return BootstrapEngine(random_seed=42)

    def test_normal_data_large_alpha(self, engine):
        """正态数据 Hill α 应较大（>2，有限方差）。"""
        rng = np.random.default_rng(42)
        values = rng.normal(0, 1, 500)
        alpha = engine.hill_estimator(values)
        assert alpha > 2.0

    def test_pareto_small_alpha(self, engine):
        """Pareto(1.5) 厚尾数据 Hill α < 2。"""
        rng = np.random.default_rng(42)
        values = rng.pareto(1.5, 500)
        alpha = engine.hill_estimator(values)
        assert alpha < 2.5  # 估计值接近真实 1.5

    def test_explicit_k(self, engine):
        """指定 k 值时应使用该 k。"""
        rng = np.random.default_rng(42)
        values = rng.normal(0, 1, 200)
        alpha = engine.hill_estimator(values, k=20)
        assert alpha > 0

    def test_small_sample(self, engine):
        """n<20 返回 inf。"""
        values = [1.0] * 10
        alpha = engine.hill_estimator(values)
        assert alpha == float('inf')


class TestDetectHeavyTail:
    """detect_heavy_tail 厚尾检测。"""

    @pytest.fixture
    def engine(self):
        return BootstrapEngine(random_seed=42)

    def test_normal_not_heavy(self, engine):
        """正态数据不应被标记为厚尾。"""
        rng = np.random.default_rng(42)
        values = rng.normal(0, 1, 500)
        result = engine.detect_heavy_tail(values)
        assert not result['heavy_tail']
        assert result['alpha'] > 2.0

    def test_pareto_heavy(self, engine):
        """Pareto(1.5) 应被标记为厚尾。"""
        rng = np.random.default_rng(42)
        values = rng.pareto(1.5, 500)
        result = engine.detect_heavy_tail(values)
        assert result['heavy_tail']
        assert 'm-out-of-n' in result['recommendation']


class TestTotalVariationDistance:
    """total_variation_distance 总变差距离。"""

    def test_identical_distributions(self):
        """相同分布 TVD=0。"""
        engine = BootstrapEngine()
        p = {'a': 0.5, 'b': 0.3, 'c': 0.2}
        q = {'a': 0.5, 'b': 0.3, 'c': 0.2}
        assert engine.total_variation_distance(p, q) == 0.0

    def test_disjoint_distributions(self):
        """完全不相交分布 TVD=1。"""
        engine = BootstrapEngine()
        p = {'a': 1.0}
        q = {'b': 1.0}
        assert engine.total_variation_distance(p, q) == 1.0

    def test_partial_overlap(self):
        """部分重叠分布。"""
        engine = BootstrapEngine()
        p = {'a': 0.6, 'b': 0.4}
        q = {'a': 0.4, 'b': 0.6}
        # TVD = 0.5 * (|0.6-0.4| + |0.4-0.6|) = 0.5 * 0.4 = 0.2
        assert engine.total_variation_distance(p, q) == pytest.approx(0.2)

    def test_different_keys(self):
        """键集合不同的分布。"""
        engine = BootstrapEngine()
        p = {'a': 0.7, 'b': 0.3}
        q = {'a': 0.7, 'c': 0.3}
        # TVD = 0.5 * (|0.7-0.7| + |0.3-0| + |0-0.3|) = 0.5 * 0.6 = 0.3
        assert engine.total_variation_distance(p, q) == pytest.approx(0.3)


class TestBootstrapResultFormat:
    """BootstrapResult.format_ci 格式化。"""

    def test_default_precision(self):
        result = BootstrapResult(0.5, 0.4, 0.6, 0.05, 'BCa', 100, 1000)
        formatted = result.format_ci()
        assert formatted == "0.500 [0.400, 0.600]"

    def test_custom_precision(self):
        result = BootstrapResult(0.12345, 0.1, 0.2, 0.01, 'percentile', 50, 500)
        formatted = result.format_ci(precision=2)
        assert formatted == "0.12 [0.10, 0.20]"

    def test_method_field(self):
        result = BootstrapResult(1.0, 1.0, 1.0, 0.0, 'GPD-param', 30, 1000)
        assert result.method == 'GPD-param'
