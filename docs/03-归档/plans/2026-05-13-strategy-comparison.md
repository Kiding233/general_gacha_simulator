# 策略比较功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现策略比较面板，允许用户选择多种抽卡策略，在相同配置下并行运行模拟，对比各策略在 GDR、资源消耗、成功率等维度的表现。

**Architecture:** 新增 `StrategyComparisonPanel` 作为主窗口同级 Tab。在 `batch_simulator.py` 中新增策略工厂函数，根据策略名称创建 Strategy 实例。比较面板对每个策略调用 `run_batch_parallel`，收集结果后用表格和图表对比展示。

**Tech Stack:** Python 3, PyQt6, matplotlib

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

1. **`_SmartStrategy` 不继承 `Strategy` 基类** — 它是 batch_simulator.py 中的独立类，不实现 `observe()` 的标准接口（Strategy 基类没有 observe 方法，但 GachaService 会调用 `hasattr(strategy, 'acquired')`）
2. **所有批量模拟都硬编码使用 `_SmartStrategy`** — `run_batch_parallel` 内部的 `_wk_run_single` 直接创建 `_SmartStrategy`
3. **ConfigStore 只存 `strategy_type` 字符串** — 没有策略参数的存储结构
4. **没有策略注册表** — 策略选择是 config_panel 中的硬编码下拉框

---

## 设计方案

### 核心思路

1. 在 `batch_simulator.py` 中新增**策略注册表** `STRATEGY_REGISTRY`，注册所有可用策略及其参数
2. 修改 `_wk_run_single` 和 `_wk_init`，接受策略名称和参数，动态创建策略
3. 新增 `StrategyComparisonPanel`，让用户勾选多个策略，设置各策略参数，一键对比

### 策略注册表设计

```python
STRATEGY_REGISTRY = {
    'smart': {
        'display_name': '按需追卡',
        'description': '优先兑换→按目标追卡→等待下一个池',
        'factory': _create_smart_strategy,
        'params': {},  # 无额外参数，从 target_set 自动推断
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

### 新增策略类

1. **PoolQuotaStrategy** — 在指定池子抽指定数量后切换到下一个池。参数 `pool_quotas` 是 `{pool_id: count}` 映射。
2. **PityReserveStrategy** — 只在保底概率≥阈值时才抽卡。利用 pity_engine 的 `before_draw` 计算当前抽卡的大保底概率，低于阈值时等待。
3. **StopOnTargetStrategy** — 抽到当期up/目标卡就停止。通过 `observe()` 跟踪抽卡结果，一旦抽到目标卡就返回 `WaitAction(duration=0)` 让 stop_condition 生效。

### Worker 修改

`_wk_init` 新增 `_wk_strategy_name` 和 `_wk_strategy_params` 两个全局变量。`_wk_run_single` 根据策略名从注册表创建策略实例。

### 比较面板 UI

```
┌─ 策略选择 ──────────────────────────────┐
│ ☑ 按需追卡    ☑ 指定池配额  ☑ 保底预留   │
│ ☐ 目标即停                                │
│                                          │
│ [指定池配额 参数]                         │
│   池A配额: [10]  池B配额: [5]             │
├─ 模拟参数 ──────────────────────────────┤
│ 每策略模拟次数: [1000]                    │
│ 并行进程数: [4]                           │
│ GDR判定: [目标达成率 ▼]  阈值: [1.0]      │
├─ [开始比较]  [停止]                       │
│ ████████████████ 75%                      │
├─ 比较结果 ──────────────────────────────┤
│ ┌───────┬──────┬──────┬──────┬──────┐    │
│ │策略    │成功率│均值抽│SSR数 │GDR   │    │
│ ├───────┼──────┼──────┼──────┼──────┤    │
│ │按需追卡│95.2% │87.3  │3.1   │0.98  │    │
│ │指定配额│89.1% │92.7  │3.8   │0.91  │    │
│ │保底预留│78.3% │105.2 │2.7   │0.82  │    │
│ └───────┴──────┴──────┴──────┴──────┘    │
│                                          │
│ [GDR分布对比图] [资源消耗对比图]           │
└──────────────────────────────────────────┘
```

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `gui/batch_simulator.py` | 修改 | 新增 STRATEGY_REGISTRY、策略工厂函数、修改 _wk_init/_wk_run_single 支持策略选择 |
| `gui/strategy_comparison_panel.py` | 新建 | 策略比较面板 UI 和 Worker |
| `gui/main_window.py` | 修改 | 添加策略比较 Tab |

---

### Task 1: 在 batch_simulator.py 中新增策略注册表和工厂函数

**Files:**
- Modify: `gacha_simulator/gui/batch_simulator.py`

- [ ] **Step 1: 新增 PoolQuotaStrategy、PityReserveStrategy、StopOnTargetStrategy 类**

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

- [ ] **Step 2: 新增策略工厂函数和注册表**

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

- [ ] **Step 3: 修改 _wk_init 和 _wk_run_single 支持策略选择**

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

- [ ] **Step 4: 修改 run_batch_parallel 签名和调用**

在 `run_batch_parallel` 中新增 `strategy_name='smart'` 和 `strategy_params=None` 参数。

在串行回退的 `_wk_init` 调用中添加这两个参数。

在 `MPPool` 的 `initargs` 中添加这两个参数。

---

### Task 2: 新建策略比较面板

**Files:**
- Create: `gacha_simulator/gui/strategy_comparison_panel.py`

- [ ] **Step 1: 创建 StrategyComparisonWorker**

```python
class StrategyComparisonWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(dict)
    error = pyqtSignal(object)

    def __init__(self, strategies_config, num_simulations, max_workers,
                 gdr_key, gdr_threshold, config_store):
        super().__init__()
        self.strategies_config = strategies_config  # {name: params}
        self.num_simulations = num_simulations
        self.max_workers = max_workers
        self.gdr_key = gdr_key
        self.gdr_threshold = gdr_threshold
        self.config_store = config_store
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def run(self):
        try:
            from .batch_simulator import SimulationEnvBuilder, run_batch_parallel, STRATEGY_REGISTRY
            from gacha_simulator.core.gdr import compute_success_probability, compute_gdr_from_compact

            env = SimulationEnvBuilder.from_config_store(self.config_store)
            target_specs = {tc.card_id: getattr(tc, 'quantity', 1) for tc in getattr(self.config_store, 'target_cards', [])}

            results = {}
            total = len(self.strategies_config)
            for i, (strategy_name, strategy_params) in enumerate(self.strategies_config.items()):
                if self._should_stop:
                    self.finished.emit(None)
                    return

                display_name = STRATEGY_REGISTRY.get(strategy_name, {}).get('display_name', strategy_name)
                self.progress.emit(f"正在模拟策略: {display_name} ({i+1}/{total})", int((i / total) * 100))

                histories = run_batch_parallel(
                    pools=env.pools,
                    schedule_mgr=env.schedule_mgr,
                    end_time=env.end_time,
                    pity_engine=env.pity_engine,
                    resource_gain=env.resource_gain,
                    pity_state_init=env.pity_state_init,
                    card_defs=env.card_defs,
                    target_specs=target_specs,
                    initial_resources=env.initial_resources,
                    num_simulations=self.num_simulations,
                    max_workers=self.max_workers,
                    seed=0,
                    strategy_name=strategy_name,
                    strategy_params=strategy_params or {},
                )

                success_prob = compute_success_probability(histories, target_specs, self.gdr_key, self.gdr_threshold)

                valid = [h for h in histories if h is not None]
                avg_draws = sum(h.get('total_draws', 0) for h in valid) / max(len(valid), 1)
                avg_ssr = 0
                for h in valid:
                    cc = h.get('card_counts', {})
                    for cid, cnt in cc.items():
                        if 'ssr' in cid.lower():
                            avg_ssr += cnt
                avg_ssr /= max(len(valid), 1)

                avg_gdr = 0
                for h in valid:
                    avg_gdr += compute_gdr_from_compact(h, target_specs, self.gdr_key)
                avg_gdr /= max(len(valid), 1)

                results[strategy_name] = {
                    'display_name': display_name,
                    'success_probability': success_prob,
                    'avg_draws': avg_draws,
                    'avg_ssr': avg_ssr,
                    'avg_gdr': avg_gdr,
                    'histories': histories,
                }

            self.progress.emit("比较完成", 100)
            self.finished.emit(results)

        except Exception as e:
            import traceback as tb
            tb.print_exc()
            class DetailedError(Exception):
                def __init__(self, msg):
                    self.msg = msg
                def __str__(self):
                    return self.msg
            self.error.emit(DetailedError(f"{type(e).__name__}: {e}\n\n{tb.format_exc()}"))
```

- [ ] **Step 2: 创建 StrategyComparisonPanel**

面板包含：
- 策略勾选区（QCheckBox 列表，从 STRATEGY_REGISTRY 动态生成）
- 各策略的参数配置区（根据 params 定义动态生成控件）
- 模拟参数区（模拟次数、并行数、GDR选择、阈值）
- 结果对比表格
- 结果对比图表（matplotlib 嵌入）

详细 UI 代码见实现阶段。

---

### Task 3: 集成到主窗口

**Files:**
- Modify: `gacha_simulator/gui/main_window.py`

- [ ] **Step 1: 导入并添加 Tab**

在 main_window.py 中导入 `StrategyComparisonPanel`，在 `_setup_ui` 中添加：

```python
self.comparison_panel = StrategyComparisonPanel()
self.comparison_panel.set_store(self._store)
self.tabs.addTab(self.comparison_panel, "策略比较")
```

在 `_on_tab_changed` 中添加 store 同步。

---

### Task 4: 修改现有面板使用策略注册表

**Files:**
- Modify: `gacha_simulator/gui/gacha_panel.py`
- Modify: `gacha_simulator/gui/strategy_panel.py`
- Modify: `gacha_simulator/gui/resource_search_panel.py`

- [ ] **Step 1: 修改 gacha_panel.py 的 run_batch_parallel 调用**

添加 `strategy_name='smart'` 和 `strategy_params={}` 参数。

- [ ] **Step 2: 修改 strategy_panel.py 的 run_batch_parallel 调用**

同上。

- [ ] **Step 3: 修改 resource_search_panel.py 的 run_batch_parallel 调用**

同上。

---

### Task 5: 验证

- [ ] **Step 1: 编译检查**

```bash
cd /workspace && python -m py_compile gacha_simulator/gui/batch_simulator.py && \
python -m py_compile gacha_simulator/gui/strategy_comparison_panel.py && \
python -m py_compile gacha_simulator/gui/main_window.py && \
python -m py_compile gacha_simulator/gui/gacha_panel.py && \
python -m py_compile gacha_simulator/gui/strategy_panel.py && \
python -m py_compile gacha_simulator/gui/resource_search_panel.py && \
echo "ALL OK"
```

- [ ] **Step 2: 搜索残留引用**

确认所有 `run_batch_parallel` 调用都传了 `strategy_name` 和 `strategy_params`。
