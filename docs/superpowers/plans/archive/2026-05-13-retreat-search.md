# 退路方案搜索 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于脆弱性分析结果，搜索使成功率恢复至阈值以上的补救方案（最少额外资源 / 最多目标卡 / Pareto 前沿）

**Architecture:** 截断配置方案 — 构造只含后续池子的新 ConfigStore，复用现有 `run_batch_parallel` 接口。新增 `core/retreat_config.py`（截断配置构建器）、`core/retreat_search.py`（搜索引擎）、`gui/retreat_search_panel.py`（GUI 面板）。扩展 `run_simulation_compact` 记录保底快照，扩展脆弱性分析收集保底统计。

**Tech Stack:** Python 3.14, PyQt6, numpy, statsmodels, matplotlib

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `service/gacha_service.py` | 在 `run_simulation_compact` 中记录 `pool_end_pity_states` |
| Modify | `core/vulnerability.py` | 新增 `PityStatSnapshot`，扩展 `PoolVulnerabilityResult`，收集保底统计 |
| Modify | `core/__init__.py` | 导出新类型 |
| Create | `core/retreat_config.py` | `RetreatConfigBuilder` 截断配置构建器 |
| Create | `core/retreat_search.py` | `RetreatSearchEngine` 三种搜索模式 + 数据类 |
| Create | `gui/retreat_search_panel.py` | 退路方案搜索 GUI 面板 |
| Modify | `gui/main_window.py` | 添加新 tab 页 |
| Create | `tests/core/test_retreat_config.py` | 截断配置构建器测试 |
| Create | `tests/core/test_retreat_search.py` | 搜索引擎测试 |

---

### Task 1: 扩展模拟结果 — 记录池结束时的保底状态

**Files:**
- Modify: `gacha_simulator/service/gacha_service.py:253-341,372-387`
- Test: `tests/service/test_analysis_service.py`

- [ ] **Step 1: 在 `run_simulation_compact` 中新增 `pool_end_pity_states` 字典**

在 `pool_end_resources = {}` 之后添加 `pool_end_pity_states = {}`，在每次记录 `pool_end_resources[pid]` 的地方同时记录 `pool_end_pity_states[pid] = pity_state.to_dict()`。

在 `gacha_service.py` 约 253 行，`pool_end_resources = {}` 后面加：

```python
pool_end_pity_states = {}
```

在约 339-341 行，`pool_end_resources[pid] = dict(resources)` 后面加：

```python
pool_end_pity_states[pid] = pity_state.to_dict()
```

同样在约 359-361 行和 368-370 行的另外两处 `pool_end_resources[pid]` 记录点后面加同样的 `pool_end_pity_states[pid] = pity_state.to_dict()`。

在返回字典（约 372-387 行）中添加：

```python
'pool_end_pity_states': pool_end_pity_states,
```

- [ ] **Step 2: 验证编译通过**

Run: `cd /workspace && python -c "from gacha_simulator.service.gacha_service import GachaService; print('OK')"`

- [ ] **Step 3: 写测试验证 `pool_end_pity_states` 存在于返回结果中**

在 `tests/service/test_analysis_service.py` 末尾添加测试（如果文件不存在则创建）：

```python
def test_pool_end_pity_states_in_compact_result():
    from gacha_simulator.core import GachaState, TargetCard, TargetCardSet
    from gacha_simulator.service import GachaService
    from gacha_simulator.core.pool import Pool, Reward
    from gacha_simulator.core.stop_condition import TimeLimitCondition
    from gacha_simulator.core.strategy import FixedCountStrategy
    from gacha_simulator.core.schedule import PoolScheduleManager, PoolSchedule

    pool = Pool(
        id='test_pool',
        name='Test',
        cost=[{'draw_resource': 160}],
        rewards=[(Reward(id='card_a', name='A', resources_gained={}), 1.0)],
        available_from=0,
        available_until=86400 * 21,
    )
    schedules = [PoolSchedule(pool_id='test_pool', available_from=0, available_until=86400 * 21)]
    schedule_mgr = PoolScheduleManager(schedules)
    target = TargetCard(card_id='card_a', pool_ids=['test_pool'], quantity_needed=1)
    target_set = TargetCardSet([target])
    strategy = FixedCountStrategy(count=5)
    stop_cond = TimeLimitCondition(max_time=86400 * 21)

    service = GachaService(
        [pool], strategy, stop_cond, target_set,
        schedule_manager=schedule_mgr,
    )
    state = GachaState(resources={'draw_resource': 100000})
    result = service.run_simulation_compact(state)

    assert 'pool_end_pity_states' in result
    assert isinstance(result['pool_end_pity_states'], dict)
```

- [ ] **Step 4: 运行测试**

Run: `cd /workspace && python -m pytest tests/service/test_analysis_service.py::test_pool_end_pity_states_in_compact_result -v`
Expected: PASS

---

### Task 2: 扩展脆弱性分析 — 收集保底计数器统计

**Files:**
- Modify: `gacha_simulator/core/vulnerability.py:6-30,93-213`
- Modify: `gacha_simulator/core/__init__.py:39-42,73-74`

- [ ] **Step 1: 新增 `PityStatSnapshot` 数据类并扩展 `PoolVulnerabilityResult`**

在 `vulnerability.py` 的 `VulnerabilityInterval` 类之后添加：

```python
@dataclass
class PityStatSnapshot:
    counter_name: str
    mean: float
    median: float
    p25: float
    p75: float
```

在 `PoolVulnerabilityResult` 中新增字段：

```python
pity_stats_at_pool_end: Dict[str, PityStatSnapshot] = field(default_factory=dict)
```

注意：需要在文件顶部确认 `field` 已从 `dataclasses` 导入（当前只有 `dataclass`，需要加 `field`）。

- [ ] **Step 2: 在 `compute_vulnerability_analysis` 中收集保底统计**

在 `compute_vulnerability_analysis` 函数中，对每个池子的模拟结果，提取 `pool_end_pity_states` 并计算统计量。

在 `for pool_id in sorted(all_pool_ids):` 循环内，`arr_failure = np.array(failure_flags)` 之后，添加保底统计收集逻辑：

```python
pity_snapshots = {}
pity_records = {}
for r in reached:
    pes = r.get('pool_end_pity_states', {})
    if pool_id in pes:
        counters = pes[pool_id].get('counters', {})
        for cname, cval in counters.items():
            if cname not in pity_records:
                pity_records[cname] = []
            pity_records[cname].append(cval)

for cname, vals in pity_records.items():
    arr = np.array(vals)
    pity_snapshots[cname] = PityStatSnapshot(
        counter_name=cname,
        mean=float(np.mean(arr)),
        median=float(np.median(arr)),
        p25=float(np.percentile(arr, 25)),
        p75=float(np.percentile(arr, 75)),
    )
```

在 `pool_results.append(PoolVulnerabilityResult(...))` 中添加 `pity_stats_at_pool_end=pity_snapshots`。

- [ ] **Step 3: 更新 `core/__init__.py` 导出**

在 `from .vulnerability import (...)` 中添加 `PityStatSnapshot`。

在 `__all__` 列表中添加 `'PityStatSnapshot'`。

- [ ] **Step 4: 运行现有测试确保不回归**

Run: `cd /workspace && python -m pytest tests/core/test_vulnerability.py -v`
Expected: 12 passed

- [ ] **Step 5: 写测试验证保底统计收集**

在 `tests/core/test_vulnerability.py` 中添加：

```python
def test_pity_stats_collected():
    from gacha_simulator.core.vulnerability import compute_vulnerability_analysis, PityStatSnapshot
    results = []
    for i in range(100):
        remaining = max(0, i * 50 + np.random.uniform(-100, 100))
        succeeded = remaining >= 3000
        results.append({
            'pool_end_resources': {'pool_A': {'draw_resource': remaining}},
            'pool_end_pity_states': {'pool_A': {'counters': {'soft_pity': i % 90}}},
            'card_counts': {'card_a': 1} if succeeded else {'card_a': 0},
            'final_resources': {'draw_resource': remaining},
            'total_draws': 10,
        })
    analysis = compute_vulnerability_analysis(
        results, {'card_a': 1}, alpha=0.5, num_bins=10,
    )
    assert len(analysis.pool_results) == 1
    pr = analysis.pool_results[0]
    assert isinstance(pr.pity_stats_at_pool_end, dict)
    if 'soft_pity' in pr.pity_stats_at_pool_end:
        snap = pr.pity_stats_at_pool_end['soft_pity']
        assert isinstance(snap, PityStatSnapshot)
        assert snap.counter_name == 'soft_pity'
        assert snap.mean >= 0
```

- [ ] **Step 6: 运行新测试**

Run: `cd /workspace && python -m pytest tests/core/test_vulnerability.py::test_pity_stats_collected -v`
Expected: PASS

---

### Task 3: 实现截断配置构建器

**Files:**
- Create: `gacha_simulator/core/retreat_config.py`
- Create: `tests/core/test_retreat_config.py`

- [ ] **Step 1: 写截断配置构建器的测试**

创建 `tests/core/test_retreat_config.py`：

```python
import pytest
from gacha_simulator.core.config_store import (
    ConfigStore, PoolEntry, PityConfig, PityDef, GainRule, DayOverride,
    TargetCardEntry, CardDefEntry,
)
from gacha_simulator.core.retreat_config import RetreatConfigBuilder


def _make_store_with_3_pools():
    store = ConfigStore()
    store.pools = [
        PoolEntry(pool_id='pool_1', name='池1', start_day=0, end_day=21),
        PoolEntry(pool_id='pool_2', name='池2', start_day=21, end_day=42),
        PoolEntry(pool_id='pool_3', name='池3', start_day=42, end_day=63),
    ]
    store.pity = PityConfig(enabled=True, pities=[
        PityDef(name='soft_pity', btype='soft', params={'start': '74', 'end': '90'}),
    ])
    store.gain_rules = [
        GainRule(rule_type='every_n_days', param='1', gains={'draw_resource': 100}),
    ]
    store.day_overrides = [
        DayOverride(day=5, gains={'draw_resource': 500}),
        DayOverride(day=30, gains={'draw_resource': 1000}),
        DayOverride(day=50, gains={'draw_resource': 2000}),
    ]
    store.initial_resources = {'draw_resource': 30000}
    store.target_cards = [
        TargetCardEntry(card_id='card_a', quantity=1),
        TargetCardEntry(card_id='card_b', quantity=1),
    ]
    store.card_defs = [
        CardDefEntry(card_id='card_a', name='A', rarity='SSR', pools=['pool_1', 'pool_2']),
        CardDefEntry(card_id='card_b', name='B', rarity='SSR', pools=['pool_3']),
    ]
    return store


def test_truncate_removes_earlier_pools():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    pool_ids = [p.pool_id for p in truncated.pools]
    assert 'pool_1' not in pool_ids
    assert 'pool_2' not in pool_ids
    assert 'pool_3' in pool_ids
    assert len(truncated.pools) == 1


def test_truncate_offsets_pool_days():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    pool_3 = truncated.pools[0]
    assert pool_3.start_day == 0
    assert pool_3.end_day == 21


def test_truncate_sets_initial_resources():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    assert truncated.initial_resources == {'draw_resource': 5000}


def test_truncate_sets_pity_counter_init():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    assert truncated.pity.counter_init == {'soft_pity': 30}


def test_truncate_offsets_day_overrides():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    override_days = [o.day for o in truncated.day_overrides]
    assert 5 not in override_days
    assert 8 in override_days
    assert 28 in override_days


def test_truncate_preserves_gain_rules():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    assert len(truncated.gain_rules) == 1
    assert truncated.gain_rules[0].rule_type == 'every_n_days'


def test_truncate_preserves_target_cards():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    tc_ids = [tc.card_id for tc in truncated.target_cards]
    assert 'card_a' in tc_ids
    assert 'card_b' in tc_ids


def test_truncate_preserves_card_defs():
    store = _make_store_with_3_pools()
    truncated = RetreatConfigBuilder.build(
        original_store=store,
        from_pool_id='pool_2',
        initial_resources={'draw_resource': 5000},
        pity_counter_init={'soft_pity': 30},
    )
    cd_ids = [cd.card_id for cd in truncated.card_defs]
    assert 'card_a' in cd_ids
    assert 'card_b' in cd_ids
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /workspace && python -m pytest tests/core/test_retreat_config.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: 实现 `RetreatConfigBuilder`**

创建 `gacha_simulator/core/retreat_config.py`：

```python
from typing import Dict
from .config_store import (
    ConfigStore, PoolEntry, PityConfig, PityDef, GainRule, DayOverride,
    TargetCardEntry, CardDefEntry,
)


class RetreatConfigBuilder:
    @staticmethod
    def build(
        original_store: ConfigStore,
        from_pool_id: str,
        initial_resources: Dict[str, float],
        pity_counter_init: Dict[str, int],
    ) -> ConfigStore:
        from_pool = None
        for p in original_store.pools:
            if p.pool_id == from_pool_id:
                from_pool = p
                break

        if from_pool is None:
            raise ValueError(f"Pool '{from_pool_id}' not found in config")

        offset_day = from_pool.end_day if from_pool.end_day > 0 else (from_pool.start_day + 21)

        truncated = ConfigStore()

        truncated.pools = []
        for p in original_store.pools:
            if p.start_day >= offset_day:
                new_start = p.start_day - offset_day
                new_end = p.end_day - offset_day
                truncated.pools.append(PoolEntry(
                    enabled=p.enabled,
                    pool_id=p.pool_id,
                    name=p.name,
                    start_day=new_start,
                    end_day=new_end,
                    cost=p.cost,
                    distribution_file=p.distribution_file,
                    bindings=dict(p.bindings),
                    target_specs=list(p.target_specs),
                    rerun_of=p.rerun_of,
                    exchange_card_id=p.exchange_card_id,
                    distribution=list(p.distribution),
                ))

        truncated.pity = PityConfig(
            enabled=original_store.pity.enabled,
            pities=[PityDef(
                name=pd.name,
                btype=pd.btype,
                params=dict(pd.params),
                target_distribution=dict(pd.target_distribution),
                reset_condition=pd.reset_condition,
                pools=pd.pools,
            ) for pd in original_store.pity.pities],
            counter_init=dict(pity_counter_init),
        )

        truncated.initial_resources = dict(initial_resources)

        truncated.gain_rules = [
            GainRule(
                rule_type=gr.rule_type,
                param=gr.param,
                gains=dict(gr.gains),
            )
            for gr in original_store.gain_rules
        ]

        truncated.day_overrides = []
        for dor in original_store.day_overrides:
            new_day = dor.day - offset_day
            if new_day >= 0:
                truncated.day_overrides.append(DayOverride(
                    day=new_day,
                    gains=dict(dor.gains),
                ))

        truncated.target_cards = [
            TargetCardEntry(
                card_id=tc.card_id,
                quantity=tc.quantity,
                pool_ids=list(tc.pool_ids),
            )
            for tc in original_store.target_cards
        ]

        truncated.card_defs = [
            CardDefEntry(
                card_id=cd.card_id,
                name=cd.name,
                rarity=cd.rarity,
                pools=list(cd.pools),
            )
            for cd in original_store.card_defs
        ]

        truncated.resource_defs = dict(original_store.resource_defs)
        truncated.strategy_type = original_store.strategy_type
        truncated.auto_wait = original_store.auto_wait

        return truncated
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd /workspace && python -m pytest tests/core/test_retreat_config.py -v`
Expected: All PASS

---

### Task 4: 实现退路搜索引擎

**Files:**
- Create: `gacha_simulator/core/retreat_search.py`
- Create: `tests/core/test_retreat_search.py`

- [ ] **Step 1: 定义搜索结果数据类**

创建 `gacha_simulator/core/retreat_search.py`，先写数据类和引擎骨架：

```python
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field


@dataclass
class RetreatSearchPoint:
    extra_resource: float
    target_specs: Dict[str, int]
    success_probability: float


@dataclass
class RetreatSearchResult:
    from_pool_id: str
    base_resource: float
    pity_init: Dict[str, int]
    search_mode: str
    points: List[RetreatSearchPoint] = field(default_factory=list)


class RetreatSearchEngine:
    def __init__(
        self,
        config_store,
        from_pool_id: str,
        base_resource: float,
        pity_counter_init: Dict[str, int],
        success_threshold: float = 0.95,
        gdr_key: str = 'all_targets',
        gdr_threshold: float = 1.0,
        num_simulations: int = 500,
        max_workers: int = 4,
        max_binary_iterations: int = 20,
        precision_draws: int = 1,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ):
        self.config_store = config_store
        self.from_pool_id = from_pool_id
        self.base_resource = base_resource
        self.pity_counter_init = pity_counter_init
        self.success_threshold = success_threshold
        self.gdr_key = gdr_key
        self.gdr_threshold = gdr_threshold
        self.num_simulations = num_simulations
        self.max_workers = max_workers
        self.max_binary_iterations = max_binary_iterations
        self.precision_draws = precision_draws
        self.progress_callback = progress_callback or (lambda msg, pct: None)
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def _build_truncated_env(self, target_specs, initial_resource_value):
        from .retreat_config import RetreatConfigBuilder
        truncated_store = RetreatConfigBuilder.build(
            original_store=self.config_store,
            from_pool_id=self.from_pool_id,
            initial_resources={'draw_resource': initial_resource_value},
            pity_counter_init=self.pity_counter_init,
        )
        from gacha_simulator.gui.batch_simulator import SimulationEnvBuilder
        env = SimulationEnvBuilder.from_config_store(truncated_store)
        return env, truncated_store

    def _simulate_with_resource(self, env, target_specs, resource_value):
        from gacha_simulator.gui.batch_simulator import run_batch_parallel
        from gacha_simulator.core.gdr import compute_success_probability
        ir = dict(env.initial_resources)
        ir['draw_resource'] = resource_value
        histories = run_batch_parallel(
            pools=env.pools,
            schedule_mgr=env.schedule_mgr,
            end_time=env.end_time,
            pity_engine=env.pity_engine,
            resource_gain=env.resource_gain,
            pity_state_init=env.pity_state_init,
            card_defs=env.card_defs,
            target_specs=target_specs,
            initial_resources=ir,
            num_simulations=self.num_simulations,
            max_workers=self.max_workers,
            seed=0,
            strategy_name='smart',
            strategy_params={},
        )
        return compute_success_probability(histories, target_specs, self.gdr_key, self.gdr_threshold)

    def _extract_cost_per_draw(self, env):
        for p in env.pools:
            cost = p.cost
            if isinstance(cost, list) and cost:
                for opt in cost:
                    if isinstance(opt, dict):
                        return float(list(opt.values())[0])
            elif isinstance(cost, dict):
                return float(list(cost.values())[0])
        return 160

    def search_min_resource(self, target_specs: Dict[str, int]) -> RetreatSearchResult:
        self._should_stop = False
        result = RetreatSearchResult(
            from_pool_id=self.from_pool_id,
            base_resource=self.base_resource,
            pity_init=dict(self.pity_counter_init),
            search_mode='resource',
        )

        env, _ = self._build_truncated_env(target_specs, self.base_resource)
        cost_per_draw = self._extract_cost_per_draw(env)
        epsilon = cost_per_draw * self.precision_draws

        self.progress_callback("搜索上界...", 5)
        r_hi = 0.0
        prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_hi)

        if prob >= self.success_threshold:
            result.points.append(RetreatSearchPoint(
                extra_resource=0.0,
                target_specs=dict(target_specs),
                success_probability=prob,
            ))
            return result

        r_hi = cost_per_draw * 50
        prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_hi)
        doubling = 0
        while prob < self.success_threshold and doubling < 10:
            if self._should_stop:
                return result
            r_hi *= 2
            prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_hi)
            doubling += 1
            self.progress_callback(f"上界搜索: +{r_hi:.0f}, P={prob:.2%}", 10 + doubling * 3)

        r_lo = 0.0
        binary_iter = 0
        while r_hi - r_lo > epsilon and binary_iter < self.max_binary_iterations:
            if self._should_stop:
                return result
            binary_iter += 1
            r_mid = (r_lo + r_hi) / 2.0
            prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_mid)
            if prob >= self.success_threshold:
                r_hi = r_mid
            else:
                r_lo = r_mid
            pct = int(30 + 60 * binary_iter / max(self.max_binary_iterations, 1))
            self.progress_callback(f"二分 #{binary_iter}: +{r_mid:.0f}, P={prob:.2%}", min(pct, 95))

        final_prob = self._simulate_with_resource(env, target_specs, self.base_resource + r_hi)
        result.points.append(RetreatSearchPoint(
            extra_resource=r_hi,
            target_specs=dict(target_specs),
            success_probability=final_prob,
        ))
        self.progress_callback(f"最少额外资源: +{r_hi:.0f}, P={final_prob:.2%}", 100)
        return result

    def search_max_targets(self, target_specs: Dict[str, int]) -> RetreatSearchResult:
        self._should_stop = False
        result = RetreatSearchResult(
            from_pool_id=self.from_pool_id,
            base_resource=self.base_resource,
            pity_init=dict(self.pity_counter_init),
            search_mode='target',
        )

        env, _ = self._build_truncated_env(target_specs, self.base_resource)
        current_specs = dict(target_specs)
        card_ids = list(target_specs.keys())

        prob = self._simulate_with_resource(env, current_specs, self.base_resource)
        result.points.append(RetreatSearchPoint(
            extra_resource=0.0,
            target_specs=dict(current_specs),
            success_probability=prob,
        ))

        if prob >= self.success_threshold:
            return result

        for i, cid in enumerate(card_ids):
            if self._should_stop:
                break
            reduced_specs = dict(current_specs)
            del reduced_specs[cid]
            if not reduced_specs:
                break

            env, _ = self._build_truncated_env(reduced_specs, self.base_resource)
            prob = self._simulate_with_resource(env, reduced_specs, self.base_resource)
            current_specs = reduced_specs
            result.points.append(RetreatSearchPoint(
                extra_resource=0.0,
                target_specs=dict(current_specs),
                success_probability=prob,
            ))
            pct = int((i + 1) / len(card_ids) * 100)
            self.progress_callback(f"后退法: 移除 {cid}, 剩余 {len(current_specs)} 卡, P={prob:.2%}", pct)

            if prob >= self.success_threshold:
                break

        return result

    def search_pareto(self, target_specs: Dict[str, int]) -> RetreatSearchResult:
        self._should_stop = False
        result = RetreatSearchResult(
            from_pool_id=self.from_pool_id,
            base_resource=self.base_resource,
            pity_init=dict(self.pity_counter_init),
            search_mode='pareto',
        )

        current_specs = dict(target_specs)
        card_ids = list(target_specs.keys())

        self.progress_callback("Pareto: 搜索完整目标卡的最少资源...", 5)
        res_result = self.search_min_resource(current_specs)
        if res_result.points:
            result.points.append(res_result.points[-1])
        self._should_stop = False

        for i, cid in enumerate(card_ids):
            if self._should_stop:
                break
            reduced_specs = dict(current_specs)
            del reduced_specs[cid]
            if not reduced_specs:
                break

            self.progress_callback(f"Pareto: 移除 {cid}, 搜索剩余 {len(reduced_specs)} 卡的最少资源...", int(10 + 80 * (i + 1) / len(card_ids)))
            res_result = self.search_min_resource(reduced_specs)
            if res_result.points:
                result.points.append(res_result.points[-1])
            self._should_stop = False

            current_specs = reduced_specs

        return result
```

- [ ] **Step 2: 写搜索引擎的基础测试**

创建 `tests/core/test_retreat_search.py`：

```python
import pytest
from gacha_simulator.core.retreat_search import RetreatSearchEngine, RetreatSearchResult, RetreatSearchPoint


def test_search_result_dataclass():
    result = RetreatSearchResult(
        from_pool_id='pool_2',
        base_resource=5000.0,
        pity_init={'soft_pity': 30},
        search_mode='resource',
        points=[
            RetreatSearchPoint(extra_resource=12000.0, target_specs={'card_a': 1}, success_probability=0.96),
        ],
    )
    assert result.from_pool_id == 'pool_2'
    assert result.base_resource == 5000.0
    assert len(result.points) == 1
    assert result.points[0].extra_resource == 12000.0


def test_engine_init():
    from gacha_simulator.core.config_store import ConfigStore
    store = ConfigStore()
    engine = RetreatSearchEngine(
        config_store=store,
        from_pool_id='pool_1',
        base_resource=5000.0,
        pity_counter_init={'soft_pity': 0},
    )
    assert engine.from_pool_id == 'pool_1'
    assert engine.base_resource == 5000.0
```

- [ ] **Step 3: 运行测试**

Run: `cd /workspace && python -m pytest tests/core/test_retreat_search.py -v`
Expected: PASS

---

### Task 5: 实现退路方案搜索面板

**Files:**
- Create: `gacha_simulator/gui/retreat_search_panel.py`

- [ ] **Step 1: 实现面板 UI 和 Worker**

创建 `gacha_simulator/gui/retreat_search_panel.py`：

```python
import sys
import os
import traceback
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QProgressBar, QGroupBox, QFormLayout, QDoubleSpinBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QComboBox, QRadioButton, QButtonGroup,
    QScrollArea, QLineEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from gacha_simulator.core.config_store import ConfigStore
from gacha_simulator.core.gdr import COMPACT_GDR_REGISTRY


class RetreatSearchWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(object)
    error = pyqtSignal(object)

    def __init__(self, engine, target_specs, search_mode):
        super().__init__()
        self.engine = engine
        self.target_specs = target_specs
        self.search_mode = search_mode
        self._should_stop = False

    def stop(self):
        self._should_stop = True
        self.engine.stop()

    def run(self):
        try:
            self.progress.emit("正在构建截断配置...", 0)
            if self.search_mode == 'resource':
                result = self.engine.search_min_resource(self.target_specs)
            elif self.search_mode == 'target':
                result = self.engine.search_max_targets(self.target_specs)
            elif self.search_mode == 'pareto':
                result = self.engine.search_pareto(self.target_specs)
            else:
                raise ValueError(f"Unknown search mode: {self.search_mode}")
            self.finished.emit(result)
        except Exception as e:
            traceback.print_exc()
            self.error.emit(e)


class RetreatSearchPanel(QWidget):
    status_update = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._store = None
        self._vulnerability_result = None
        self._worker = None
        self._gdr_key_map = {v[0]: k for k, v in COMPACT_GDR_REGISTRY.items()}
        self._gdr_default_thresholds = {v[0]: v[1] for k, v in COMPACT_GDR_REGISTRY.items()}
        self._setup_ui()

    def set_store(self, store):
        self._store = store

    def set_vulnerability_result(self, result):
        self._vulnerability_result = result
        self._refresh_pool_combo()

    def _refresh_pool_combo(self):
        self.pool_combo.clear()
        if not self._vulnerability_result:
            return
        for pr in self._vulnerability_result.pool_results:
            if pr.vulnerability_intervals:
                self.pool_combo.addItem(pr.pool_id, pr.pool_id)

    def _on_pool_changed(self, index):
        pool_id = self.pool_combo.currentData()
        if not pool_id or not self._vulnerability_result:
            return
        for pr in self._vulnerability_result.pool_results:
            if pr.pool_id == pool_id:
                self._update_resource_presets(pr)
                self._update_pity_table(pr)
                break

    def _update_resource_presets(self, pr):
        for btn in [self.res_vi_lower, self.res_vi_mean, self.res_vi_upper]:
            btn.setEnabled(False)
        self.res_vi_lower.setText("VI下限 (--)")
        self.res_vi_mean.setText("VI均值 (--)")
        self.res_vi_upper.setText("VI上限 (--)")

        if pr.vulnerability_intervals:
            vi = pr.vulnerability_intervals[0]
            self.res_vi_lower.setText(f"VI下限 ({vi.lower:.0f})")
            self.res_vi_mean.setText(f"VI均值 ({vi.mean:.0f})")
            self.res_vi_upper.setText(f"VI上限 ({vi.upper:.0f})")
            self.res_vi_lower.setEnabled(True)
            self.res_vi_mean.setEnabled(True)
            self.res_vi_upper.setEnabled(True)
            self.res_vi_mean.setChecked(True)

    def _update_pity_table(self, pr):
        self.pity_table.setRowCount(0)
        if not pr.pity_stats_at_pool_end:
            return
        for i, (cname, snap) in enumerate(pr.pity_stats_at_pool_end.items()):
            self.pity_table.insertRow(i)
            self.pity_table.setItem(i, 0, QTableWidgetItem(cname))
            self.pity_table.setItem(i, 1, QTableWidgetItem(f"{snap.mean:.1f}"))
            self.pity_table.setItem(i, 2, QTableWidgetItem(f"{snap.median:.1f}"))
            self.pity_table.setItem(i, 3, QTableWidgetItem(f"{snap.p25:.1f}"))
            self.pity_table.setItem(i, 4, QTableWidgetItem(f"{snap.p75:.1f}"))

    def _get_selected_resource(self):
        if self.res_manual.isChecked():
            return float(self.res_manual_input.text() or '0')
        pool_id = self.pool_combo.currentData()
        if not pool_id or not self._vulnerability_result:
            return 0.0
        for pr in self._vulnerability_result.pool_results:
            if pr.pool_id == pool_id and pr.vulnerability_intervals:
                vi = pr.vulnerability_intervals[0]
                if self.res_vi_lower.isChecked():
                    return vi.lower
                elif self.res_vi_mean.isChecked():
                    return vi.mean
                elif self.res_vi_upper.isChecked():
                    return vi.upper
        return 0.0

    def _get_pity_init(self):
        pity_init = {}
        for i in range(self.pity_table.rowCount()):
            cname = self.pity_table.item(i, 0).text() if self.pity_table.item(i, 0) else ''
            val_text = self.pity_init_input.text() or '0'
            try:
                pity_init[cname] = int(float(val_text))
            except ValueError:
                pity_init[cname] = 0
        return pity_init

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        source_group = QGroupBox("起始状态（来自脆弱性分析）")
        source_form = QFormLayout(source_group)

        self.pool_combo = QComboBox()
        self.pool_combo.currentIndexChanged.connect(self._on_pool_changed)
        source_form.addRow("起始池:", self.pool_combo)

        res_group = QGroupBox("资源剩余值")
        res_layout = QVBoxLayout(res_group)
        self.res_btn_group = QButtonGroup(self)
        self.res_vi_lower = QRadioButton("VI下限 (--)")
        self.res_vi_mean = QRadioButton("VI均值 (--)")
        self.res_vi_upper = QRadioButton("VI上限 (--)")
        self.res_manual = QRadioButton("手动输入:")
        self.res_manual_input = QLineEdit("0")
        self.res_btn_group.addButton(self.res_vi_lower)
        self.res_btn_group.addButton(self.res_vi_mean)
        self.res_btn_group.addButton(self.res_vi_upper)
        self.res_btn_group.addButton(self.res_manual)
        res_layout.addWidget(self.res_vi_lower)
        res_layout.addWidget(self.res_vi_mean)
        res_layout.addWidget(self.res_vi_upper)
        manual_layout = QHBoxLayout()
        manual_layout.addWidget(self.res_manual)
        manual_layout.addWidget(self.res_manual_input)
        res_layout.addLayout(manual_layout)
        self.res_manual.setChecked(True)
        source_form.addRow(res_group)

        pity_group = QGroupBox("保底水位")
        pity_layout = QVBoxLayout(pity_group)
        self.pity_table = QTableWidget()
        self.pity_table.setColumnCount(5)
        self.pity_table.setHorizontalHeaderLabels(["计数器", "均值", "中位", "25%", "75%"])
        self.pity_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pity_table.verticalHeader().setVisible(False)
        self.pity_table.setMaximumHeight(100)
        pity_layout.addWidget(self.pity_table)
        pity_init_layout = QHBoxLayout()
        pity_init_layout.addWidget(QLabel("初始值:"))
        self.pity_init_input = QLineEdit("0")
        pity_init_layout.addWidget(self.pity_init_input)
        pity_layout.addLayout(pity_init_layout)
        source_form.addRow(pity_group)

        left_layout.addWidget(source_group)

        search_group = QGroupBox("搜索配置")
        search_form = QFormLayout(search_group)

        self.mode_resource = QRadioButton("最少额外资源")
        self.mode_target = QRadioButton("最多目标卡")
        self.mode_pareto = QRadioButton("Pareto前沿")
        self.mode_btn_group = QButtonGroup(self)
        self.mode_btn_group.addButton(self.mode_resource)
        self.mode_btn_group.addButton(self.mode_target)
        self.mode_btn_group.addButton(self.mode_pareto)
        self.mode_pareto.setChecked(True)
        mode_layout = QVBoxLayout()
        mode_layout.addWidget(self.mode_resource)
        mode_layout.addWidget(self.mode_target)
        mode_layout.addWidget(self.mode_pareto)
        search_form.addRow("搜索模式:", mode_layout)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.01, 1.0)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setValue(0.95)
        self.threshold_spin.setDecimals(2)
        search_form.addRow("成功率阈值:", self.threshold_spin)

        self.sim_spin = QSpinBox()
        self.sim_spin.setRange(50, 10000)
        self.sim_spin.setSingleStep(100)
        self.sim_spin.setValue(500)
        search_form.addRow("每步模拟次数:", self.sim_spin)

        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, 16)
        self.worker_spin.setValue(4)
        search_form.addRow("并行数:", self.worker_spin)

        self.gdr_combo = QComboBox()
        self.gdr_combo.addItems([v[0] for v in COMPACT_GDR_REGISTRY.values()])
        self.gdr_combo.setCurrentIndex(0)
        search_form.addRow("GDR指标:", self.gdr_combo)

        self.gdr_threshold_spin = QDoubleSpinBox()
        self.gdr_threshold_spin.setRange(0.0, 9999999.0)
        self.gdr_threshold_spin.setSingleStep(0.1)
        self.gdr_threshold_spin.setValue(1.0)
        self.gdr_threshold_spin.setDecimals(2)
        search_form.addRow("GDR阈值:", self.gdr_threshold_spin)

        left_layout.addWidget(search_group)

        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("开始搜索")
        self.run_btn.clicked.connect(self._on_run)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.run_btn)
        btn_layout.addWidget(self.stop_btn)
        left_layout.addLayout(btn_layout)

        self.progress_bar = QProgressBar()
        left_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("请先运行脆弱性分析")
        left_layout.addWidget(self.status_label)
        left_layout.addStretch()

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        result_group = QGroupBox("搜索结果")
        result_layout = QVBoxLayout(result_group)
        self.result_label = QLabel("尚未运行搜索")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("padding: 8px; background: #f5f5f5; border-radius: 4px;")
        result_layout.addWidget(self.result_label)
        right_layout.addWidget(result_group)

        detail_group = QGroupBox("详细结果")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_table = QTableWidget()
        self.detail_table.setColumnCount(4)
        self.detail_table.setHorizontalHeaderLabels(["额外资源", "目标卡集合", "成功率", "总资源"])
        header = self.detail_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.detail_table.verticalHeader().setVisible(False)
        detail_layout.addWidget(self.detail_table)
        right_layout.addWidget(detail_group)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([400, 600])

    def _on_run(self):
        if not self._store:
            self.status_update.emit("请先加载配置")
            return
        if not self._vulnerability_result:
            self.status_label.setText("请先在退路分析中运行脆弱性分析")
            return

        pool_id = self.pool_combo.currentData()
        if not pool_id:
            self.status_label.setText("请选择起始池")
            return

        target_specs = {}
        for tc in self._store.target_cards:
            target_specs[tc.card_id] = getattr(tc, 'quantity', 1)
        if not target_specs:
            self.status_label.setText("请先在配置中添加目标卡")
            return

        base_resource = self._get_selected_resource()
        pity_init = self._get_pity_init()

        if self.mode_resource.isChecked():
            mode = 'resource'
        elif self.mode_target.isChecked():
            mode = 'target'
        else:
            mode = 'pareto'

        gdr_name = self.gdr_combo.currentText()
        gdr_key = self._gdr_key_map.get(gdr_name, 'all_targets')

        from gacha_simulator.core.retreat_search import RetreatSearchEngine
        engine = RetreatSearchEngine(
            config_store=self._store,
            from_pool_id=pool_id,
            base_resource=base_resource,
            pity_counter_init=pity_init,
            success_threshold=self.threshold_spin.value(),
            gdr_key=gdr_key,
            gdr_threshold=self.gdr_threshold_spin.value(),
            num_simulations=self.sim_spin.value(),
            max_workers=self.worker_spin.value(),
        )

        self._worker = RetreatSearchWorker(engine, target_specs, mode)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self._worker.start()

    def _on_stop(self):
        if self._worker:
            self._worker.stop()

    def _on_progress(self, msg, pct):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)
        self.status_update.emit(msg)

    def _on_finished(self, result):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if result is None:
            self.status_label.setText("搜索已停止")
            return

        from gacha_simulator.core.retreat_search import RetreatSearchResult
        assert isinstance(result, RetreatSearchResult)

        lines = [f"<b>搜索模式:</b> {result.search_mode}"]
        lines.append(f"<b>起始池:</b> {result.from_pool_id}")
        lines.append(f"<b>基准资源:</b> {result.base_resource:.0f}")
        lines.append(f"<b>保底初始:</b> {result.pity_init}")
        lines.append(f"<b>结果点数:</b> {len(result.points)}")

        if result.points:
            best = result.points[-1]
            lines.append(f"<b>最优:</b> 额外+{best.extra_resource:.0f}资源, "
                         f"目标{best.target_specs}, P={best.success_probability:.2%}")

        self.result_label.setText('<br>'.join(lines))

        self.detail_table.setRowCount(len(result.points))
        for i, pt in enumerate(result.points):
            self.detail_table.setItem(i, 0, QTableWidgetItem(f"{pt.extra_resource:.0f}"))
            specs_str = ', '.join(f"{k}×{v}" for k, v in pt.target_specs.items())
            self.detail_table.setItem(i, 1, QTableWidgetItem(specs_str or "(无)"))
            self.detail_table.setItem(i, 2, QTableWidgetItem(f"{pt.success_probability:.2%}"))
            total = result.base_resource + pt.extra_resource
            self.detail_table.setItem(i, 3, QTableWidgetItem(f"{total:.0f}"))

        self.status_update.emit("退路方案搜索完成")

    def _on_error(self, err):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(f"错误: {err}")
        traceback.print_exc()
```

- [ ] **Step 2: 验证语法**

Run: `cd /workspace && python -c "import ast; ast.parse(open('gacha_simulator/gui/retreat_search_panel.py').read()); print('Syntax OK')"`

---

### Task 6: 集成到主窗口

**Files:**
- Modify: `gacha_simulator/gui/main_window.py:20,56-62,74-77,79-86,132-143`

- [ ] **Step 1: 添加 import 和面板实例化**

在 `main_window.py` 的 import 区域添加：

```python
from .retreat_search_panel import RetreatSearchPanel
```

在 `_setup_ui` 中，`self.retreat_panel = RetreatPanel()` 之后添加：

```python
self.retreat_search_panel = RetreatSearchPanel()
```

在 `set_store` 调用区域添加：

```python
self.retreat_search_panel.set_store(self._store)
```

在 `tabs.addTab` 区域，在退路分析 tab 之后添加：

```python
self.tabs.addTab(self.retreat_search_panel, "退路方案搜索")
```

- [ ] **Step 2: 连接脆弱性分析结果到退路方案搜索面板**

在 `_connect_signals` 中添加：

```python
self.retreat_panel.status_update.connect(self.status_bar.showMessage)
```

注意：退路分析面板已有 `status_update` 信号。需要让脆弱性分析完成后自动传递结果。在 `RetreatPanel._on_finished` 中添加结果传递。

修改 `gacha_simulator/gui/retreat_panel.py`，在 `RetreatPanel` 类中添加：

```python
vulnerability_finished = pyqtSignal(object)
```

在 `_on_finished` 方法末尾添加：

```python
self.vulnerability_finished.emit(result['analysis'])
```

在 `MainWindow._connect_signals` 中添加：

```python
self.retreat_panel.vulnerability_finished.connect(self.retreat_search_panel.set_vulnerability_result)
```

在 `_on_config_changed` 中添加：

```python
self.retreat_search_panel.set_store(self._store)
```

在 `_on_tab_changed` 中添加：

```python
elif widget is self.retreat_search_panel:
    self.retreat_search_panel.set_store(self._store)
```

- [ ] **Step 3: 验证编译**

Run: `cd /workspace && python -c "import ast; ast.parse(open('gacha_simulator/gui/main_window.py').read()); print('Syntax OK')"`

---

### Task 7: 全局验证

- [ ] **Step 1: 运行所有现有测试**

Run: `cd /workspace && python -m pytest tests/core/ -v`
Expected: All PASS

- [ ] **Step 2: 运行新测试**

Run: `cd /workspace && python -m pytest tests/core/test_retreat_config.py tests/core/test_retreat_search.py -v`
Expected: All PASS

- [ ] **Step 3: 验证导入链完整**

Run: `cd /workspace && python -c "from gacha_simulator.core.retreat_config import RetreatConfigBuilder; from gacha_simulator.core.retreat_search import RetreatSearchEngine; print('All imports OK')"`

- [ ] **Step 4: 验证 GUI 导入链**

Run: `cd /workspace && python -c "import ast; ast.parse(open('gacha_simulator/gui/retreat_search_panel.py').read()); ast.parse(open('gacha_simulator/gui/main_window.py').read()); print('GUI syntax OK')"`
