# 策略代码调查与重构方案报告

> 调查日期：2026-05-20（第二次更新版）
> 基于代码版本：v1.8.0
> 变更说明：PR 提交后代码已发生变化，主要涉及最差后期影响分析（worst_impact.py）和模拟服务层（gacha_service.py）。本次重新调查已反映所有变更。

---

## 一、现状全景图

### 1.1 策略代码的分布位置

策略代码分散在 **6 个模块**中，形成了两套并行的策略体系：

```
gacha_simulator/
├── core/
│   ├── strategy.py          ← 基类 + 通用策略（导出）
│   ├── worst_impact.py      ← 专用 _DrawTargetStrategy + _TargetPoolEnd（已变更）
│   ├── streaming.py         ← 流式分析器（新增 pool_end_pity_states 提取）
│   └── vulnerability.py     ← 脆弱性分析（使用 pool_end_pity_states）
│
├── gui/
│   ├── batch_simulator.py   ← STRATEGY_REGISTRY + 4个具体实现（主战场）
│   ├── config_panel.py      ← 策略UI配置（硬编码下拉框）
│   ├── strategy_panel.py    ← 前进/后退法分析（硬编码 smart）
│   ├── gacha_panel.py       ← 批量模拟（硬编码 smart）
│   ├── resource_search_panel.py ← 资源搜索（硬编码 smart）
│   └── retreat_panel.py     ← 退路分析（无策略选择）
│
└── service/
    └── gacha_service.py     ← 策略执行引擎（已变更：新增 pool_end_pity_states）
```

### 1.2 两套策略体系对比

| 维度 | 体系 A：`core/strategy.py` | 体系 B：`gui/batch_simulator.py` |
|------|--------------------------|--------------------------------|
| **定位** | 被 `GachaService` 直接使用 | 被 `run_batch_parallel` 批量模拟使用 |
| **基类** | ✅ 有 `Strategy` 抽象基类 | ❌ 无基类，只有4个独立类 |
| **注册表** | ❌ 无注册表 | ✅ 有 `STRATEGY_REGISTRY` |
| **工厂函数** | ❌ 无 | ✅ 有 4 个 `_create_*` 函数 |
| **可配置参数** | ❌ 无参数机制 | ✅ 通过 `strategy_params` 传递 |
| **实例方法** | `select_action` | `select_action` + `observe` |
| **静态属性** | ❌ 无 | `lookahead = None` |

---

## 二、详细代码分析

### 2.1 `core/strategy.py` — 策略基类体系

**文件位置**：[core/strategy.py](file:///workspace/gacha_simulator/gacha_simulator/core/strategy.py)

#### 抽象基类 `Strategy`

```python
class Strategy(ABC):
    lookahead: Optional[float] = None

    @abstractmethod
    def select_action(
        self,
        state: 'GachaState',
        history: List['InfoVector'],
        current_pools: List['Pool'],
        future_schedules: List[PoolSchedule],
        target_cards: TargetCardSet,
        stop_condition: 'StopCondition',
    ) -> Action:
        pass
```

**输入参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| `state` | `GachaState` | 当前资源/时间状态 |
| `history` | `List[InfoVector]` | 已执行的抽卡记录 |
| `current_pools` | `List[Pool]` | 当前可用的池子列表 |
| `future_schedules` | `List[PoolSchedule]` | 未来计划 |
| `target_cards` | `TargetCardSet` | 目标卡集合 |
| `stop_condition` | `StopCondition` | 停止条件 |

**输出**：`Action`（`DrawAction` 或 `WaitAction`）

**导出情况**：
- [core/__init__.py](file:///workspace/gacha_simulator/gacha_simulator/core/__init__.py#L63) 导出了 `Strategy, FixedCountStrategy, TargetHuntingStrategy, CompositeStrategy`
- [service/gacha_service.py](file:///workspace/gacha_simulator/gacha_simulator/service/gacha_service.py#L6) 接收 `Strategy` 类型的 `strategy` 参数

#### 4 个具体策略（core/strategy.py）

| 策略类 | 行为 | 构造函数参数 |
|--------|------|------------|
| `FixedCountStrategy` | 抽指定次数后停止 | `count: int` |
| `TargetHuntingStrategy` | 只从指定池抽卡 | `target_pool_ids: List[str]` |
| `CompositeStrategy` | 组合多个策略 | `strategies: List[Strategy], mode: str` |

**特点**：
- `FixedCountStrategy` 和 `TargetHuntingStrategy` **没有 `observe()` 方法**
- `CompositeStrategy` 的 `observe()` 也没有实现

---

### 2.2 `gui/batch_simulator.py` — 策略注册表体系

**文件位置**：[batch_simulator.py](file:///workspace/gacha_simulator/gacha_simulator/gui/batch_simulator.py)

#### `STRATEGY_REGISTRY` 注册表

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
        'params': {'pool_quotas': {...}},
    },
    'pity_reserve': {
        'display_name': '保底预留',
        'description': '只在大保底概率≥阈值时才抽卡',
        'factory': _create_pity_reserve_strategy,
        'params': {'pity_threshold_pct': {...}},
    },
    'stop_on_target': {
        'display_name': '目标即停',
        'description': '抽到当期up/目标卡就停止',
        'factory': _create_stop_on_target_strategy,
        'params': {'stop_on_featured': {...}, 'stop_on_any_target': {...}},
    },
}
```

**注册表机制**：
- `factory` 函数签名：`(target_set, params) -> Strategy`
- `params` 定义了每个参数的类型、显示名、默认值、范围
- `run_batch_parallel` 通过 `strategy_name` + `strategy_params` 动态选择策略

#### 4 个策略实现类

**1. `_SmartStrategy`**（最复杂）
- 优先兑换 → 按目标追卡 → 等待下一个池
- 有 `acquired` 字典跟踪已获得卡牌
- 有 `_pool_to_targets` 映射

**2. `_PoolQuotaStrategy`**
- 支持 `pool_quotas: Dict[str, int]` 参数
- 跟踪 `pool_draw_counts` 计数

**3. `_PityReserveStrategy`**
- 支持 `pity_threshold_pct` 参数
- 实时计算 SSR 概率，与阈值比较
- 依赖 `_wk_pity_engine`、`_wk_pity_state_init` 全局变量

**4. `_StopOnTargetStrategy`**
- 支持 `stop_on_featured` + `stop_on_any_target` 参数
- 有 `_stopped` 标志位

**共同特点**：
- 都有 `lookahead = None` 静态属性
- 都有 `observe()` 方法（`GachaService` 通过 `hasattr` 调用）
- 都在 `_wk_run_single` 中通过注册表工厂创建
- 都需要访问 `_wk_pools` 全局变量

---

### 2.3 `worst_impact.py` — 专用策略与停止条件（已变更）

**文件位置**：[core/worst_impact.py](file:///workspace/gacha_simulator/gacha_simulator/core/worst_impact.py)

#### 🆕 变更：`_TargetPoolEnd` 停止条件

```python
class _TargetPoolEnd(StopCondition):
    def __init__(self, end_time: float):
        self.end_time = end_time

    def check(self, state, history, stats=None):
        return state.real_time >= self.end_time

    def description(self):
        return ""
```

**关键变更**：`_TargetPoolEnd` 现在继承了 `core/stop_condition.py` 的 `StopCondition` 基类，而不再是一个独立的无基类类。`check` 方法签名增加了 `stats=None` 参数。

#### 🆕 变更：`_DrawTargetStrategy` 策略

```python
class _DrawTargetStrategy(Strategy):
    lookahead = None

    def __init__(self, target_card_ids: Set[str], pool_id: str):
        self.target_card_ids = target_card_ids
        self.pool_id = pool_id
        self.acquired: Dict[str, int] = {}

    @classmethod
    def description(cls) -> str:
        return "最差影响分析：从目标池抽卡"

    def select_action(self, state, history, current_pools,
                      future_schedules, target_cards, stop_cond):
        for pool in current_pools:
            if pool.id == self.pool_id and state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)
        wait_time = 86400
        for pool in current_pools:
            if (pool.available_until is not None
                    and pool.available_until > state.real_time):
                wait_time = min(wait_time, pool.available_until - state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)

    def observe(self, iv):
        if iv.action_type == 'draw' and iv.card_id:
            self.acquired[iv.card_id] = self.acquired.get(iv.card_id, 0) + 1
```

**特点**：
- **继承了 `core/strategy.py` 的 `Strategy` 基类**（注册表中的4个策略都没有继承）
- 在链式模拟中直接创建，不经过注册表
- 有 `observe()` 方法
- 只从一个指定池抽卡
- 🆕 新增 `description()` 类方法

#### 🆕 变更：`WorstImpactAnalyzer` 构造函数

```python
class WorstImpactAnalyzer:
    def __init__(self, simulation_results, target_specs, store,
                 gdr_key='all_targets', gdr_threshold=1.0,
                 custom_pool_config=None,
                 desire_weights=None, miss_cost_weights=None,
                 card_value_weights=None):
```

**新增参数**：
- `desire_weights`：加权满意度 GDR 的 desire 权重
- `miss_cost_weights`：加权满意度 GDR 的 miss_cost 权重
- `card_value_weights`：总出卡价值 GDR 的 card_value 权重

这些权重从 `main_window.config_panel` 获取，传递给 `SuccessChecker`。

#### 🆕 变更：`_build_success_checker` 方法

```python
def _build_success_checker(self):
    from .gdr import SuccessChecker
    self._checker = SuccessChecker(
        target_specs=self.target_specs,
        gdr_key=self.gdr_key,
        gdr_threshold=self.gdr_threshold,
        desire_weights=self.desire_weights,
        miss_cost_weights=self.miss_cost_weights,
        card_value_weights=self.card_value_weights,
        ssr_ids=self._ssr_ids,
    )
    return self._checker.is_success
```

现在使用 `SuccessChecker` 类（来自 `core/gdr.py`），而非直接调用 `compute_gdr_from_compact`。`SuccessChecker` 是一个统一的成功判定器，支持所有 GDR 指标。

#### 🆕 变更：保底状态传递机制

`_run_single_simulation` 方法现在从 compact dict 的 `pool_end_pity_states` 字段提取保底状态：

```python
def _run_single_simulation(self, pool, resource, pity_state,
                            target_set, strategy, stop_cond):
    ...
    result = service.run_simulation_compact(state)

    final_pity_state = dict(pity_state)
    pool_end_pity = result.get('pool_end_pity_states', {})
    if pool_end_pity:
        if pool.id in pool_end_pity:
            final_pity_state = pool_end_pity_states[pool.id].get('counters', {})
        else:
            last_key = list(pool_end_pity.keys())[-1]
            final_pity_state = pool_end_pity[last_key].get('counters', {})
    ...
```

**意义**：链式模拟中，每个新池子能正确继承前一个池子结束时的保底计数器状态，而非从零开始。

#### 🆕 变更：`_compute_pool_distribution` 链式模拟

```python
def _compute_pool_distribution(self, resource, pity_state,
                                num_simulations, progress_callback=None):
    success_counts = defaultdict(int)
    ...
    for sim_idx in range(num_simulations):
        current_resource = resource
        current_pity = dict(pity_state)
        consecutive = 0
        pool_index = 0

        while current_resource > 0 and pool_index < max_pools:
            pool = self._create_new_pool(pool_index)
            target_set = self._build_target_card_set(pool.id)
            strategy = _DrawTargetStrategy(self._featured_ids, pool.id)
            stop_cond = _TargetPoolEnd(pool.available_until)

            result = self._run_single_simulation(
                pool, current_resource, current_pity,
                target_set, strategy, stop_cond
            )
            if result['success']:
                consecutive += 1
                current_resource = result['remaining_resource']
                current_pity = result['final_pity_state']  # 🆕 传递保底状态
                pool_index += 1
            else:
                break

        success_counts[consecutive] += 1
```

---

### 2.4 `gacha_service.py` — 策略执行引擎（已变更）

**文件位置**：[service/gacha_service.py](file:///workspace/gacha_simulator/gacha_simulator/service/gacha_service.py)

#### 🆕 变更：`run_simulation_compact` 新增 `pool_end_pity_states` 输出

compact dict 输出现在包含 `pool_end_pity_states` 字段：

```python
return {
    'draw_card_ids': draw_card_ids,
    'draw_pool_ids': draw_pool_ids,
    ...
    'pool_end_resources': pool_end_resources,
    'pool_end_pity_states': pool_end_pity_states,  # 🆕
}
```

**实现机制**：

```python
pool_end_pity_states = {}
pool_end_times_sorted = sorted(
    [(p.id, p.available_until) for p in pools_list if p.available_until],
    key=lambda x: x[1]
)
recorded_pool_ends = set()

# 在 WaitAction 和循环结束后记录
for pid, pet in pool_end_times_sorted:
    if pid not in recorded_pool_ends and real_time >= pet:
        pool_end_resources[pid] = dict(resources)
        pool_end_pity_states[pid] = pity_state.to_dict()
        recorded_pool_ends.add(pid)
```

**记录时机**：
1. WaitAction 执行后检查
2. DrawAction 执行后检查
3. 循环结束后兜底检查

**数据格式**：
```python
pool_end_pity_states = {
    'pool_1': {'counters': {'soft_pity': 15, 'hard_pity': 15}},
    'pool_2': {'counters': {'soft_pity': 0, 'hard_pity': 0}},
}
```

#### 🆕 变更：`run_simulation_compact` 新增更多逐抽字段

compact dict 输出现在包含更丰富的逐抽信息：

| 字段 | 类型 | 说明 |
|------|------|------|
| `draw_pity_names` | `List[Optional[str]]` | 🆕 触发的保底名称 |
| `draw_pity_counter_max` | `List[int]` | 🆕 每抽时池子最大保底计数器值 |
| `pool_card_counts` | `Dict[str, Dict[str, int]]` | 🆕 每池每卡计数 |
| `pool_pity_counts` | `Dict[str, int]` | 🆕 每池保底触发次数 |

#### 🆕 变更：保底触发判定增强

```python
pity_triggered = False
triggered_pity_name = None
if original_probs is not None:
    for card_id, orig_prob in original_probs.items():
        new_prob = probabilities.get(card_id, 0)
        if new_prob > orig_prob * 1.01:
            pity_triggered = True
            break

if _pity_engine and pity_triggered:
    spec = _pity_engine.get_spec(pool.id)
    if spec:
        for pname in spec.pity_names:
            behavior = _pity_engine.behaviors.get(pname)
            if behavior is None:
                continue
            cv = pity_state.get(pname)
            if hasattr(behavior, 'start_at') and cv >= behavior.start_at:
                triggered_pity_name = pname
                break
```

**新增**：`triggered_pity_name` 记录具体是哪个保底机制触发的。

---

### 2.5 `streaming.py` — 流式分析器（已变更）

**文件位置**：[core/streaming.py](file:///workspace/gacha_simulator/gacha_simulator/core/streaming.py)

#### 🆕 变更：`extract_aggregate` 新增 `pool_end_pity_states` 提取

```python
def extract_aggregate(compact):
    ...
    return {
        ...
        'pool_end_pity_states': dict(compact.get('pool_end_pity_states', {})),  # 🆕
        'pool_resources_consumed': pool_resources_consumed,
        'pool_resources_gained': pool_resources_gained,
        'pool_counter_max': pool_counter_max,
    }
```

#### 🆕 变更：`StreamingSuccessCounter` 使用 `SuccessChecker`

```python
class StreamingSuccessCounter(StreamingAnalyzer):
    def __init__(self, target_specs, gdr_key, gdr_threshold, ...):
        from .gdr import SuccessChecker
        self._checker = SuccessChecker(
            target_specs, gdr_key, gdr_threshold, ...
        )
```

---

### 2.6 `vulnerability.py` — 脆弱性分析（已变更）

**文件位置**：[core/vulnerability.py](file:///workspace/gacha_simulator/gacha_simulator/core/vulnerability.py)

#### 🆕 变更：使用 `pool_end_pity_states` 提取保底统计

```python
pes = r.get('pool_end_pity_states', {})
if pool_id in pes:
    counters = pes[pool_id].get('counters', {})
    for cname, cval in counters.items():
        ...
```

脆弱性分析现在能从 compact dict 中提取每个池子结束时的保底计数器状态，用于计算保底统计快照（`PityStatSnapshot`）。

---

### 2.7 `gdr.py` — GDR 判定系统

**文件位置**：[core/gdr.py](file:///workspace/gacha_simulator/gacha_simulator/core/gdr.py)

#### `SuccessChecker` 类

```python
class SuccessChecker:
    def __init__(self, target_specs, gdr_key='target_achievement',
                 gdr_threshold=None,
                 desire_weights=None, miss_cost_weights=None,
                 card_value_weights=None, ssr_ids=None,
                 weapon_character_map=None):
        ...

    def compute_gdr(self, compact_or_aggregate):
        ...

    def is_success(self, compact_or_aggregate):
        return self.compute_gdr(compact_or_aggregate) >= self.gdr_threshold

    def check_batch(self, results):
        ...

    @classmethod
    def from_registry(cls, gdr_key, target_specs, gdr_threshold=None, **kwargs):
        ...
```

**被使用位置**：
- [worst_impact.py#L170-L180](file:///workspace/gacha_simulator/gacha_simulator/core/worst_impact.py#L170-L180)：`WorstImpactAnalyzer._build_success_checker()`
- [streaming.py#L18-L23](file:///workspace/gacha_simulator/gacha_simulator/core/streaming.py#L18-L23)：`StreamingSuccessCounter.__init__()`

---

### 2.8 `run_batch_parallel` — 批量模拟入口

**调用链**：

```
gacha_panel.py: SimulationThread
    └─ run_batch_parallel(..., strategy_name='smart', strategy_params={})

strategy_panel.py: StrategyWorker
    ├─ _forward_method()
    │   └─ run_batch_parallel(..., strategy_name='smart', strategy_params={})
    └─ _backward_method()
        └─ run_batch_parallel(..., strategy_name='smart', strategy_params={})

resource_search_panel.py: ResourceSearchWorker
    └─ run_batch_parallel(..., strategy_name='smart', strategy_params={})

retreat_search.py: RetreatSearchWorker
    └─ run_batch_parallel(..., strategy_name='smart', strategy_params={})
```

**`run_batch_parallel` 签名**：
```python
def run_batch_parallel(
    ...
    strategy_name: str = 'smart',
    strategy_params: Optional[dict] = None,
    ...
) -> List[Optional[Dict[str, Any]]]:
```

**执行流程**：
```
run_batch_parallel(strategy_name='smart', strategy_params={})
    ↓
_wk_init(..., strategy_name='smart', strategy_params={})  # 设置全局变量
    ↓
_wk_run_single(seed, target_specs, initial_resources)
    ↓
strategy_factory = STRATEGY_REGISTRY['smart']['factory']
strategy = factory(target_set, {})
    ↓
GachaService(pools, strategy, stop_cond, target_set, ...)
    ↓
service.run_simulation_compact(state)  # 返回 compact dict（含 pool_end_pity_states）
```

---

### 2.9 `ConfigStore` — 配置存储

**文件位置**：[core/config_store.py#L92-L105](file:///workspace/gacha_simulator/gacha_simulator/core/config_store.py#L92-L105)

```python
@dataclass
class ConfigStore:
    ...
    strategy_type: str = '按需追卡'   # ← 字符串，无参数存储
    auto_wait: bool = True
```

**映射关系**（config_panel.py）：
```python
strategy_map = {"按需追卡": 0, "指定池抽卡": 1}
self.strategy_type.setCurrentIndex(strategy_map.get(store.strategy_type, 0))
```

**问题**：
- 只存字符串 `"按需追卡"` 或 `"指定池抽卡"`
- **没有 `strategy_params` 的存储**
- 配置导出/导入时只导出字符串，无参数信息

---

## 三、硬编码位置汇总

### 3.1 硬编码 `strategy_name='smart'`

| 文件 | 位置 | 说明 |
|------|------|------|
| `gacha_panel.py` | [SimulationThread](file:///workspace/gacha_simulator/gacha_simulator/gui/gacha_panel.py) | 批量模拟面板 |
| `strategy_panel.py` | [_forward_method](file:///workspace/gacha_simulator/gacha_simulator/gui/strategy_panel.py) | 前进法 |
| `strategy_panel.py` | [_backward_method](file:///workspace/gacha_simulator/gacha_simulator/gui/strategy_panel.py) | 后退法 |
| `retreat_search.py` | [RetreatSearchWorker](file:///workspace/gacha_simulator/gacha_simulator/core/retreat_search.py) | 退路搜索 |
| `resource_search_panel.py` | [ResourceSearchWorker](file:///workspace/gacha_simulator/gacha_simulator/gui/resource_search_panel.py) | 资源搜索 |

**共 5 处硬编码**。

### 3.2 硬编码策略类型映射

[config_panel.py](file:///workspace/gacha_simulator/gacha_simulator/gui/config_panel.py)：
```python
strategy_map = {"按需追卡": 0, "指定池抽卡": 1}
self.strategy_type.setCurrentIndex(strategy_map.get(store.strategy_type, 0))
```

**问题**：
- 显示名为中文，与 `STRATEGY_REGISTRY` 的 key 不匹配
- `STRATEGY_REGISTRY` 用 `'smart'`，这里用 `"按需追卡"`
- **没有参数编辑 UI**

### 3.3 硬编码停止条件

[batch_simulator.py#L525](file:///workspace/gacha_simulator/gacha_simulator/gui/batch_simulator.py#L525)：
```python
stop_cond = _AllPoolsEnd(_wk_end_time)
```

**问题**：所有批量模拟都使用同一个停止条件 `_AllPoolsEnd`，没有参数化。

### 3.4 专用策略/停止条件未入注册表

| 类 | 文件 | 基类 | 注册表 |
|----|------|------|--------|
| `_DrawTargetStrategy` | worst_impact.py | ✅ `Strategy` | ❌ 未注册 |
| `_TargetPoolEnd` | worst_impact.py | ✅ `StopCondition` | ❌ 未注册 |
| `_AllPoolsEnd` | batch_simulator.py | ❌ 无基类 | ❌ 未注册 |

---

## 四、架构问题总结

### 问题 1：两套策略体系并存

- `core/strategy.py`：有基类，无注册表，无参数机制
- `batch_simulator.py`：无基类，有注册表，有参数机制
- `_DrawTargetStrategy`：**继承了基类但未入注册表**

### 问题 2：硬编码 `strategy_name='smart'`

5 个调用位置全部硬编码 `smart`，导致：
- 无法切换策略进行对比
- 策略比较面板无法实现（计划文档已写，但面板未实现）

### 问题 3：ConfigStore 策略配置不完整

- 只存 `strategy_type: str`
- 不存 `strategy_params`
- 导出/导入丢失参数

### 问题 4：UI 与注册表不同步

| `STRATEGY_REGISTRY` | `config_panel.py` |
|---------------------|-------------------|
| key: `'smart'` | 显示: `"按需追卡"` |
| key: `'pool_quota'` | ❌ 不存在 |
| key: `'pity_reserve'` | ❌ 不存在 |
| key: `'stop_on_target'` | ❌ 不存在 |

注册表有 4 种策略，UI 只有 2 种选项。

### 问题 5：停止条件未注册

`_AllPoolsEnd`（batch_simulator.py）和 `_TargetPoolEnd`（worst_impact.py）都是独立定义，没有类似 `STOP_CONDITION_REGISTRY` 的机制。但 `_TargetPoolEnd` 已继承了 `StopCondition` 基类。

### 🆕 问题 6：`SuccessChecker` 使用不一致

| 位置 | 使用方式 |
|------|---------|
| `worst_impact.py` | ✅ 使用 `SuccessChecker` 类 |
| `streaming.py` | ✅ 使用 `SuccessChecker` 类 |
| `vulnerability.py` | ❌ 直接调用 `_is_success()` 函数 |
| `analysis_panel.py` | ❌ 直接调用 `compute_gdr_from_compact()` |

应统一使用 `SuccessChecker` 类。

---

## 五、重构方案

### 5.1 统一策略基类

将 `batch_simulator.py` 中的 4 个策略类移到 `core/strategy.py`，让它们都继承 `Strategy` 基类：

```python
# core/strategy.py
class Strategy(ABC):
    lookahead: Optional[float] = None
    
    @abstractmethod
    def select_action(self, state, history, current_pools, 
                      future_schedules, target_cards, stop_condition) -> Action:
        pass
    
    def observe(self, iv: 'InfoVector') -> None:
        """可选的观察方法"""
        pass
```

### 5.2 建立统一的注册表

在 `core/strategy.py` 中定义 `STRATEGY_REGISTRY`：

```python
STRATEGY_REGISTRY = {
    'smart': {...},
    'pool_quota': {...},
    'pity_reserve': {...},
    'stop_on_target': {...},
}
```

从 `gui/batch_simulator.py` 导出供外部使用。

### 5.3 ConfigStore 增加参数存储

```python
@dataclass
class ConfigStore:
    strategy_name: str = 'smart'
    strategy_params: Dict[str, Any] = dc_field(default_factory=dict)
```

### 5.4 UI 面板从注册表动态生成

修改 `config_panel.py`，从 `STRATEGY_REGISTRY` 动态生成策略选择下拉框和参数配置区：

```python
def _setup_strategy_tab(self, parent):
    for key, info in STRATEGY_REGISTRY.items():
        self.strategy_combo.addItem(info['display_name'], key)
        # 根据 params 动态生成参数控件
```

### 5.5 开放 `run_batch_parallel` 的 `stop_condition_name` 参数

```python
def run_batch_parallel(
    ...
    strategy_name: str = 'smart',
    strategy_params: Optional[dict] = None,
    stop_condition_name: str = 'all_pools_end',
    stop_condition_params: Optional[dict] = None,
    ...
)
```

### 5.6 🆕 统一 `SuccessChecker` 使用

将 `vulnerability.py` 和 `analysis_panel.py` 中的直接 GDR 调用替换为 `SuccessChecker` 类。

### 5.7 预估工作量

| 任务 | 优先级 | 工作量 |
|------|--------|--------|
| 迁移策略类到 core/strategy.py | P1 | 中 |
| 统一注册表到 core/ | P1 | 小 |
| ConfigStore 增加 strategy_params | P2 | 小 |
| config_panel 从注册表动态生成 UI | P2 | 中 |
| 移除 5 处硬编码 smart | P2 | 小 |
| 统一 SuccessChecker 使用 | P2 | 小 |
| 实现策略比较面板（已有计划文档） | P3 | 中 |
| 停止条件注册表 | P3 | 中 |

---

## 六、推荐实施顺序

**Phase 1：基础统一（P1）**
1. 将 `batch_simulator.py` 的 4 个策略类迁移到 `core/strategy.py`
2. 将 `STRATEGY_REGISTRY` 迁移到 `core/strategy.py` 并导出
3. 在 `gui/batch_simulator.py` 从 `core.strategy` 导入注册表
4. ConfigStore 增加 `strategy_params` 字段

**Phase 2：UI 联动（P2）**
5. config_panel 从注册表动态生成策略选择 UI
6. 策略参数配置区根据 `params` 动态生成控件
7. 移除 5 处硬编码，改用 ConfigStore 中的值
8. 统一 `SuccessChecker` 使用

**Phase 3：高级功能（P3）**
9. 实现策略比较面板（已有详细计划文档）
10. 停止条件注册表
11. 策略保存/加载（导出配置包含完整参数）

---

## 七、注意事项：重构风险与应对措施

### 7.1 向后兼容性风险

**风险点**：
- 现有配置文件只保存 `strategy_type: str`（中文 `"按需追卡"`）
- 若直接改为 `strategy_name: str`（英文 key `"smart"`），**现有配置将无法正确加载**
- `ConfigStore` 序列化/反序列化逻辑可能受影响

**应对措施**：
1. 保留 `strategy_type` 字段作为别名，兼容旧配置
2. 添加迁移逻辑：`if store.strategy_type in strategy_map: store.strategy_name = strategy_map[store.strategy_type]`
3. 配置保存时同时保存新旧字段，或仅保存新字段

**示例代码**：
```python
@dataclass
class ConfigStore:
    strategy_type: str = '按需追卡'  # 保留旧字段
    strategy_name: str = 'smart'
    strategy_params: Dict[str, Any] = dc_field(default_factory=dict)
    
    def __post_init__(self):
        if self.strategy_type and not self.strategy_name:
            old_to_new = {"按需追卡": "smart", "指定池抽卡": "pool_quota"}
            if self.strategy_type in old_to_new:
                self.strategy_name = old_to_new[self.strategy_type]
```

---

### 7.2 多进程 worker 依赖风险

**风险点**：
- `batch_simulator.py` 中的策略类依赖 `_wk_pools` 等 worker 全局变量
- 若将这些类移到 `core/strategy.py`，**依赖关系可能断裂**
- `_PityReserveStrategy` 还依赖 `_wk_pity_engine`、`_wk_pity_state_init`

**应对措施**：
1. 保留 `batch_simulator.py` 中的工厂函数，但改为从 `core.strategy` 导入类
2. 工厂函数仍接收 `target_set` + `params`，负责构造对象
3. 策略类内部尽量减少对全局变量的依赖，通过 `select_action` 传入
4. 🆕 `_PityReserveStrategy` 需要特殊处理：将 `_wk_pity_engine` 等作为构造参数传入

**示例**：
```python
# gui/batch_simulator.py 中
from gacha_simulator.core.strategy import (
    SmartStrategy, PoolQuotaStrategy, PityReserveStrategy, StopOnTargetStrategy
)

def _create_pity_reserve_strategy(target_set, params):
    pct = params.get('pity_threshold_pct', 80.0)
    return PityReserveStrategy(
        target_set, pity_threshold_pct=pct,
        pity_engine=_wk_pity_engine,
        pity_state_init=_wk_pity_state_init,
        pools=_wk_pools,
    )
```

---

### 7.3 参数类型验证风险

**风险点**：
- 新增 `strategy_params` 为 `Dict[str, Any]`，无类型约束
- UI 动态生成控件时可能输入错误值类型
- `PityReserveStrategy` 的 `pity_threshold_pct` 若传入 string 会导致运行时错误

**应对措施**：
1. 注册表中参数定义包含类型校验函数
2. ConfigStore 加载/保存时进行参数验证
3. 策略构造函数接收参数前先验证

**示例参数定义**：
```python
'params': {
    'pity_threshold_pct': {
        'type': 'float',
        'display_name': '保底概率阈值(%)',
        'default': 80.0,
        'min': 0.0,
        'max': 100.0,
        'validator': lambda x: 0.0 <= x <= 100.0
    }
}
```

---

### 7.4 测试覆盖不足风险

**风险点**：
- 重构涉及多个模块（core、gui、service）
- 现有测试可能未覆盖所有策略场景
- 修改可能引入隐蔽 bug（如资源泄漏、参数不匹配）

**应对措施**：
1. 重构前先添加关键路径的回归测试
2. 重点测试：
   - 批量模拟调用链
   - 配置保存/加载/迁移
   - UI 参数编辑
   - 多策略切换
   - 🆕 保底状态在链式模拟中的传递正确性
3. 保留原实现作为分支，必要时可快速回滚

---

### 7.5 计划文档中的未完成功能

**风险点**：
- 计划文档 `docs/superpowers/plans/2026-05-13-strategy-comparison-panel.md` 提到策略比较面板
- 该面板尚未实现，但重构需要为此预留接口
- 若未预留，后续实现策略比较可能需要再次大改

**应对措施**：
1. 重构时确保 `run_batch_parallel` 能接收任意策略名+参数
2. ConfigStore 设计应支持保存**多个策略配置**（便于对比）
3. 提前预留策略比较面板的挂载点（main_window 中）

---

### 7.6 已有历史模拟结果兼容性

**风险点**：
- 用户可能已有保存的模拟结果（compact dict 列表）
- 这些结果是用 `smart` 策略生成的
- 重构后若改变了策略行为，**历史结果与新模拟可能不可比**
- 🆕 旧 compact dict 可能缺少 `pool_end_pity_states`、`draw_pity_names` 等新字段

**应对措施**：
1. 确保策略语义完全不变（仅调整代码结构）
2. 在结果元数据中记录生成时的策略名和版本
3. 添加结果兼容性检查，若版本不兼容给出提示
4. 🆕 所有读取 compact dict 的代码已使用 `.get()` 带默认值，对旧格式兼容

---

### 🆕 7.7 `pool_end_pity_states` 数据一致性风险

**风险点**：
- `gacha_service.py` 中 `pool_end_pity_states` 的记录时机有 3 处（WaitAction 后、DrawAction 后、循环结束后兜底）
- 若池子结束时间恰好与抽卡时间重合，可能重复记录或遗漏
- `worst_impact.py` 中读取时使用 `pool.id in pool_end_pity` 匹配，但新池子 id 为 `_worst_impact_pool_0`，可能与批量模拟的池子 id 不匹配

**应对措施**：
1. `recorded_pool_ends` 集合确保不重复记录
2. `worst_impact.py` 中已有 fallback 逻辑：若精确匹配失败，取最后一个 key
3. 建议增加单元测试验证边界情况

---

## 八、参考文档与计划

- [docs/superpowers/plans/2026-05-13-strategy-comparison-infra.md](file:///workspace/gacha_simulator/docs/superpowers/plans/2026-05-13-strategy-comparison-infra.md)
- [docs/superpowers/plans/2026-05-13-strategy-comparison.md](file:///workspace/gacha_simulator/docs/superpowers/plans/2026-05-13-strategy-comparison.md)
- [docs/superpowers/plans/2026-05-13-strategy-comparison-panel.md](file:///workspace/gacha_simulator/docs/superpowers/plans/2026-05-13-strategy-comparison-panel.md)

---

## 九、变更追踪（本次更新摘要）

| 变更项 | 文件 | 变更类型 | 影响 |
|--------|------|---------|------|
| `pool_end_pity_states` 输出 | gacha_service.py | 🆕 新增字段 | worst_impact.py、streaming.py、vulnerability.py 均已适配 |
| `draw_pity_names` 输出 | gacha_service.py | 🆕 新增字段 | 过程分析可区分保底名称 |
| `draw_pity_counter_max` 输出 | gacha_service.py | 🆕 新增字段 | 流式提取器已使用 |
| `pool_card_counts` 输出 | gacha_service.py | 🆕 新增字段 | 每池每卡计数 |
| `pool_pity_counts` 输出 | gacha_service.py | 🆕 新增字段 | 每池保底触发次数 |
| 保底状态传递 | worst_impact.py | 🔄 变更 | 链式模拟正确传递保底计数器 |
| `SuccessChecker` 统一 | worst_impact.py, streaming.py | 🔄 变更 | 使用 `SuccessChecker` 类替代直接调用 |
| `_TargetPoolEnd` 继承基类 | worst_impact.py | 🔄 变更 | 继承 `StopCondition`，签名增加 `stats` |
| `WorstImpactAnalyzer` 增加权重参数 | worst_impact.py | 🔄 变更 | 支持 desire/miss_cost/card_value 权重 |
| `extract_aggregate` 增加 pity_states | streaming.py | 🔄 变更 | 流式提取器传递保底状态 |
