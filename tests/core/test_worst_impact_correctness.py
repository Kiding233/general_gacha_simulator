"""最差影响分析正确性验证。

不依赖概率的确定性测试：逐个验证策略行为、停止条件、完整流程。
"""
import pytest
from unittest.mock import MagicMock, patch
from gacha_simulator.core.worst_impact import DrawTargetStrategy
from gacha_simulator.core.strategy import StrategyContext, create_strategy, STRATEGY_REGISTRY
from gacha_simulator.core.action import DrawAction, WaitAction
from gacha_simulator.core.stop_condition import ConsecutivePoolTargetCondition


# ============================================================
# 测试 1: DrawTargetStrategy 在批量模式下的行为
# ============================================================

class _FakePool:
    def __init__(self, pid, cost, available_until=None):
        self.id = pid
        self.cost = cost
        self.available_until = available_until


class _FakeState:
    def __init__(self, resources, real_time=0):
        self._resources = resources.copy()
        self.real_time = real_time

    def can_afford(self, cost):
        for k, v in cost.items():
            if self._resources.get(k, 0) < v:
                return False
        return True

    @property
    def resources(self):
        return self._resources.copy()

    def spend(self, cost):
        for k, v in cost.items():
            if self._resources.get(k, 0) < v:
                return False
            self._resources[k] -= v
        return True


def test_strategy_draws_from_any_pool_when_pool_id_empty():
    """pool_id='' 时，从当前任意可用池子抽卡"""
    strategy = DrawTargetStrategy(target_card_ids=set(), pool_id='')

    pool_a = _FakePool('pool_a', {'draw_resource': 160})
    state = _FakeState({'draw_resource': 1000})

    ctx = StrategyContext(
        state=state,
        current_pools=[pool_a],
        all_pools=[],
        future_schedules=[],
        target_cards={},
        stop_condition=None,
        _pity_engine=None,
        _pity_state=None,
        acquired={},
        pool_draw_counts={},
        total_draws=0,
        last_draw_pity_triggered=False,
        ssr_ids=set(),
        _pity_cache={},
    )

    action = strategy.select_action(ctx)
    assert isinstance(action, DrawAction), f"应返回 DrawAction，实际: {type(action)}"
    assert action.pool_id == 'pool_a', f"应从 pool_a 抽卡，实际: {action.pool_id}"


def test_strategy_draws_from_specific_pool_when_pool_id_set():
    """pool_id 指定时，只从指定池子抽卡"""
    strategy = DrawTargetStrategy(target_card_ids=set(), pool_id='pool_b')

    pool_a = _FakePool('pool_a', {'draw_resource': 160})
    pool_b = _FakePool('pool_b', {'draw_resource': 160})
    state = _FakeState({'draw_resource': 1000})

    ctx = StrategyContext(
        state=state,
        current_pools=[pool_a, pool_b],
        all_pools=[],
        future_schedules=[],
        target_cards={},
        stop_condition=None,
        _pity_engine=None,
        _pity_state=None,
        acquired={},
        pool_draw_counts={},
        total_draws=0,
        last_draw_pity_triggered=False,
        ssr_ids=set(),
        _pity_cache={},
    )

    action = strategy.select_action(ctx)
    assert isinstance(action, DrawAction)
    assert action.pool_id == 'pool_b', f"应从 pool_b 抽卡，实际: {action.pool_id}"


def test_strategy_waits_when_cannot_afford():
    """资源不够时返回 WaitAction"""
    strategy = DrawTargetStrategy(target_card_ids=set(), pool_id='')

    pool_a = _FakePool('pool_a', {'draw_resource': 160})
    state = _FakeState({'draw_resource': 100})  # 不够

    ctx = StrategyContext(
        state=state,
        current_pools=[pool_a],
        all_pools=[],
        future_schedules=[],
        target_cards={},
        stop_condition=None,
        _pity_engine=None,
        _pity_state=None,
        acquired={},
        pool_draw_counts={},
        total_draws=0,
        last_draw_pity_triggered=False,
        ssr_ids=set(),
        _pity_cache={},
    )

    action = strategy.select_action(ctx)
    assert isinstance(action, WaitAction), f"资源不够应等待，实际: {type(action)}"


def test_strategy_created_via_factory():
    """create_strategy('draw_target', params) 正确构造 DrawTargetStrategy"""
    strategy = create_strategy('draw_target', {
        'target_card_ids': ['card_a', 'card_b'],
        'pool_id': 'test_pool',
    })
    assert isinstance(strategy, DrawTargetStrategy)
    assert strategy.pool_id == 'test_pool'
    assert strategy.target_card_ids == {'card_a', 'card_b'}


def test_strategy_created_via_factory_empty_pool_id():
    """create_strategy('draw_target') 空 pool_id 也能正确构造（批量模式）"""
    strategy = create_strategy('draw_target', {'pool_id': ''})
    assert isinstance(strategy, DrawTargetStrategy)
    assert strategy.pool_id == ''
    assert strategy.target_card_ids == set()


# ============================================================
# 测试 2: ConsecutivePoolTargetCondition 停止条件
# ============================================================

class _FakeStats:
    def __init__(self, card_counts=None):
        self.card_counts = dict(card_counts or {})


def test_stop_when_pool_ended_without_target():
    """池子结束但未拿到目标卡 → 应停止"""
    cond = ConsecutivePoolTargetCondition(
        pool_schedules=[('pool_a', 0, 86400)],  # 0-1天
        pool_targets={'pool_a': 'card_a'},
        resource_name='draw_resource',
    )

    state = _FakeState({'draw_resource': 1000}, real_time=90000)  # > pool_a end
    stats = _FakeStats({'card_a': 0})  # 没拿到

    assert cond.check(state, [], stats) is True, "池结束未拿到目标卡，应停止"


def test_continue_when_pool_ended_with_target():
    """池子结束且拿到目标卡 → 应继续"""
    cond = ConsecutivePoolTargetCondition(
        pool_schedules=[('pool_a', 0, 86400)],
        pool_targets={'pool_a': 'card_a'},
        resource_name='draw_resource',
    )

    state = _FakeState({'draw_resource': 1000}, real_time=90000)
    stats = _FakeStats({'card_a': 1})  # 拿到了

    assert cond.check(state, [], stats) is False, "池结束拿到目标卡，应继续"


def test_no_check_unfinished_pool():
    """未结束的池子不检查（break 逻辑）"""
    cond = ConsecutivePoolTargetCondition(
        pool_schedules=[
            ('pool_a', 0, 86400),        # 0-1天, 已结束
            ('pool_b', 86400, 172800),   # 1-2天, 未结束
        ],
        pool_targets={'pool_a': 'card_a', 'pool_b': 'card_b'},
        resource_name='draw_resource',
    )

    state = _FakeState({'draw_resource': 1000}, real_time=90000)  # 在 pool_b 期间
    stats = _FakeStats({'card_a': 1, 'card_b': 0})  # pool_a 拿到了, pool_b 没拿到

    # pool_a 结束且拿到 → OK
    # pool_b 未结束 → break, 不检查 → 不停止
    assert cond.check(state, [], stats) is False, "未结束的池子不应触发停止"


def test_stop_on_resource_exhausted():
    """资源耗尽 → 直接停止，不检查池子"""
    cond = ConsecutivePoolTargetCondition(
        pool_schedules=[('pool_a', 0, 86400)],
        pool_targets={'pool_a': 'card_a'},
        resource_name='draw_resource',
    )

    state = _FakeState({'draw_resource': 0}, real_time=100)
    assert cond.check(state, [], None) is True, "资源耗尽应停止"


def test_first_pool_fails_stops_immediately():
    """第一个池子就失败 → 立即停止，后续池子不会被检查"""
    cond = ConsecutivePoolTargetCondition(
        pool_schedules=[
            ('pool_a', 0, 86400),
            ('pool_b', 86400, 172800),
        ],
        pool_targets={'pool_a': 'card_a', 'pool_b': 'card_b'},
        resource_name='draw_resource',
    )

    state = _FakeState({'draw_resource': 1000}, real_time=90000)
    stats = _FakeStats({'card_a': 0, 'card_b': 1})  # pool_a 失败, pool_b 却有 card_b?

    # schedules 按 end_time 排序，先检查 pool_a
    assert cond.check(state, [], stats) is True, "第一个池失败应立即停止"
