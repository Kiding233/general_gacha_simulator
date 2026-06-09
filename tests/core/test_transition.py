"""转变分析统一测试：compute_transition_matrices_from_flags + compute_transition_flags_from_gdr + 完整管线。"""
import pytest
import warnings
from gacha_simulator.core.per_pool_analysis import (
    compute_transition_matrices_from_flags,
    compute_transition_flags_from_gdr,
    TransitionMatrix,
)
from gacha_simulator.core.streaming import DrawSequenceExtractor
from gacha_simulator.core.result_types import CompactResult


# ─── compute_transition_matrices_from_flags 纯函数 ─────────────────────

def test_empty_flags_returns_empty():
    """空输入 → 空输出"""
    result = compute_transition_matrices_from_flags([], [])
    assert result == []


def test_single_pool_no_transition():
    """单个池 → 从初始到该池的单个矩阵，无历史转移"""
    result = compute_transition_matrices_from_flags(
        [[True], [False]],
        ['pool_A'],
    )
    assert len(result) == 1
    m = result[0]
    assert m.from_pool_id == '(初始)'
    assert m.to_pool_id == 'pool_A'
    assert m.success_rate_before == 0.0
    assert m.success_rate_after == pytest.approx(0.5)


def test_two_pools_all_stable():
    """两个池全成功或全失败 → 转移矩阵无变化"""
    result = compute_transition_matrices_from_flags(
        [[True, True], [False, False]],
        ['pool_1', 'pool_2'],
    )
    assert len(result) == 2
    m1 = result[1]  # pool_1 → pool_2
    assert m1.success_to_success == pytest.approx(1.0)
    assert m1.fail_to_fail == pytest.approx(1.0)


def test_two_pools_mixed_transition():
    """混合转移：一半成功变失败，一半失败变成功"""
    result = compute_transition_matrices_from_flags(
        [[True, True], [True, False], [False, True], [False, False]],
        ['pool_1', 'pool_2'],
    )
    assert len(result) == 2
    m = result[1]
    # pool_1: 2 成功/2 失败 → pool_2: 2 成功/2 失败
    assert m.success_to_success == pytest.approx(0.5)
    assert m.success_to_fail == pytest.approx(0.5)
    assert m.fail_to_success == pytest.approx(0.5)
    assert m.fail_to_fail == pytest.approx(0.5)


def test_three_pools_two_transitions():
    """三个池 → 三个 TransitionMatrix（含初始）"""
    result = compute_transition_matrices_from_flags(
        [[True, False, True], [False, True, False]],
        ['pool_1', 'pool_2', 'pool_3'],
    )
    assert len(result) == 3
    assert result[0].from_pool_id == '(初始)'
    assert result[1].from_pool_id == 'pool_1'
    assert result[2].from_pool_id == 'pool_2'


def test_variable_length_flags():
    """不同模拟的池数不同时应安全处理"""
    result = compute_transition_matrices_from_flags(
        [[True, True], [False]],  # 第二行只有 1 个池的数据
        ['pool_1', 'pool_2'],
    )
    assert len(result) == 2


# ─── compute_transition_flags_from_gdr ─────────────────────────────────

def test_gdr_flags_all_targets_cumulative():
    """累积快照 + all_targets GDR → 逐池判定"""
    cum_snaps = {
        'pool_1': [{'cumulative_card_counts': {'card_A': 1, 'card_B': 0}}],
        'pool_2': [{'cumulative_card_counts': {'card_A': 1, 'card_B': 1}}],
    }
    pool_ids = ['pool_1', 'pool_2']
    target_specs = {'card_A': 1, 'card_B': 1}

    flags = compute_transition_flags_from_gdr(
        cum_snaps, pool_ids, target_specs,
        gdr_key='all_targets', threshold=1.0,
        scope='cumulative',
    )
    # pool_1: 缺 card_B → 失败; pool_2: 齐全 → 成功
    assert flags == [[False, True]]


# ─── 完整管线：DrawSequenceExtractor → 转变分析 ────────────────────────

def _make_compact(pool_ids, card_ids, times, pool_end_times,
                  pool_end_resources=None):
    """构造最小 CompactResult 用于测试管线。"""
    return CompactResult(
        draw_pool_ids=pool_ids,
        draw_card_ids=card_ids,
        draw_times=times,
        draw_pity=[False] * len(pool_ids),
        draw_pity_names=[''] * len(pool_ids),
        draw_pity_counter_max=[0] * len(pool_ids),
        draw_resources_consumed=[{'draw_resource': 160}] * len(pool_ids),
        draw_resources_gained=[{}] * len(pool_ids),
        pool_end_resources=pool_end_resources or {},
    )


def test_extractor_to_transition_pipeline():
    """DrawSequenceExtractor 填充 cumulative_snapshots 后完整转变分析管线能产出结果。"""
    pool_end_times = {'pool_A': 10.0, 'pool_B': 20.0}

    extractor = DrawSequenceExtractor(
        max_keep=10,
        pool_end_times=pool_end_times,
        target_ids={'card_A', 'card_B'},
        target_specs={'card_A': 1, 'card_B': 1},
    )

    # 模拟 4 次——每次的抽卡序列不同
    results = [
        # 模拟0：pool_A结束前就抽到了2张卡，pool_B结束前抽到4张
        _make_compact(
            ['pool_A', 'pool_A', 'pool_B', 'pool_B'],
            ['card_A', 'card_B', 'card_A', 'card_B'],
            [5.0, 8.0, 12.0, 18.0],
            pool_end_times,
            pool_end_resources={
                'pool_A': {'draw_resource': 5000},
                'pool_B': {'draw_resource': 4000},
            },
        ),
        # 模拟1：只抽到card_A
        _make_compact(
            ['pool_A', 'pool_B'],
            ['card_A', 'card_A'],
            [5.0, 15.0],
            pool_end_times,
        ),
        # 模拟2：全没抽到目标卡
        _make_compact(
            ['pool_A', 'pool_A', 'pool_B'],
            ['other_1', 'other_2', 'other_3'],
            [3.0, 7.0, 15.0],
            pool_end_times,
        ),
        # 模拟3：pool_A结束前凑齐，pool_B结束前额外再抽
        _make_compact(
            ['pool_A', 'pool_B', 'pool_B', 'pool_B'],
            ['card_A', 'card_B', 'card_A', 'card_B'],
            [2.0, 12.0, 16.0, 19.0],
            pool_end_times,
        ),
    ]

    for r in results:
        extractor.on_result(r)

    # 验证 cumulative_snapshots 已填充
    cum_snaps = extractor.get_cumulative_snapshots()
    assert 'pool_A' in cum_snaps
    assert 'pool_B' in cum_snaps
    assert len(cum_snaps['pool_A']) == 4
    assert len(cum_snaps['pool_B']) == 4

    # 模拟0：pool_A 结束时（≤10s）有 card_A×1 + card_B×1 = 全部齐
    snap_0_A = cum_snaps['pool_A'][0]
    assert snap_0_A['cumulative_card_counts'].get('card_A', 0) >= 1
    assert snap_0_A['cumulative_card_counts'].get('card_B', 0) >= 1

    # 模拟2：pool_A 结束时没有目标卡
    snap_2_A = cum_snaps['pool_A'][2]
    assert snap_2_A['cumulative_card_counts'].get('card_A', 0) == 0
    assert snap_2_A['cumulative_card_counts'].get('card_B', 0) == 0

    # 计算转变flags——all_targets 阈值1.0
    pool_ids_ordered = ['pool_A', 'pool_B']
    flags = compute_transition_flags_from_gdr(
        cum_snaps, pool_ids_ordered,
        {'card_A': 1, 'card_B': 1},
        gdr_key='all_targets', threshold=1.0,
        scope='cumulative',
    )
    assert len(flags) == 4
    # 模拟0：pool_A全部齐 → True, pool_B全部齐 → True
    assert flags[0] == [True, True]
    # 模拟1：pool_A缺card_B → False, pool_B仍缺 → False
    assert flags[1] == [False, False]
    # 模拟2：全缺 → False, False
    assert flags[2] == [False, False]
    # 模拟3：pool_A齐(只有card_A) → False(缺card_B), pool_B全部齐 → True
    assert flags[3] == [False, True]

    # 计算转移矩阵
    trans = compute_transition_matrices_from_flags(flags, pool_ids_ordered)
    assert len(trans) == 2
    assert trans[0].from_pool_id == '(初始)'
    assert trans[0].to_pool_id == 'pool_A'
    assert trans[1].from_pool_id == 'pool_A'
    assert trans[1].to_pool_id == 'pool_B'


def test_extractor_empty_pool_end_times_produces_empty_snapshots():
    """pool_end_times 为空时，cumulative_snapshots 和 transition_flags 均为空。"""
    extractor = DrawSequenceExtractor(
        max_keep=10,
        pool_end_times={},
        target_ids={'card_A'},
        target_specs={'card_A': 1},
    )
    r = _make_compact(
        ['pool_A'], ['card_A'], [5.0],
        {'pool_A': 10.0},
    )
    extractor.on_result(r)

    assert extractor.get_cumulative_snapshots() == {}
    assert extractor.get_transition_flags() == []


def test_analysis_worker_guards_accept_nonempty_data():
    """模拟 AnalysisWorker 守卫条件：pool_end_times 和 cumulative_snapshots 非空时应通过。"""
    pool_end_times = {'pool_A': 10.0}
    cum_snaps = {
        'pool_A': [{'cumulative_card_counts': {'card_A': 1}}],
    }
    pool_ids_ordered = ['pool_A']

    # 守卫1: pool_end_times 非空
    assert pool_end_times  # 通过

    # 守卫2: cumulative_snapshots 非空
    assert cum_snaps  # 通过

    flags = compute_transition_flags_from_gdr(
        cum_snaps, pool_ids_ordered,
        {'card_A': 1},
        gdr_key='all_targets', threshold=1.0,
        scope='cumulative',
    )
    assert len(flags) == 1

    trans = compute_transition_matrices_from_flags(flags, pool_ids_ordered)
    assert len(trans) == 1


def test_update_transition_per_card_requirements():
    """_update_transition 按每张卡的独立需求量判断成功，非简单的总数比对。"""
    pool_end_times = {'pool_A': 10.0}
    # 需要 2 张 card_A + 1 张 card_B，但只抽到 3 张 card_A（缺 card_B）
    extractor = DrawSequenceExtractor(
        max_keep=10,
        pool_end_times=pool_end_times,
        target_ids={'card_A', 'card_B'},
        target_specs={'card_A': 2, 'card_B': 1},
    )
    r = _make_compact(
        ['pool_A', 'pool_A', 'pool_A'],
        ['card_A', 'card_A', 'card_A'],  # 3张card_A, 0张card_B
        [2.0, 5.0, 8.0],
        pool_end_times,
    )
    extractor.on_result(r)

    flags = extractor.get_transition_flags()
    assert len(flags) == 1
    # 缺 card_B → 失败（旧逻辑会因总数 3 >= 3 误判为成功）
    assert flags[0] == [False]


def test_update_transition_per_card_satisfied():
    """同时满足所有卡的需求量时才判定成功。"""
    pool_end_times = {'pool_A': 10.0, 'pool_B': 20.0}
    extractor = DrawSequenceExtractor(
        max_keep=10,
        pool_end_times=pool_end_times,
        target_ids={'card_A', 'card_B'},
        target_specs={'card_A': 2, 'card_B': 1},
    )
    r = _make_compact(
        ['pool_A', 'pool_A', 'pool_B', 'pool_B', 'pool_B'],
        ['card_A', 'card_A', 'card_B', 'card_A', 'card_B'],
        [2.0, 5.0, 12.0, 16.0, 19.0],
        pool_end_times,
    )
    extractor.on_result(r)

    flags = extractor.get_transition_flags()
    assert len(flags) == 1
    # pool_A 结束时（≤10s）：card_A×2 → 满足card_A需求，但card_B=0 → 失败
    # pool_B 结束时（≤20s）：card_A×3 + card_B×2 → 全部满足 → 成功
    assert flags[0] == [False, True]
