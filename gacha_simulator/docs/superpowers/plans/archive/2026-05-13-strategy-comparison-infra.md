# 策略比较基础设施改造计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为策略比较功能改造底层基础设施：新增策略注册表、策略工厂函数、3种新策略类，修改 worker 支持策略选择，更新所有现有面板的 `run_batch_parallel` 调用。

**Architecture:** 在 `batch_simulator.py` 中新增 `STRATEGY_REGISTRY` 注册表和策略工厂函数。修改 `_wk_init`/`_wk_run_single` 从注册表动态创建策略。所有现有面板的 `run_batch_parallel` 调用传入 `strategy_name='smart'` 和 `strategy_params={}` 以保持向后兼容。

**Tech Stack:** Python 3, PyQt6

---

## 现状分析

### 当前策略体系

| 策略 | 位置 | 行为 | 可配置参数 |
|------|------|------|-----------|
| `_SmartStrategy` | `batch_simulator.py` | 优先兑换→按目标追卡→等待 | target_set |
| `TargetHuntingStrategy` | `core/strategy.py` | 只从指定池抽卡 | target_pool_ids |
| `FixedCountStrategy` | `core/strategy.py` | 抽指定次数 | count |
| `CompositeStrategy` | `core/strategy.py` | 组合多个策略 | strategies, mode |

### 关键问题

1. **所有批量模拟都硬编码使用 `_SmartStrategy`** — `run_batch_parallel` 内部直接创建 `_SmartStrategy`
2. **没有策略注册表** — 策略选择是 config_panel 中的硬编码下拉框
3. **ConfigStore 只存 `strategy_type` 字符串** — 没有策略参数的存储结构

---

## 设计方案

### 策略注册表设计

```python
STRATEGY_REGISTRY = {
    'smart': {
        'display_name': '按需追卡',
        'description': '优先兑换→按目标追卡→等待下一个池',
        'factory': _create_smart_strategy,
        'params': {},
    },
    'pool_quota': {
        'display_name': '指定池配额',
        'description': '在指定池子抽指定数量后切换',
        'factory': _create_pool_quota_strategy,
        'params': {
            'pool_quotas': {
                'type': 'pool_int_map',
                'display_name': '各池配额',
                'default': {},
            },
        },
    },
    'pity_reserve': {
        'display_name': '保底预留',
        'description': '只在大保底概率≥阈值时才抽卡',
        'factory': _create_pity_reserve_strategy,
        'params': {
            'pity_threshold_pct': {
                'type': 'float',
                'display_name': '保底概率阈值(%)',
                'default': 80.0,
                'min': 0.0,
                'max': 100.0,
            },
        },
    },
    'stop_on_target': {
        'display_name': '目标即停',
        'description': '抽到当期up/目标卡就停止',
        'factory': _create_stop_on_target_strategy,
        'params': {
            'stop_on_featured': {
                'type': 'bool',
                'display_name': '抽到up即停',
                'default': True,
            },
            'stop_on_any_target': {
                'type': 'bool',
                'display_name': '抽到任意目标即停',
                'default': False,
            },
        },
    },
}
```

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `gui/batch_simulator.py` | 修改 | 新增 STRATEGY_REGISTRY、策略工厂函数、修改 _wk_init/_wk_run_single 支持策略选择 |
| `gui/gacha_panel.py` | 修改 | run_batch_parallel 调用传入 strategy_name/strategy_params |
| `gui/strategy_panel.py` | 修改 | run_batch_parallel 调用传入 strategy_name/strategy_params |
| `gui/resource_search_panel.py` | 修改 | run_batch_parallel 调用传入 strategy_name/strategy_params |

---

### Task 1: 在 batch_simulator.py 中新增策略注册表和工厂函数

**Files:**
- Modify: `gacha_simulator/gui/batch_simulator.py`

- [x] **Step 1: 新增 PoolQuotaStrategy、PityReserveStrategy、StopOnTargetStrategy 类**

在 `_AllPoolsEnd` 类之后、`_wk_run_single` 之前，新增：

```python
class _PoolQuotaStrategy:
    lookahead = None

    def __init__(self, target_set, pool_quotas=None):
        self.target_set = target_set
        self.acquired = {}
        self.pool_quotas = pool_quotas or {}
        self.pool_draw_counts = {}

    def select_action(self, state, history, current_pools, future_schedules, target_cards, stop_cond):
        from gacha_simulator.core.action import DrawAction, WaitAction

        for t in self.target_set.targets:
            if self.acquired.get(t.card_id, 0) >= t.quantity_needed:
                continue
            for pool in _wk_pools:
                if pool.is_exchange and pool.exchange_card_id == t.card_id:
                    if pool.is_available_at(state.real_time) and state.can_afford(pool.cost):
                        return DrawAction(pool_id=pool.id)

        for pool in current_pools:
            if pool.is_exchange or not state.can_afford(pool.cost):
                continue
            pid = pool.id
            quota = self.pool_quotas.get(pid)
            drawn = self.pool_draw_counts.get(pid, 0)
            if quota is None or drawn < quota:
                if self._pool_needs_target(pool.id):
                    self.pool_draw_counts[pid] = drawn + 1
                    return DrawAction(pool_id=pid)

        for pool in current_pools:
            if not pool.is_exchange and state.can_afford(pool.cost):
                pid = pool.id
                quota = self.pool_quotas.get(pid)
                drawn = self.pool_draw_counts.get(pid, 0)
                if quota is None or drawn < quota:
                    self.pool_draw_counts[pid] = drawn + 1
                    return DrawAction(pool_id=pid)

        wait_time = 86400
        for pool in current_pools:
            if hasattr(pool, 'available_until') and pool.available_until and pool.available_until > state.real_time:
                wait_time = min(wait_time, pool.available_until - state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)

    def _pool_needs_target(self, pool_id):
        for t in self.target_set.targets:
            for pid in t.pool_ids:
                if pid == pool_id and self.acquired.get(t.card_id, 0) < t.quantity_needed:
                    return True
        return False

    def observe(self, iv):
        if iv.action_type == 'draw' and iv.card_id:
            self.acquired[iv.card_id] = self.acquired.get(iv.card_id, 0) + 1


class _PityReserveStrategy:
    lookahead = None

    def __init__(self, target_set, pity_threshold_pct=80.0):
        self.target_set = target_set
        self.acquired = {}
        self.pity_threshold_pct = pity_threshold_pct / 100.0

    def select_action(self, state, history, current_pools, future_schedules, target_cards, stop_cond):
        from gacha_simulator.core.action import DrawAction, WaitAction

        for t in self.target_set.targets:
            if self.acquired.get(t.card_id, 0) >= t.quantity_needed:
                continue
            for pool in _wk_pools:
                if pool.is_exchange and pool.exchange_card_id == t.card_id:
                    if pool.is_available_at(state.real_time) and state.can_afford(pool.cost):
                        return DrawAction(pool_id=pool.id)

        for pool in current_pools:
            if pool.is_exchange or not state.can_afford(pool.cost):
                continue
            if not self._pool_needs_target(pool.id):
                continue

            if _wk_pity_engine:
                from gacha_simulator.core.pity import PityState
                ps = PityState()
                if _wk_pity_state_init and 'counters' in _wk_pity_state_init:
                    for cname, cval in _wk_pity_state_init['counters'].items():
                        ps.counters[cname] = cval
                for iv in history:
                    if iv.action_type == 'draw' and iv.pool_id == pool.id:
                        _wk_pity_engine.after_draw(pool.id, ps, iv.card_id)
                probs = {r.id: p for r, p in pool.rewards}
                modified = _wk_pity_engine.before_draw(pool.id, ps, probs)
                ssr_prob = sum(p for cid, p in modified.items() if 'ssr' in cid.lower())
                if ssr_prob >= self.pity_threshold_pct:
                    return DrawAction(pool_id=pool.id)
            else:
                return DrawAction(pool_id=pool.id)

        wait_time = 86400
        for pool in current_pools:
            if hasattr(pool, 'available_until') and pool.available_until and pool.available_until > state.real_time:
                wait_time = min(wait_time, pool.available_until - state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)

    def _pool_needs_target(self, pool_id):
        for t in self.target_set.targets:
            for pid in t.pool_ids:
                if pid == pool_id and self.acquired.get(t.card_id, 0) < t.quantity_needed:
                    return True
        return False

    def observe(self, iv):
        if iv.action_type == 'draw' and iv.card_id:
            self.acquired[iv.card_id] = self.acquired.get(iv.card_id, 0) + 1


class _StopOnTargetStrategy:
    lookahead = None

    def __init__(self, target_set, stop_on_featured=True, stop_on_any_target=False):
        self.target_set = target_set
        self.acquired = {}
        self.stop_on_featured = stop_on_featured
        self.stop_on_any_target = stop_on_any_target
        self._stopped = False

    def select_action(self, state, history, current_pools, future_schedules, target_cards, stop_cond):
        from gacha_simulator.core.action import DrawAction, WaitAction

        if self._stopped:
            return WaitAction(duration=0)

        for t in self.target_set.targets:
            if self.acquired.get(t.card_id, 0) >= t.quantity_needed:
                continue
            for pool in _wk_pools:
                if pool.is_exchange and pool.exchange_card_id == t.card_id:
                    if pool.is_available_at(state.real_time) and state.can_afford(pool.cost):
                        return DrawAction(pool_id=pool.id)

        for pool in current_pools:
            if not pool.is_exchange and self._pool_needs_target(pool.id) and state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)

        wait_time = 86400
        for pool in current_pools:
            if hasattr(pool, 'available_until') and pool.available_until and pool.available_until > state.real_time:
                wait_time = min(wait_time, pool.available_until - state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)

    def _pool_needs_target(self, pool_id):
        for t in self.target_set.targets:
            for pid in t.pool_ids:
                if pid == pool_id and self.acquired.get(t.card_id, 0) < t.quantity_needed:
                    return True
        return False

    def observe(self, iv):
        if iv.action_type == 'draw' and iv.card_id:
            self.acquired[iv.card_id] = self.acquired.get(iv.card_id, 0) + 1
            if self.stop_on_featured and iv.pity_triggered:
                self._stopped = True
            if self.stop_on_any_target and iv.card_id in {t.card_id for t in self.target_set.targets}:
                self._stopped = True
```

- [x] **Step 2: 新增策略工厂函数和注册表**

在 `_StopOnTargetStrategy` 之后、`_wk_run_single` 之前，新增：

```python
def _create_smart_strategy(target_set, params):
    return _SmartStrategy(target_set)

def _create_pool_quota_strategy(target_set, params):
    quotas = params.get('pool_quotas', {})
    return _PoolQuotaStrategy(target_set, pool_quotas=quotas)

def _create_pity_reserve_strategy(target_set, params):
    pct = params.get('pity_threshold_pct', 80.0)
    return _PityReserveStrategy(target_set, pity_threshold_pct=pct)

def _create_stop_on_target_strategy(target_set, params):
    featured = params.get('stop_on_featured', True)
    any_target = params.get('stop_on_any_target', False)
    return _StopOnTargetStrategy(target_set, stop_on_featured=featured, stop_on_any_target=any_target)


STRATEGY_REGISTRY = {
    'smart': {
        'display_name': '按需追卡',
        'description': '优先兑换→按目标追卡→等待下一个池',
        'factory': _create_smart_strategy,
        'params': {},
    },
    'pool_quota': {
        'display_name': '指定池配额',
        'description': '在指定池子抽指定数量后切换',
        'factory': _create_pool_quota_strategy,
        'params': {
            'pool_quotas': {
                'type': 'pool_int_map',
                'display_name': '各池配额',
                'default': {},
            },
        },
    },
    'pity_reserve': {
        'display_name': '保底预留',
        'description': '只在大保底概率≥阈值时才抽卡',
        'factory': _create_pity_reserve_strategy,
        'params': {
            'pity_threshold_pct': {
                'type': 'float',
                'display_name': '保底概率阈值(%)',
                'default': 80.0,
                'min': 0.0,
                'max': 100.0,
            },
        },
    },
    'stop_on_target': {
        'display_name': '目标即停',
        'description': '抽到当期up/目标卡就停止',
        'factory': _create_stop_on_target_strategy,
        'params': {
            'stop_on_featured': {
                'type': 'bool',
                'display_name': '抽到up即停',
                'default': True,
            },
            'stop_on_any_target': {
                'type': 'bool',
                'display_name': '抽到任意目标即停',
                'default': False,
            },
        },
    },
}
```

- [x] **Step 3: 修改 _wk_init 和 _wk_run_single 支持策略选择**

在 `_wk_init` 中新增全局变量：

```python
_wk_strategy_name = 'smart'
_wk_strategy_params = {}
```

修改 `_wk_init` 签名，新增 `strategy_name` 和 `strategy_params` 参数：

```python
def _wk_init(
    pools,
    schedule_mgr,
    end_time,
    pity_engine,
    resource_gain,
    pity_state_init,
    card_defs,
    strategy_name,
    strategy_params,
):
    global _wk_pools, _wk_schedule_mgr, _wk_end_time
    global _wk_pity_engine, _wk_resource_gain, _wk_pity_state_init, _wk_card_defs
    global _wk_strategy_name, _wk_strategy_params
    _wk_pools = pools
    _wk_schedule_mgr = schedule_mgr
    _wk_end_time = end_time
    _wk_pity_engine = pity_engine
    _wk_resource_gain = resource_gain
    _wk_pity_state_init = pity_state_init
    _wk_card_defs = card_defs
    _wk_strategy_name = strategy_name
    _wk_strategy_params = strategy_params
```

修改 `_wk_run_single`，将策略创建改为从注册表获取：

```python
    # 替换原来的:
    # strategy = _SmartStrategy(target_set)
    # 改为:
    strategy_factory = STRATEGY_REGISTRY.get(_wk_strategy_name, STRATEGY_REGISTRY['smart'])['factory']
    strategy = strategy_factory(target_set, _wk_strategy_params)
```

- [x] **Step 4: 修改 run_batch_parallel 签名和调用**

在 `run_batch_parallel` 中新增 `strategy_name='smart'` 和 `strategy_params=None` 参数。

在串行回退的 `_wk_init` 调用中添加这两个参数。

在 `MPPool` 的 `initargs` 中添加这两个参数。

---

### Task 2: 修改现有面板使用策略注册表

**Files:**
- Modify: `gacha_simulator/gui/gacha_panel.py`
- Modify: `gacha_simulator/gui/strategy_panel.py`
- Modify: `gacha_simulator/gui/resource_search_panel.py`

- [x] **Step 1: 修改 gacha_panel.py 的 run_batch_parallel 调用**

添加 `strategy_name='smart'` 和 `strategy_params={}` 参数。

- [x] **Step 2: 修改 strategy_panel.py 的 run_batch_parallel 调用**

同上。

- [x] **Step 3: 修改 resource_search_panel.py 的 run_batch_parallel 调用**

同上。

---

### Task 3: 验证

- [x] **Step 1: 编译检查**

```bash
cd /workspace && python -m py_compile gacha_simulator/gui/batch_simulator.py && \
python -m py_compile gacha_simulator/gui/gacha_panel.py && \
python -m py_compile gacha_simulator/gui/strategy_panel.py && \
python -m py_compile gacha_simulator/gui/resource_search_panel.py && \
echo "ALL OK"
```

- [x] **Step 2: 搜索残留引用**

确认所有 `run_batch_parallel` 调用都传了 `strategy_name` 和 `strategy_params`。
