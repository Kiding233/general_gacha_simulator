"""GDR 模块测试：lower_is_better、target_card_draws、resource_per_card 等。"""
import math
import pytest
from gacha_simulator.core.gdr import (
    GDRDefinition, GDRCalculator, compute_success_probability,
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
    checker = GDRCalculator({'card_A': 1}, gdr_key=test_key)
    # value=30 <= threshold=50 → 成功
    assert checker.is_success({}) is True

    # 阈值更低时 value=30 <= threshold=20 → 失败
    checker2 = GDRCalculator({'card_A': 1}, gdr_key=test_key, gdr_threshold=20.0)
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


# ═══════════════════════════════════════════════════════════════════
# P22 多资源类型支持——新公共函数测试
# ═══════════════════════════════════════════════════════════════════

class TestParseGdrKey:
    """parse_gdr_key() 单元测试"""

    def test_plain_key_defaults_to_draw_resource(self):
        from gacha_simulator.core.gdr import parse_gdr_key
        base_key, resource_id = parse_gdr_key('resource_remaining')
        assert base_key == 'resource_remaining'
        assert resource_id == 'draw_resource'

    def test_qualified_key_parses_correctly(self):
        from gacha_simulator.core.gdr import parse_gdr_key
        base_key, resource_id = parse_gdr_key('resource_remaining:exchange_currency')
        assert base_key == 'resource_remaining'
        assert resource_id == 'exchange_currency'

    def test_non_resource_key_defaults(self):
        from gacha_simulator.core.gdr import parse_gdr_key
        base_key, resource_id = parse_gdr_key('target_achievement')
        assert base_key == 'target_achievement'
        assert resource_id == 'draw_resource'

    def test_key_with_multiple_colons(self):
        """仅第一个 ':' 为分隔符"""
        from gacha_simulator.core.gdr import parse_gdr_key
        base_key, resource_id = parse_gdr_key('a:b:c')
        assert base_key == 'a'
        assert resource_id == 'b:c'

    def test_none_input_returns_safe_default(self):
        """GUI 初始化时 currentData() 可能为 None，不应崩溃"""
        from gacha_simulator.core.gdr import parse_gdr_key
        base_key, resource_id = parse_gdr_key(None)
        assert base_key == ''
        assert resource_id == 'draw_resource'


class TestIsResourceGdr:
    """is_resource_gdr() 单元测试"""

    def test_resource_gdr_plain_key(self):
        from gacha_simulator.core.gdr import is_resource_gdr
        assert is_resource_gdr('resource_remaining') is True
        assert is_resource_gdr('resource_consumed') is True
        assert is_resource_gdr('resource_per_card') is True
        assert is_resource_gdr('resource_efficiency') is True

    def test_resource_gdr_qualified_key(self):
        from gacha_simulator.core.gdr import is_resource_gdr
        assert is_resource_gdr('resource_remaining:exchange_currency') is True

    def test_non_resource_key(self):
        from gacha_simulator.core.gdr import is_resource_gdr
        assert is_resource_gdr('target_achievement') is False
        assert is_resource_gdr('all_targets') is False
        assert is_resource_gdr('draw_conversion_efficiency') is False

    def test_invalid_key(self):
        from gacha_simulator.core.gdr import is_resource_gdr
        assert is_resource_gdr('nonexistent_gdr') is False

    def test_none_input_returns_false(self):
        """GUI 初始化时 currentData() 可能为 None，不应崩溃"""
        from gacha_simulator.core.gdr import is_resource_gdr
        assert is_resource_gdr(None) is False


class TestGetExpandedGdrEntries:
    """get_expanded_gdr_entries() 单元测试"""

    def test_no_resource_defs_returns_17(self):
        from gacha_simulator.core.gdr import get_expanded_gdr_entries
        entries = get_expanded_gdr_entries()
        assert len(entries) == 17

    def test_two_resource_types_returns_21(self):
        from gacha_simulator.core.gdr import get_expanded_gdr_entries
        entries = get_expanded_gdr_entries({
            'draw_resource': '抽卡资源',
            'exchange_currency': '兑换货币',
        })
        assert len(entries) == 21

    def test_no_duplicate_original_keys(self):
        """展开后不应出现原始 resource_remaining（无 : 后缀）"""
        from gacha_simulator.core.gdr import get_expanded_gdr_entries
        entries = get_expanded_gdr_entries({
            'draw_resource': '抽卡资源',
            'exchange_currency': '兑换货币',
        })
        keys = [e[0] for e in entries]
        assert 'resource_remaining' not in keys
        assert 'resource_remaining:draw_resource' in keys
        assert 'resource_remaining:exchange_currency' in keys

    def test_display_name_format(self):
        from gacha_simulator.core.gdr import get_expanded_gdr_entries
        entries = get_expanded_gdr_entries({
            'draw_resource': '抽卡资源',
            'exchange_currency': '兑换货币',
        })
        for key, display, lib, thr in entries:
            if key == 'resource_remaining:exchange_currency':
                assert '资源剩余' in display
                assert '兑换货币' in display
                break
        else:
            assert False, "未找到 resource_remaining:exchange_currency"


class TestResolveGdrDefinition:
    """resolve_gdr_definition() 单元测试"""

    def test_hit_by_full_qualified_key(self):
        from gacha_simulator.core.gdr import resolve_gdr_definition
        defn = resolve_gdr_definition('resource_remaining:exchange_currency')
        assert defn is not None
        assert defn.key == 'resource_remaining'

    def test_hit_by_base_key_fallback(self):
        from gacha_simulator.core.gdr import resolve_gdr_definition
        defn = resolve_gdr_definition('resource_remaining')
        assert defn is not None
        assert defn.key == 'resource_remaining'

    def test_invalid_key_returns_none(self):
        from gacha_simulator.core.gdr import resolve_gdr_definition
        assert resolve_gdr_definition('nonexistent_key') is None

    def test_none_input_returns_none(self):
        """GUI 初始化时 currentData() 可能为 None，不应崩溃"""
        from gacha_simulator.core.gdr import resolve_gdr_definition
        assert resolve_gdr_definition(None) is None

    def test_lower_is_better_preserved(self):
        from gacha_simulator.core.gdr import resolve_gdr_definition
        defn = resolve_gdr_definition('resource_consumed:exchange_currency')
        assert defn is not None
        assert defn.lower_is_better is True


class TestMultiResourceCompute:
    """多资源类型端到端 GDR 计算测试"""

    def test_resource_remaining_reads_correct_resource(self):
        from gacha_simulator.core.gdr import compute_gdr_from_compact
        compact = {
            'final_resources': {'draw_resource': 100.0, 'exchange_currency': 50.0},
            'total_consumed': {},
            'card_counts': {},
        }
        val_draw = compute_gdr_from_compact(compact, {}, 'resource_remaining')
        assert val_draw == 100.0
        val_ex = compute_gdr_from_compact(compact, {}, 'resource_remaining:exchange_currency')
        assert val_ex == 50.0

    def test_resource_consumed_reads_correct_resource(self):
        from gacha_simulator.core.gdr import compute_gdr_from_compact
        compact = {
            'final_resources': {},
            'total_consumed': {'draw_resource': 200.0, 'exchange_currency': 20.0},
            'card_counts': {},
        }
        val_draw = compute_gdr_from_compact(compact, {}, 'resource_consumed')
        assert val_draw == 200.0
        val_ex = compute_gdr_from_compact(compact, {}, 'resource_consumed:exchange_currency')
        assert val_ex == 20.0

    def test_resource_efficiency_uses_resource_id(self):
        from gacha_simulator.core.gdr import compute_gdr_from_compact
        compact = {
            'final_resources': {},
            'total_consumed': {'draw_resource': 1600.0, 'exchange_currency': 10.0},
            'card_counts': {'card_a': 2},
        }
        target_specs = {'card_a': 2}
        val_draw = compute_gdr_from_compact(compact, target_specs, 'resource_efficiency')
        assert abs(val_draw - 0.00125) < 1e-9
        val_ex = compute_gdr_from_compact(compact, target_specs, 'resource_efficiency:exchange_currency')
        assert abs(val_ex - 0.2) < 1e-9

    def test_resource_per_card_uses_resource_id(self):
        from gacha_simulator.core.gdr import compute_gdr_from_compact
        compact = {
            'final_resources': {},
            'total_consumed': {'draw_resource': 320.0, 'exchange_currency': 8.0},
            'card_counts': {'card_a': 1},
        }
        target_specs = {'card_a': 1}
        val_draw = compute_gdr_from_compact(compact, target_specs, 'resource_per_card')
        assert val_draw == 320.0
        val_ex = compute_gdr_from_compact(compact, target_specs, 'resource_per_card:exchange_currency')
        assert val_ex == 8.0

    def test_resource_per_card_nan_when_zero_obtained(self):
        from gacha_simulator.core.gdr import compute_gdr_from_compact
        import math
        compact = {
            'final_resources': {},
            'total_consumed': {'exchange_currency': 8.0},
            'card_counts': {},
        }
        val = compute_gdr_from_compact(compact, {'card_a': 1}, 'resource_per_card:exchange_currency')
        assert math.isnan(val)

    def test_gdr_kwargs_resource_id_priority(self):
        """通过 **gdr_kwargs 传入 resource_id 会被解析值覆盖，不抛 TypeError"""
        from gacha_simulator.core.gdr import compute_gdr_from_compact
        compact = {
            'final_resources': {'exchange_currency': 50.0},
            'total_consumed': {},
            'card_counts': {},
        }
        val = compute_gdr_from_compact(
            compact, {}, 'resource_remaining:exchange_currency',
            resource_id='draw_resource',
        )
        assert val == 50.0  # 以 key 解析值为准

    def test_compute_vulnerability_analysis_resource_key_fallback(self):
        """resource_key=None 时从 gdr_key 解析"""
        from gacha_simulator.core.gdr import parse_gdr_key
        _, rid = parse_gdr_key('resource_remaining:exchange_currency')
        assert rid == 'exchange_currency'
        _, rid_default = parse_gdr_key('all_targets')
        assert rid_default == 'draw_resource'

    def test_gdr_binning_inf_detection_with_qualified_key(self):
        """resource_per_card:exchange_currency 的 inf 检测"""
        from gacha_simulator.core.gdr import parse_gdr_key
        base_key, _ = parse_gdr_key('resource_per_card:exchange_currency')
        assert base_key == 'resource_per_card'
        base_key2, _ = parse_gdr_key('resource_per_card')
        assert base_key2 == 'resource_per_card'

    def test_resolve_gdr_definition_for_comparison_analyzer(self):
        """B12a 场景"""
        from gacha_simulator.core.gdr import resolve_gdr_definition
        defn = resolve_gdr_definition('resource_remaining:exchange_currency')
        assert defn is not None
        assert defn.lower_is_better is False

    def test_resolve_gdr_definition_for_default_threshold(self):
        """B18 场景"""
        from gacha_simulator.core.gdr import get_default_threshold
        thr = get_default_threshold('resource_remaining:exchange_currency')
        assert thr == 0.0

    def test_get_default_threshold_none_input(self):
        """GUI 初始化时 currentData() 可能为 None，不应崩溃——返回 1.0"""
        from gacha_simulator.core.gdr import get_default_threshold
        assert get_default_threshold(None) == 1.0

    def test_populate_gdr_combo_with_resource_defs(self):
        """S2.1 场景: 传入 resource_defs 展开 21 条"""
        from gacha_simulator.core.gdr import populate_gdr_combo

        class _MockCombo:
            def clear(self):
                self.items = []
            def addItem(self, text, data=None):
                self.items.append((text, data))
            def count(self):
                return len(self.items)
            def itemData(self, i):
                return self.items[i][1]
            def itemText(self, i):
                return self.items[i][0]

        combo = _MockCombo()
        populate_gdr_combo(combo, resource_defs={
            'draw_resource': '抽卡资源',
            'exchange_currency': '兑换货币',
        })
        assert combo.count() == 21
        keys = [combo.itemData(i) for i in range(combo.count())]
        assert 'resource_remaining' not in keys
        assert 'resource_remaining:draw_resource' in keys
        assert 'resource_remaining:exchange_currency' in keys
