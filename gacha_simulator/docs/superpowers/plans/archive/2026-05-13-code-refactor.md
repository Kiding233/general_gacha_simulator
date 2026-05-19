# 代码重构：消除重复与统一接口

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 GUI 层三处模拟环境构建重复、两处 GDR 成功判定重复，清理废弃代码，统一接口。

**Architecture:** 提取 `SimulationEnvBuilder` 到 `batch_simulator.py` 统一构建模拟环境；提取 `compute_gdr_from_compact` 和 `compute_success_probability` 到 `core/gdr.py` 统一 GDR 计算；删除废弃的 `batch_service.py` 和 `forward_backward.py` 中的过时函数；迁移 `_build_pity_engine_from_gui` 到 `batch_simulator.py`。

**Tech Stack:** Python 3, PyQt6, multiprocessing

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `gui/batch_simulator.py` | 修改 | 新增 `SimulationEnvBuilder`、`SimulationEnv`；迁入 `_build_pity_engine_from_gui` |
| `gui/gacha_panel.py` | 修改 | 删除 `_build_pity_engine_from_gui`；`SimulationThread.run()` 改用 `SimulationEnvBuilder` |
| `gui/strategy_panel.py` | 修改 | `_build_simulation_env` 改用 `SimulationEnvBuilder`；GDR 判定改用 `compute_success_probability` |
| `gui/resource_search_panel.py` | 修改 | `_build_simulation_env` 改用 `SimulationEnvBuilder`；GDR 判定改用 `compute_success_probability` |
| `core/gdr.py` | 修改 | 新增 `compute_gdr_from_compact`、`compute_success_probability` |
| `core/forward_backward.py` | 修改 | 删除 `_compute_success_probability_from_histories`、`forward_method`、`backward_method` |
| `core/__init__.py` | 修改 | 移除已删除函数的导出 |
| `service/batch_service.py` | 删除 | 废弃未使用 |
| `service/__init__.py` | 修改 | 移除 batch_service 导出 |

---

### Task 1: 在 core/gdr.py 中新增 compact dict GDR 计算函数

**Files:**
- Modify: `gacha_simulator/core/gdr.py`

- [ ] **Step 1: 在 gdr.py 末尾新增 `compute_gdr_from_compact` 和 `compute_success_probability`**

在 `gdr.py` 末尾追加以下代码：

```python
def compute_gdr_from_compact(
    compact: Dict[str, Any],
    target_specs: Dict[str, int],
    gdr_key: str = 'target_achievement',
) -> float:
    card_counts = compact.get('card_counts', {})
    final_resources = compact.get('final_resources', {})
    total_draws = compact.get('total_draws', 0)
    total_consumed = compact.get('total_consumed', {})
    total_needed = sum(target_specs.values())

    if gdr_key == 'target_achievement':
        obtained = sum(card_counts.get(cid, 0) for cid in target_specs)
        return obtained / max(total_needed, 1) if total_needed > 0 else 0.0
    elif gdr_key == 'all_targets':
        obtained = sum(card_counts.get(cid, 0) for cid in target_specs)
        return 1.0 if obtained >= total_needed else 0.0
    elif gdr_key == 'ssr_collection':
        ssr_count = sum(v for k, v in card_counts.items() if 'ssr' in k.lower())
        return ssr_count / max(total_draws, 1)
    elif gdr_key == 'resource_remaining':
        return final_resources.get('draw_resource', 0)
    elif gdr_key == 'extra_target':
        obtained = sum(card_counts.get(cid, 0) for cid in target_specs)
        return float(max(obtained - total_needed, 0))
    elif gdr_key == 'resource_efficiency':
        obtained = sum(card_counts.get(cid, 0) for cid in target_specs)
        consumed_r = total_consumed.get('draw_resource', 0)
        draws_used = consumed_r / 160 if consumed_r > 0 else 1
        return obtained / max(draws_used, 1)
    else:
        obtained = sum(card_counts.get(cid, 0) for cid in target_specs)
        return obtained / max(total_needed, 1) if total_needed > 0 else 0.0


def compute_success_probability(
    histories: List[Optional[Dict[str, Any]]],
    target_specs: Dict[str, int],
    gdr_key: str = 'target_achievement',
    gdr_threshold: float = 1.0,
) -> float:
    valid = [h for h in histories if h is not None]
    if not valid:
        return 0.0
    total_needed = sum(target_specs.values())
    if total_needed == 0 and gdr_key == 'target_achievement':
        return 1.0
    success_count = 0
    for h in valid:
        val = compute_gdr_from_compact(h, target_specs, gdr_key)
        if val >= gdr_threshold:
            success_count += 1
    return success_count / len(valid)
```

- [ ] **Step 2: 在 `core/__init__.py` 中导出新函数**

在 `core/__init__.py` 的 gdr 导入行添加 `compute_gdr_from_compact, compute_success_probability`，在 `__all__` 中也添加。

---

### Task 2: 在 batch_simulator.py 中新增 SimulationEnv 和 SimulationEnvBuilder

**Files:**
- Modify: `gacha_simulator/gui/batch_simulator.py`

- [ ] **Step 1: 在 batch_simulator.py 顶部（import 之后）新增 SimulationEnv dataclass**

```python
from dataclasses import dataclass, field as dc_field
from typing import List, Dict, Set, Optional, Any

@dataclass
class SimulationEnv:
    pools: list
    schedule_mgr: Any
    end_time: float
    pity_engine: Any
    resource_gain: Any
    pity_state_init: Optional[dict]
    card_defs: list
    initial_resources: Dict[str, float]
    target_ids: Set[str] = dc_field(default_factory=set)
    ssr_ids: Set[str] = dc_field(default_factory=set)
    all_drawable_ids: List[str] = dc_field(default_factory=list)
    pool_end_times: Dict[str, float] = dc_field(default_factory=dict)
    gdr_context: Any = None
    daily_income: float = 0.0
```

- [ ] **Step 2: 将 `_build_pity_engine_from_gui` 从 gacha_panel.py 复制到 batch_simulator.py**

将 gacha_panel.py 中 `_build_pity_engine_from_gui` 函数的完整代码复制到 batch_simulator.py 中 `SimulationEnv` 定义之后。函数签名和实现保持不变。

- [ ] **Step 3: 在 batch_simulator.py 中新增 `SimulationEnvBuilder` 类**

```python
class SimulationEnvBuilder:
    @staticmethod
    def from_config_store(config_store) -> SimulationEnv:
        from gacha_simulator.core.pool import Pool, Reward, parse_cost_string
        from gacha_simulator.core.schedule import PoolScheduleManager, PoolSchedule
        from gacha_simulator.core.resource_gain import (
            PeriodicResourceGain, ScheduleResourceGain, CompositeResourceGain,
        )

        DAY = 86400
        pool_entries = config_store.pools
        schedules = []
        pools = []
        pool_featured_map = {}
        pool_ssr_map = {}

        for pe in pool_entries:
            pid = pe.pool_id
            start_day = pe.start_day or 0
            end_day = pe.end_day if pe.end_day > start_day else (start_day + 21)

            rewards = []
            featured_ids = set()
            ssr_ids = set()
            for de in getattr(pe, 'distribution', []):
                rg = dict(getattr(de, 'resources_gained', {}) or {})
                rwd = Reward(id=de.card_id, name=getattr(de, 'card_id', ''), resources_gained=rg)
                rewards.append((rwd, de.probability / 100.0))
                if de.featured and de.card_id != '_no_card':
                    featured_ids.add(de.card_id)
                if de.rarity.upper() == 'SSR' and de.card_id != '_no_card':
                    ssr_ids.add(de.card_id)

            if not ssr_ids:
                _fallback_ssr_id = f"{pid}_ssr"
                ssr_ids = {_fallback_ssr_id}
                if not rewards:
                    rewards.append((Reward(id=_fallback_ssr_id, name='', resources_gained={}), 0.006))
            if not featured_ids:
                featured_ids = set(ssr_ids)

            pool_featured_map[pid] = featured_ids
            pool_ssr_map[pid] = ssr_ids

            cost_str = getattr(pe, 'cost', 'draw_resource:160')
            parsed_cost = parse_cost_string(cost_str) if cost_str else [{'draw_resource': 160}]
            exchange_cid = getattr(pe, 'exchange_card_id', None)
            pool = Pool(
                id=pid,
                name=getattr(pe, 'name', pid),
                cost=parsed_cost,
                rewards=rewards,
                available_from=start_day * DAY,
                available_until=end_day * DAY,
                is_exchange=bool(exchange_cid),
                exchange_card_id=exchange_cid,
            )
            pools.append(pool)
            schedules.append(PoolSchedule(
                pool_id=pid,
                available_from=start_day * DAY,
                available_until=end_day * DAY,
            ))

        schedule_mgr = PoolScheduleManager(schedules)
        end_time = max(s.available_until for s in schedules) if schedules else 0

        pity_cfg_dict = {'enabled': True, 'pities': []}
        pc = config_store.pity
        if pc and hasattr(pc, 'pities'):
            pity_cfg_dict['enabled'] = getattr(pc, 'enabled', True)
            for pd in pc.pities:
                pentry = {
                    'name': pd.name,
                    'type': getattr(pd, 'btype', 'soft'),
                    'params': dict(getattr(pd, 'params', {}) or {}),
                    'target_distribution': dict(getattr(pd, 'target_distribution', {}) or {}),
                    'reset': getattr(pd, 'reset_condition', 'any_ssr'),
                    'pools': getattr(pd, 'pools', '*'),
                }
                pity_cfg_dict['pities'].append(pentry)

        if hasattr(pc, 'counter_init') and pc.counter_init:
            pity_cfg_dict['counter_init'] = dict(pc.counter_init)

        pity_engine = _build_pity_engine_from_gui(
            pity_cfg_dict, pools, pool_featured_map, pool_ssr_map, {})

        initial_resources = {}
        ir_raw = config_store.initial_resources
        if isinstance(ir_raw, dict):
            initial_resources = dict(ir_raw)
        elif isinstance(ir_raw, list):
            for ir in ir_raw:
                rid = getattr(ir, 'resource_id', 'draw_resource')
                amt = getattr(ir, 'amount', 0)
                if amt > 0:
                    initial_resources[rid] = initial_resources.get(rid, 0) + float(amt)

        resource_gain = SimulationEnvBuilder._build_resource_gain(config_store, end_time)

        counter_init_cfg = pity_cfg_dict.get('counter_init', 0)
        pity_state_init = None
        init_counters = {}
        if isinstance(counter_init_cfg, int) and counter_init_cfg > 0 and pity_engine:
            for cname in pity_engine.pity_defs:
                init_counters[cname] = counter_init_cfg
        elif isinstance(counter_init_cfg, dict) and pity_engine:
            for k, v in counter_init_cfg.items():
                if v > 0 and k in pity_engine.pity_defs:
                    init_counters[k] = v
        if init_counters:
            pity_state_init = {'counters': init_counters}

        card_defs = []
        for cd in config_store.card_defs:
            card_defs.append({
                'card_id': cd.card_id,
                'name': getattr(cd, 'name', ''),
                'rarity': getattr(cd, 'rarity', 'r'),
                'pools': list(getattr(cd, 'pools', [])),
            })

        target_ids = set()
        for tc in getattr(config_store, 'target_cards', []):
            target_ids.add(tc.card_id)

        ssr_ids = set()
        for cd in config_store.card_defs:
            if getattr(cd, 'rarity', '').upper() == 'SSR':
                ssr_ids.add(cd.card_id)
        if not ssr_ids:
            for pid, ssr_set in pool_ssr_map.items():
                ssr_ids.update(ssr_set)

        all_drawable_ids = [r.id for p in pools for r, _ in p.rewards]
        pool_end_times = {s.pool_id: s.available_until for s in schedules}

        from gacha_simulator.core.gdr import GDRContext
        target_specs = {tc.card_id: getattr(tc, 'quantity', 1) for tc in getattr(config_store, 'target_cards', [])}
        gdr_context = GDRContext(
            target_specs=target_specs,
            ssr_ids=ssr_ids,
            all_drawable_ids=all_drawable_ids,
            initial_resources=dict(initial_resources),
            resource_gain_per_day={'draw_resource': 0},
        )

        return SimulationEnv(
            pools=pools,
            schedule_mgr=schedule_mgr,
            end_time=end_time,
            pity_engine=pity_engine,
            resource_gain=resource_gain,
            pity_state_init=pity_state_init,
            card_defs=card_defs,
            initial_resources=initial_resources,
            target_ids=target_ids,
            ssr_ids=ssr_ids,
            all_drawable_ids=all_drawable_ids,
            pool_end_times=pool_end_times,
            gdr_context=gdr_context,
        )

    @staticmethod
    def _build_resource_gain(config_store, end_time):
        from gacha_simulator.core.resource_gain import (
            PeriodicResourceGain, ScheduleResourceGain, CompositeResourceGain,
        )
        gain_functions = []
        schedule = {}
        total_days = int(end_time / 86400) + 1 if end_time else 30

        for rule in getattr(config_store, 'gain_rules', []):
            rule_type = getattr(rule, 'rule_type', 'every_n_days')
            param = getattr(rule, 'param', '1')
            gains = getattr(rule, 'gains', {}) or {}
            for rid, amount in gains.items():
                amount = float(amount)
                if amount <= 0:
                    continue
                if rule_type == 'every_n_days':
                    n = int(param) if param else 1
                    for day in range(0, total_days, n):
                        if day not in schedule:
                            schedule[day] = {}
                        schedule[day][rid] = schedule[day].get(rid, 0) + amount
                elif rule_type == 'weekly':
                    import datetime
                    target_wday = int(param) if param else 1
                    for day in range(total_days):
                        try:
                            d = datetime.date.fromordinal(day + 735000)
                            if d.isoweekday() == target_wday:
                                if day not in schedule:
                                    schedule[day] = {}
                                schedule[day][rid] = schedule[day].get(rid, 0) + amount
                        except Exception:
                            pass

        for override in getattr(config_store, 'day_overrides', []):
            day = getattr(override, 'day', 0)
            gains = getattr(override, 'gains', {}) or {}
            for rid, amount in gains.items():
                amount = float(amount)
                if amount > 0 and 0 <= day < total_days:
                    if day not in schedule:
                        schedule[day] = {}
                    schedule[day][rid] = schedule[day].get(rid, 0) + amount

        if schedule:
            gain_functions.append(ScheduleResourceGain(schedule, total_days))

        if gain_functions:
            if len(gain_functions) == 1:
                return gain_functions[0]
            return CompositeResourceGain(gain_functions)
        return None
```

---

### Task 3: 改造 strategy_panel.py 使用 SimulationEnvBuilder + compute_success_probability

**Files:**
- Modify: `gacha_simulator/gui/strategy_panel.py`

- [ ] **Step 1: 删除 `_build_simulation_env` 方法，替换为使用 `SimulationEnvBuilder`**

将 `StrategyWorker._build_simulation_env` 整个方法体替换为：

```python
    def _build_simulation_env(self):
        from .batch_simulator import SimulationEnvBuilder
        env = SimulationEnvBuilder.from_config_store(self.config_store)
        self._sim_env = {
            'pools': env.pools,
            'schedule_mgr': env.schedule_mgr,
            'end_time': env.end_time,
            'pity_engine': env.pity_engine,
            'resource_gain': env.resource_gain,
            'pity_state_init': env.pity_state_init,
            'card_defs': env.card_defs,
            'initial_resources': env.initial_resources,
        }
```

- [ ] **Step 2: 删除 `_build_resource_gain` 方法**（已由 SimulationEnvBuilder 接管）

- [ ] **Step 3: 删除 `_compute_success_probability_from_histories` 方法，替换为使用 `compute_success_probability`**

将 `_forward_method` 和 `_backward_method` 中所有 `self._compute_success_probability_from_histories(histories, ...)` 调用替换为：

```python
from gacha_simulator.core.gdr import compute_success_probability
prob = compute_success_probability(histories, current_specs, self.gdr_key, self.gdr_threshold)
```

三处替换点：
- `_forward_method` 中 `prob = self._compute_success_probability_from_histories(...)`
- `_backward_method` 中 `initial_prob = self._compute_success_probability_from_histories(...)`
- `_backward_method` 中 `temp_prob = self._compute_success_probability_from_histories(...)`

---

### Task 4: 改造 resource_search_panel.py 使用 SimulationEnvBuilder + compute_success_probability

**Files:**
- Modify: `gacha_simulator/gui/resource_search_panel.py`

- [ ] **Step 1: 删除 `_rs_compute_success_prob` 函数**

- [ ] **Step 2: 删除 `_build_simulation_env` 方法，替换为使用 `SimulationEnvBuilder`**

将 `ResourceSearchWorker._build_simulation_env` 整个方法体替换为：

```python
    def _build_simulation_env(self):
        from .batch_simulator import SimulationEnvBuilder
        env = SimulationEnvBuilder.from_config_store(self.config_store)
        self._sim_env = {
            'pools': env.pools,
            'schedule_mgr': env.schedule_mgr,
            'end_time': env.end_time,
            'pity_engine': env.pity_engine,
            'resource_gain': env.resource_gain,
            'pity_state_init': env.pity_state_init,
            'card_defs': env.card_defs,
            'initial_resources': env.initial_resources,
        }
        self._cost_per_draw = self._extract_cost_per_draw(env.pools)
        self._initial_resources_backup = dict(env.initial_resources)
```

- [ ] **Step 3: 删除 `_build_resource_gain` 方法**

- [ ] **Step 4: 修改 `_simulate_with_resource` 使用 `compute_success_probability`**

将 `_simulate_with_resource` 中的 `return _rs_compute_success_prob(...)` 替换为：

```python
        from gacha_simulator.core.gdr import compute_success_probability
        return compute_success_probability(histories, self.target_specs, self.gdr_key, self.gdr_threshold)
```

---

### Task 5: 改造 gacha_panel.py 使用 SimulationEnvBuilder

**Files:**
- Modify: `gacha_simulator/gui/gacha_panel.py`

- [ ] **Step 1: 删除 `_build_pity_engine_from_gui` 函数**（已迁移到 batch_simulator.py）

- [ ] **Step 2: 修改 `SimulationThread.run()` 中的环境构建部分**

将 `SimulationThread.run()` 中从 `pools = []` 到 `resource_gain = CompositeResourceGain(gain_functions)` 的全部环境构建代码（约 200 行），替换为：

```python
            from .batch_simulator import SimulationEnvBuilder

            env = SimulationEnvBuilder.from_config_store(
                self._build_config_store()
            )

            target_ids = env.target_ids
            ssr_ids = env.ssr_ids
            self._target_ids = target_ids
            self._ssr_ids = ssr_ids
            self._pool_end_times = env.pool_end_times
            self._gdr_context = env.gdr_context
```

- [ ] **Step 3: 在 SimulationThread 中新增 `_build_config_store` 方法**

将 gacha_panel 的 dict config 转换为 ConfigStore 对象，供 SimulationEnvBuilder 使用。这个方法需要将 `self.config` dict 转换为 ConfigStore dataclass：

```python
    def _build_config_store(self):
        from gacha_simulator.core.config_store import ConfigStore, PoolEntry, PityConfig, PityDef, DistributionEntry, CardDef, TargetCardDef
        config = self.config
        pools = []
        for p in config.get('pools', []):
            distribution = []
            for item in p.get('distribution', []):
                rg_text = item.get('resources_gained', '')
                rg = {}
                if rg_text and isinstance(rg_text, str):
                    for part in rg_text.split(','):
                        part = part.strip()
                        if ':' in part:
                            rk, rv = part.split(':', 1)
                            rg[rk.strip()] = float(rv.strip())
                elif isinstance(rg_text, dict):
                    rg = rg_text
                distribution.append(DistributionEntry(
                    card_id=item['card_id'],
                    probability=item.get('probability', 0),
                    featured=item.get('featured', False),
                    rarity=item.get('rarity', 'R'),
                    resources_gained=rg,
                ))
            pools.append(PoolEntry(
                pool_id=p['id'],
                name=p.get('name', p['id']),
                start_day=p.get('start_day', 0),
                end_day=p.get('start_day', 0) + p.get('duration', 21),
                cost=p.get('cost', 'draw_resource:160'),
                distribution=distribution,
                exchange_card_id=p.get('exchange_card_id'),
            ))

        pity_cfg = config.get('pity', {})
        pities = []
        for pd in pity_cfg.get('pities', []):
            pities.append(PityDef(
                name=pd.get('name', 'pity'),
                btype=pd.get('type', 'soft'),
                params=pd.get('params', {}),
                target_distribution=pd.get('target_distribution', {}),
                reset_condition=pd.get('reset', 'any_ssr'),
                pools=pd.get('pools', '*'),
            ))
        pity = PityConfig(
            enabled=pity_cfg.get('enabled', True),
            pities=pities,
            counter_init=pity_cfg.get('counter_init', 0),
        )

        card_defs = []
        for cd in config.get('card_defs', []):
            card_defs.append(CardDef(
                card_id=cd['card_id'],
                name=cd.get('name', ''),
                rarity=cd.get('rarity', 'R'),
                pools=cd.get('pools', []),
            ))

        target_cards = []
        for tc in config.get('target_cards', []):
            target_cards.append(TargetCardDef(
                card_id=tc['card_id'],
                quantity=tc.get('quantity', 1),
            ))

        initial_resources = config.get('initial_resources', [])

        return ConfigStore(
            pools=pools,
            pity=pity,
            card_defs=card_defs,
            target_cards=target_cards,
            initial_resources=initial_resources,
        )
```

- [ ] **Step 4: 修改 `run_batch_parallel` 调用部分**

将 `run_batch_parallel` 调用改为使用 env 的属性：

```python
            from .batch_simulator import run_batch_parallel

            target_specs = {tc.card_id: tc.quantity for tc in self._build_config_store().target_cards}
            card_defs_list = env.card_defs

            results = run_batch_parallel(
                pools=env.pools,
                schedule_mgr=env.schedule_mgr,
                end_time=env.end_time,
                pity_engine=env.pity_engine,
                resource_gain=env.resource_gain,
                pity_state_init=env.pity_state_init,
                card_defs=card_defs_list,
                target_specs=target_specs,
                initial_resources=env.initial_resources,
                num_simulations=N,
                max_workers=max_workers,
                seed=seed,
                progress_callback=lambda done, total: self.progress.emit(done, total),
            )
```

---

### Task 6: 清理 forward_backward.py

**Files:**
- Modify: `gacha_simulator/core/forward_backward.py`
- Modify: `gacha_simulator/core/__init__.py`

- [ ] **Step 1: 删除 `_compute_success_probability_from_histories` 函数**

- [ ] **Step 2: 删除 `forward_method` 和 `backward_method` 函数**（strategy_panel 已用自己的实现，这两个函数从未被调用）

- [ ] **Step 3: 更新 `core/__init__.py`**

从导入和 `__all__` 中移除 `forward_method, backward_method`。保留 `ForwardStep, BackwardStep, ForwardResult, BackwardResult` 的导出。

---

### Task 7: 删除 batch_service.py

**Files:**
- Delete: `gacha_simulator/service/batch_service.py`
- Modify: `gacha_simulator/service/__init__.py`

- [ ] **Step 1: 删除 `service/batch_service.py`**

- [ ] **Step 2: 修改 `service/__init__.py`**

移除 `from .batch_service import BatchService, BatchConfig, SimulationVariant, ConditionGenerator` 和对应的 `__all__` 条目。

---

### Task 8: 更新 gacha_panel.py 中对 _build_pity_engine_from_gui 的引用

**Files:**
- Modify: `gacha_simulator/gui/gacha_panel.py`

- [ ] **Step 1: 确认 gacha_panel.py 不再引用 `_build_pity_engine_from_gui`**

如果 Task 5 已正确完成，gacha_panel.py 中不应再有对 `_build_pity_engine_from_gui` 的引用。搜索确认。

- [ ] **Step 2: 更新 strategy_panel.py 和 resource_search_panel.py 中的导入**

将 `from gacha_simulator.gui.gacha_panel import _build_pity_engine_from_gui` 替换为 `from .batch_simulator import _build_pity_engine_from_gui`。

但实际上 Task 3/4 已经删除了 `_build_simulation_env` 中的直接调用，所以这些导入应该已经不存在了。搜索确认。

---

### Task 9: 验证所有修改

- [ ] **Step 1: 编译检查所有修改过的文件**

```bash
cd /workspace && python -m py_compile gacha_simulator/gui/batch_simulator.py && \
python -m py_compile gacha_simulator/gui/gacha_panel.py && \
python -m py_compile gacha_simulator/gui/strategy_panel.py && \
python -m py_compile gacha_simulator/gui/resource_search_panel.py && \
python -m py_compile gacha_simulator/core/gdr.py && \
python -m py_compile gacha_simulator/core/forward_backward.py && \
python -m py_compile gacha_simulator/core/__init__.py && \
python -m py_compile gacha_simulator/service/__init__.py && \
echo "ALL OK"
```

- [ ] **Step 2: 搜索残留引用**

```bash
cd /workspace && grep -rn "_build_pity_engine_from_gui" gacha_simulator/ && \
grep -rn "_rs_compute_success_prob" gacha_simulator/ && \
grep -rn "_compute_success_probability_from_histories" gacha_simulator/ && \
grep -rn "batch_service" gacha_simulator/
```

确认：
- `_build_pity_engine_from_gui` 只存在于 `batch_simulator.py`
- `_rs_compute_success_prob` 不存在
- `_compute_success_probability_from_histories` 不存在
- `batch_service` 不存在

- [ ] **Step 3: 搜索 forward_method/backward_method 残留**

```bash
cd /workspace && grep -rn "forward_method\|backward_method" gacha_simulator/core/
```

确认只在 `__init__.py` 的注释或已删除位置出现。
