"""GDR 模块测试：lower_is_better、target_card_draws、resource_per_card 等。"""
import math
import pytest
from gacha_simulator.core.gdr import (
    GDRDefinition, SuccessChecker, compute_success_probability,
    UNIFIED_GDR_REGISTRY, compute_gdr_from_compact, populate_gdr_combo,
)


# ─── P11: target_card_draws GDR ────────────────────────────────────────

def test_target_card_draws_counts_all_targets():
    """不去重计数所有目标卡的出现次数"""
    gdr_def = UNIFIED_GDR_REGISTRY['target_card_draws']
    compact = {'card_counts': {'card_A': 3, 'card_B': 0, 'other': 5}}
    result = compute_gdr_from_compact(compact, {'card_A': 2, 'card_B': 1}, 'target_card_draws')
    assert result == pytest.approx(3.0)


def test_target_card_draws_zero_when_none():
    """没抽到任何目标卡 → 返回 0"""
    gdr_def = UNIFIED_GDR_REGISTRY['target_card_draws']
    compact = {'card_counts': {}}
    result = compute_gdr_from_compact(compact, {'card_A': 1}, 'target_card_draws')
    assert result == pytest.approx(0.0)


# ─── P4: lower_is_better 字段 ──────────────────────────────────────────

def test_gdr_definition_lower_is_better_default():
    """lower_is_better 默认应为 False"""
    gdr = GDRDefinition(
        key="test_lower", display_name="测试lower",
        default_threshold=0.5,
        compute_from_compact=lambda c, t: 0.5,
    )
    assert gdr.lower_is_better is False


def test_gdr_definition_lower_is_better_explicit():
    """显式设置 lower_is_better=True"""
    gdr = GDRDefinition(
        key="test_lower2", display_name="测试lower2",
        default_threshold=0.5,
        compute_from_compact=lambda c, t: 0.5,
        lower_is_better=True,
    )
    assert gdr.lower_is_better is True


def test_success_checker_lower_is_better():
    """lower_is_better=True 时 is_success 使用 <= 判断"""
    test_key = '_test_lower_is_better'
    UNIFIED_GDR_REGISTRY[test_key] = GDRDefinition(
        key=test_key, display_name='测试lower指标',
        default_threshold=50.0,
        compute_from_compact=lambda c, **kw: 30.0,
        lower_is_better=True,
    )
    checker = SuccessChecker({'card_A': 1}, gdr_key=test_key)
    # value=30 <= threshold=50 → 成功
    assert checker.is_success({}) is True

    # 阈值更低时 value=30 <= threshold=20 → 失败
    checker2 = SuccessChecker({'card_A': 1}, gdr_key=test_key, gdr_threshold=20.0)
    assert checker2.is_success({}) is False

    del UNIFIED_GDR_REGISTRY[test_key]


def test_compute_success_probability_lower_is_better():
    """lower_is_better=True 时 compute_success_probability 使用 <= 判断"""
    test_key = '_test_lower_succprob'
    UNIFIED_GDR_REGISTRY[test_key] = GDRDefinition(
        key=test_key, display_name='测试lower概率',
        default_threshold=50.0,
        compute_from_compact=lambda c, **kw: 30.0,
        lower_is_better=True,
    )
    # value=30 ≤ 50 → 全部成功
    p = compute_success_probability(
        [{}, {}], {'card_A': 1},
        gdr_key=test_key, gdr_threshold=50.0,
    )
    assert p == pytest.approx(1.0)

    # value=30 ≤ 20 → 全部失败
    p = compute_success_probability(
        [{}, {}], {'card_A': 1},
        gdr_key=test_key, gdr_threshold=20.0,
    )
    assert p == pytest.approx(0.0)

    del UNIFIED_GDR_REGISTRY[test_key]


# ─── P5: 新增 (-)GDR ──────────────────────────────────────────────────

def make_compact(total_consumed, card_counts):
    """构造最小 compact dict，仅含 GDR 计算所需字段"""
    return {
        'total_consumed': total_consumed,
        'card_counts': card_counts,
    }


def test_gdr_resource_per_card_normal():
    """消耗200资源，获得2张目标卡 → 每张100"""
    gdr_def = UNIFIED_GDR_REGISTRY['resource_per_card']
    compact = make_compact(
        total_consumed={'draw_resource': 200},
        card_counts={'card_A': 2},
    )
    result = compute_gdr_from_compact(compact, {'card_A': 2}, 'resource_per_card')
    assert result == pytest.approx(100.0)


def test_gdr_resource_per_card_zero_obtained():
    """未获得任何目标卡 → 返回 nan"""
    gdr_def = UNIFIED_GDR_REGISTRY['resource_per_card']
    compact = make_compact(
        total_consumed={'draw_resource': 200},
        card_counts={'card_A': 0},
    )
    result = compute_gdr_from_compact(compact, {'card_A': 1}, 'resource_per_card')
    assert math.isnan(result)


def test_gdr_resource_per_card_excess_capped():
    """获得超出需求数量的卡时，按需求量截断"""
    compact = make_compact(
        total_consumed={'draw_resource': 300},
        card_counts={'card_A': 5},
    )
    result = compute_gdr_from_compact(compact, {'card_A': 3}, 'resource_per_card')
    assert result == pytest.approx(100.0)


def test_gdr_resource_consumed():
    """消耗5000资源 → 返回 5000"""
    compact = make_compact(
        total_consumed={'draw_resource': 5000},
        card_counts={},
    )
    result = compute_gdr_from_compact(compact, {}, 'resource_consumed')
    assert result == pytest.approx(5000.0)


def test_gdr_resource_consumed_zero():
    """未消耗 → 返回 0"""
    compact = make_compact(
        total_consumed={'draw_resource': 0},
        card_counts={},
    )
    result = compute_gdr_from_compact(compact, {}, 'resource_consumed')
    assert result == pytest.approx(0.0)


def test_new_gdrs_have_lower_is_better():
    """两个新GDR都应标记 lower_is_better=True"""
    rpc = UNIFIED_GDR_REGISTRY['resource_per_card']
    assert rpc.lower_is_better is True
    rc = UNIFIED_GDR_REGISTRY['resource_consumed']
    assert rc.lower_is_better is True


# ─── P13: 抽数转化效率 GDR ─────────────────────────────────────────────────

def make_compact_extended(total_consumed, card_counts, total_draws=0, pool_draw_counts=None, pool_types=None):
    return {
        'total_consumed': total_consumed,
        'card_counts': card_counts,
        'total_draws': total_draws,
        'pool_draw_counts': pool_draw_counts or {},
        'pool_types': pool_types or {},
    }


def test_draw_conversion_efficiency_perfect():
    """消耗 16000 资源，抽卡池抽了 100 次，单抽成本 160 → 1.0"""
    compact = make_compact_extended(
        total_consumed={'draw_resource': 16000},
        card_counts={},
        total_draws=100,
        pool_draw_counts={'pool_draw': 100},
        pool_types={'pool_draw': '角色'},
    )
    result = compute_gdr_from_compact(
        compact, {}, 'draw_conversion_efficiency',
        cost_per_draw=160,
    )
    assert result == pytest.approx(1.0)


def test_draw_conversion_efficiency_low():
    """消耗 16000 资源，抽卡池只抽了 50 次，兑换池抽了 50 次 → 0.5"""
    compact = make_compact_extended(
        total_consumed={'draw_resource': 16000},
        card_counts={},
        total_draws=100,
        pool_draw_counts={'pool_draw': 50, 'pool_exchange': 50},
        pool_types={'pool_draw': '角色', 'pool_exchange': '兑换'},
    )
    result = compute_gdr_from_compact(
        compact, {}, 'draw_conversion_efficiency',
        cost_per_draw=160,
    )
    assert result == pytest.approx(0.5)


def test_draw_conversion_efficiency_no_consumption():
    """未消耗资源 → 0（避免除零）"""
    compact = make_compact_extended(
        total_consumed={},
        card_counts={},
    )
    result = compute_gdr_from_compact(
        compact, {}, 'draw_conversion_efficiency',
        cost_per_draw=160,
    )
    assert result == 0.0


def test_draw_conversion_efficiency_fallback_total_draws():
    """不传 draw_pool_ids 时回退到 total_draws"""
    compact = make_compact_extended(
        total_consumed={'draw_resource': 8000},
        card_counts={},
        total_draws=50,
    )
    result = compute_gdr_from_compact(
        compact, {}, 'draw_conversion_efficiency',
        cost_per_draw=160,
    )
    assert result == pytest.approx(1.0)


def test_populate_gdr_combo_lower_is_better_prefix():
    """lower_is_better=True 的 GDR 在 combo 中应有 (-) 前缀"""
    # populate_gdr_combo 仅拼接字符串，不依赖 QComboBox 内部行为
    # 使用简单列表模拟 combo 的 addItem 行为以绕过 QApplication 依赖
    class _MockCombo:
        def __init__(self):
            self.items = []
        def clear(self):
            self.items.clear()
        def addItem(self, text, data):
            self.items.append((text, data))
        def count(self):
            return len(self.items)
        def itemData(self, i):
            return self.items[i][1]
        def itemText(self, i):
            return self.items[i][0]

    test_key = '_test_combo_prefix'
    UNIFIED_GDR_REGISTRY[test_key] = GDRDefinition(
        key=test_key, display_name='测试前缀',
        default_threshold=50.0,
        compute_from_compact=lambda c, **kw: 30.0,
        lower_is_better=True,
    )
    combo = _MockCombo()
    populate_gdr_combo(combo)
    found = False
    for i in range(combo.count()):
        if combo.itemData(i) == test_key:
            assert combo.itemText(i).startswith('(-)'), f"期望以 (-) 开头，实际: {combo.itemText(i)}"
            found = True
            break
    assert found, "lower_is_better GDR 应出现在 combo 中且带 (-) 前缀"
    del UNIFIED_GDR_REGISTRY[test_key]
