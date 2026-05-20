# 策略代码调查与重构方案报告

> 调查日期：2026-05-20（第三次更新版）
> 基于代码版本：v1.8.0
> 变更说明：本次更新基于对底层代码的全面审查，新增项目整体架构风险分析与重构方案，将视角从"策略代码"扩展到"项目整体"。

---

## 一、现状全景图

### 1.1 策略代码的分布位置

策略代码分散在 **6 个模块**中，形成了两套并行的策略体系：

```
gacha_simulator/
├── core/
│   ├── strategy.py          ← 基类 + SmartStrategy + 通用策略（导出）
│   ├── worst_impact.py      ← 专用 _DrawTargetStrategy + _TargetPoolEnd
│   ├── streaming.py         ← 流式分析器（提取 pool_end_pity_states）
│   └── vulnerability.py     ← 脆弱性分析（使用 pool_end_pity_states）
│
├── gui/
│   ├── batch_simulator.py   ← STRATEGY_REGISTRY + 3个具体实现（_SmartStrategy 已迁移到 core）
│   ├── config_panel.py      ← 策略UI配置（硬编码下拉框）
│   ├── strategy_panel.py    ← 前进/后退法分析（硬编码 smart）
│   ├── gacha_panel.py       ← 批量模拟（硬编码 smart）
│   ├── resource_search_panel.py ← 资源搜索（硬编码 smart）
│   └── retreat_panel.py     ← 退路分析（无策略选择）
│
└── service/
    └── gacha_service.py     ← 策略执行引擎（含 pool_end_pity_states）
```

### 1.2 两套策略体系对比

| 维度 | 体系 A：`core/strategy.py` | 体系 B：`gui/batch_simulator.py` |
|------|--------------------------|--------------------------------|
| **定位** | 被 `GachaService` 直接使用 | 被 `run_batch_parallel` 批量模拟使用 |
| **基类** | ✅ 有 `Strategy` 抽象基类 | ❌ 无基类，3个独立类（SmartStrategy 已迁至 core） |
| **注册表** | ❌ 无注册表 | ✅ 有 `STRATEGY_REGISTRY` |
| **工厂函数** | ❌ 无 | ✅ 有 4 个 `_create_*` 函数 |
| **可配置参数** | ❌ 无参数机制 | ✅ 通过 `strategy_params` 传递 |
| **实例方法** | `select_action` + `observe` | `select_action` + `observe` |
| **全局变量依赖** | ❌ 不依赖 | ✅ 依赖 `_wk_pools`、`_wk_pity_engine` 等 |

---

## 二、项目整体架构风险分析

> 以下风险点不仅限于策略代码，而是基于对 core/、service/、gui/ 全部模块的底层审查发现的系统性问题。

### 风险 R1：compact dict 无 Schema 保护（严重程度：🔴 高）

**位置**：`gacha_service.py`（生产者）、`streaming.py`、`vulnerability.py`、`worst_impact.py`、`gdr.py`、`analysis_panel.py`（消费者）

**问题描述**：
`run_simulation_compact()` 返回一个 `Dict[str, Any]`，没有任何类型约束或字段文档。所有消费模块通过 `compact.get('field', default)` 访问，存在以下问题：

1. **字段名拼写错误无编译期检查**：如写成 `compact.get('draw_card_ids')` vs `compact.get('draw_cards_ids')`，运行时不会报错，只会静默返回默认值
2. **新增字段无通知机制**：`gacha_service.py` 新增了 `draw_pity_names`、`draw_pity_counter_max`、`pool_card_counts`、`pool_pity_counts`、`pool_end_pity_states` 等字段，但没有任何消费者被强制更新
3. **旧格式数据兼容性无保证**：旧 compact dict 缺少新字段时，`.get()` 返回默认值可能掩盖逻辑错误
4. **字段语义隐含**：如 `draw_pity` 是 `List[bool]`，`draw_pity_names` 是 `List[Optional[str]]`，但没有任何地方记录这些类型

**影响范围**：所有读取 compact dict 的模块（约 15+ 处）

**建议方案**：
```python
@dataclass
class CompactResult:
    draw_card_ids: List[str]
    draw_pool_ids: List[str]
    draw_times: List[float]
    draw_pity: List[bool]
    draw_pity_names: List[Optional[str]]
    draw_pity_counter_max: List[int]
    draw_resources_consumed: List[Dict[str, float]]
    draw_resources_gained: List[Dict[str, float]]
    wait_durations: List[float]
    total_consumed: Dict[str, float]
    total_gained: Dict[str, float]
    card_counts: Dict[str, int]
    pool_draw_counts: Dict[str, int]
    pool_card_counts: Dict[str, Dict[str, int]]
    pool_pity_counts: Dict[str, int]
    total_draws: int
    total_waits: int
    pity_triggers: int
    final_resources: Dict[str, float]
    final_time: float
    final_pity_state: Dict[str, Any]
    pool_end_resources: Dict[str, Dict[str, float]]
    pool_end_pity_states: Dict[str, Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'CompactResult':
        return cls(**{f.name: d.get(f.name, f.default) for f in dataclasses.fields(cls)})
```

---

### 风险 R2：`run_simulation` 与 `run_simulation_compact` 代码高度重复（严重程度：🔴 高）

**位置**：[gacha_service.py](file:///workspace/gacha_simulator/gacha_simulator/service/gacha_service.py)

**问题描述**：
`GachaService` 有两个模拟方法：
- `run_simulation()` → 返回 `List[InfoVector]`（约 120 行）
- `run_simulation_compact()` → 返回 `Dict[str, Any]`（约 220 行）

两者的主循环逻辑几乎完全相同（策略选择→抽卡/等待→保底处理→状态更新），区别仅在于数据收集方式：
- `run_simulation` 将每步记录为 `InfoVector` 对象追加到列表
- `run_simulation_compact` 将数据追加到各个并行列表

**具体重复点**：
1. 策略调用与行动分发（DrawAction/WaitAction 分支）
2. 保底概率修改与恢复
3. 资源消耗与获取
4. 保底触发判定
5. 池子可用性过滤

**影响**：修改模拟核心逻辑时必须同步修改两处，极易遗漏导致行为不一致

**建议方案**：
```python
def run_simulation(self, initial_state, max_iterations=100000,
                   collector=None):
    if collector is None:
        collector = InfoVectorCollector()
    ...
    for iteration in range(max_iterations):
        ...
        if isinstance(action, DrawAction):
            ...
            collector.on_draw(reward, pool, spent, ...)
        elif isinstance(action, WaitAction):
            ...
            collector.on_wait(duration, rg, ...)
    return collector.get_result()

class InfoVectorCollector:
    def on_draw(self, ...): ...
    def on_wait(self, ...): ...
    def get_result(self) -> List[InfoVector]: ...

class CompactCollector:
    def on_draw(self, ...): ...
    def on_wait(self, ...): ...
    def get_result(self) -> Dict[str, Any]: ...
```

---

### 风险 R3：多进程 Worker 全局变量模式（严重程度：🔴 高）

**位置**：[batch_simulator.py:156-191](file:///workspace/gacha_simulator/gui/batch_simulator.py#L156-L191)

**问题描述**：
`batch_simulator.py` 使用 9 个模块级全局变量（`_wk_pools`、`_wk_schedule_mgr`、`_wk_end_time` 等）通过 `multiprocessing.Pool(initializer=_wk_init)` 注入子进程。

**具体风险**：
1. **策略类与全局变量紧耦合**：`_PoolQuotaStrategy`、`_PityReserveStrategy`、`_StopOnTargetStrategy` 直接访问 `_wk_pools` 全局变量进行兑换池查找，而非通过 `select_action` 参数传入
2. **`_PityReserveStrategy` 依赖 3 个全局变量**：`_wk_pity_engine`、`_wk_pity_state_init`、`_wk_pools`，使得该策略无法在非 worker 上下文中使用
3. **`_AllPoolsEnd` 停止条件未继承基类**：不继承 `StopCondition`，无法被 `GachaService` 的类型检查捕获
4. **单进程回退路径共享全局变量**：`max_workers <= 1` 时直接在主进程调用 `_wk_init`，全局变量可能被意外修改

**影响范围**：所有策略类、`run_batch_parallel`、`_wk_run_single`

**建议方案**：
```python
@dataclass
class SimulationContext:
    pools: List[Pool]
    schedule_mgr: Any
    end_time: float
    pity_engine: Any
    resource_gain: Any
    pity_state_init: Optional[dict]
    card_defs: list

class PoolQuotaStrategy(Strategy):
    def __init__(self, target_set, pool_quotas=None, context: SimulationContext = None):
        self._context = context
        ...

    def select_action(self, state, history, current_pools, ...):
        pools = self._context.pools if self._context else current_pools
        ...
```

---

### 风险 R4：两套策略体系并存导致行为不一致（严重程度：🟡 中）

**位置**：`core/strategy.py` vs `gui/batch_simulator.py`

**问题描述**：
`core/strategy.py` 中的 `SmartStrategy` 与 `batch_simulator.py` 中的 `_SmartStrategy`（现已改为从 core 导入）存在微妙差异：

1. `core/strategy.py` 的 `SmartStrategy` 通过 `all_pools` 构造参数获取池列表
2. `batch_simulator.py` 的 `_create_smart_strategy` 传入 `_wk_pools`（全局变量）
3. `batch_simulator.py` 中剩余 3 个策略（`_PoolQuotaStrategy`、`_PityReserveStrategy`、`_StopOnTargetStrategy`）**未继承 `Strategy` 基类**，缺少 `description()` 抽象方法实现
4. `core/strategy.py` 中的 `FixedCountStrategy`、`TargetHuntingStrategy`、`CompositeStrategy` **没有 `observe()` 方法**，但 `GachaService` 通过 `hasattr(strategy, 'acquired')` 检查并调用

**影响**：添加新策略时，开发者不确定应继承哪个基类、实现哪些方法

---

### 风险 R5：`SuccessChecker` 使用不一致（严重程度：🟡 中）

**位置**：多处

| 位置 | 使用方式 | 问题 |
|------|---------|------|
| `worst_impact.py` | ✅ `SuccessChecker` 类 | 正确 |
| `streaming.py` | ✅ `SuccessChecker` 类 | 正确 |
| `vulnerability.py` | ❌ `_is_success()` 私有函数 | 绕过 `SuccessChecker`，不支持 `ssr_ids`、`weapon_character_map` |
| `analysis_panel.py` | ❌ `compute_gdr_from_compact()` 直接调用 | 无统一阈值判定 |
| `process_analysis.py` | ❌ `compute_gdr_from_compact()` 直接调用 | 同上 |
| `extract_process()` in streaming.py | ❌ `compute_gdr_from_compact()` + 手动 `val >= gdr_threshold` | 重复了 `SuccessChecker.is_success` 的逻辑 |

**影响**：GDR 判定逻辑分散，修改阈值语义时需要改多处

---

### 风险 R6：`UNIFIED_GDR_REGISTRY` 注册无冲突检测（严重程度：🟡 中）

**位置**：[gdr.py](file:///workspace/gacha_simulator/gacha_simulator/core/gdr.py)

**问题描述**：
GDR 指标通过直接赋值注册到 `UNIFIED_GDR_REGISTRY` 字典，无命名冲突检测。若两个模块注册同名 key，后者静默覆盖前者。

此外，`compute_from_compact` 和 `compute_from_history` 两条计算路径并存，但无强制一致性校验——同一条 GDR 指标在两种路径下可能给出不同结果。

**建议方案**：
```python
def register_gdr(key: str, defn: GDRDefinition):
    if key in UNIFIED_GDR_REGISTRY:
        raise ValueError(f"GDR key '{key}' already registered")
    UNIFIED_GDR_REGISTRY[key] = defn
```

---

### 风险 R7：两个 `worst_impact.py` 文件并存（严重程度：🟡 中）

**位置**：
- `/workspace/worst_impact.py`（项目根目录，使用相对导入 `from .distribution`）
- `/workspace/gacha_simulator/core/worst_impact.py`（包内，使用相对导入 `from .distribution`）

**问题描述**：
根目录的 `worst_impact.py` 使用 `from .distribution import ...` 相对导入，这意味着它被当作 `gacha_simulator` 包的一部分。但它的位置在包外，可能导致导入混乱。两个文件内容相似但不完全相同：
- 根目录版本使用 `_DrawTargetStrategy`（继承 `Strategy`）+ `_TargetPoolEnd`（继承 `StopCondition`），逐池串行模拟
- core/ 版本使用 `SmartStrategy` + `CompositeStopCondition`，构建完整的多池环境一次性模拟

**影响**：开发者不确定应使用哪个版本；根目录文件可能是遗留代码

**建议方案**：删除根目录的 `worst_impact.py`，统一使用 `core/worst_impact.py`

---

### 风险 R8：两个 `docs/` 文件夹内容重复（严重程度：🟢 低）

**位置**：
- `/workspace/docs/`（项目根目录）
- `/workspace/gacha_simulator/docs/`（包内，多一个 `strategy_code_investigation_and_refactoring_plan.md`）

**问题描述**：两个文件夹内容几乎完全相同，属于重复。包内 docs 多出的文件是本报告。

**建议方案**：保留 `/workspace/docs/` 作为唯一文档目录，将本报告移至该目录，删除 `/workspace/gacha_simulator/docs/`

---

### 风险 R9：`_AllPoolsEnd` 未继承 `StopCondition` 基类（严重程度：🟡 中）

**位置**：[batch_simulator.py:193-201](file:///workspace/gacha_simulator/gui/batch_simulator.py#L193-L201)

**问题描述**：
```python
class _AllPoolsEnd:
    def __init__(self, end_time):
        self.end_time = end_time
    def check(self, state, history=None, stats=None):
        return state.real_time >= self.end_time
    def description(self):
        return ""
```

该类实现了 `StopCondition` 的接口但未继承，导致：
1. `isinstance(stop_cond, StopCondition)` 检查会失败
2. 无法被停止条件注册表管理
3. 与 `worst_impact.py` 中的 `_TargetPoolEnd`（已继承基类）不一致

---

### 风险 R10：`_PityReserveStrategy` 的保底状态重建逻辑（严重程度：🔴 高）

**位置**：[batch_simulator.py:289-301](file:///workspace/gacha_simulator/gui/batch_simulator.py#L289-L301)

**问题描述**：
```python
if _wk_pity_engine:
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
```

这段代码在每次 `select_action` 调用时**从头重建保底状态**：
1. 从初始状态开始
2. 遍历整个 history 重放所有抽卡
3. 计算当前保底概率

**问题**：
- **O(n²) 时间复杂度**：每次选择行动都重放整个历史，模拟 N 抽的总复杂度为 O(N²)
- **与 `GachaService` 的保底状态管理重复**：`GachaService` 内部已维护 `pity_state`，但策略无法访问
- **SSR 概率判定使用 `'ssr' in cid.lower()` 字符串匹配**：脆弱，依赖卡牌 ID 命名约定

**建议方案**：将当前保底概率作为 `select_action` 的上下文传入，或在 `GachaState` 中增加保底概率缓存

---

### 风险 R11：GUI 面板通过 `main_window.config_panel` 获取权重（严重程度：🟡 中）

**位置**：`worst_impact_panel.py`、`resource_search_panel.py`、`strategy_panel.py` 等

**问题描述**：
多个 GUI 面板通过 `self.window()` 向上查找 `MainWindow`，再访问 `config_panel` 的方法获取权重：
```python
main_window = self.window()
if hasattr(main_window, 'config_panel'):
    desire_weights = main_window.config_panel.get_desire_weights()
```

这种模式：
1. 隐式依赖 widget 层级结构
2. 面板无法独立使用或测试
3. 若 MainWindow 重构，所有面板都会受影响

**建议方案**：通过 `set_store()` 或信号机制传递权重数据，而非直接访问父窗口

---

### 风险 R12：`ConfigStore` 策略配置不完整（严重程度：🟡 中）

**位置**：[config_store.py](file:///workspace/gacha_simulator/gacha_simulator/core/config_store.py)

**问题描述**：
- 只存 `strategy_type: str`（中文 `"按需追卡"`）
- 不存 `strategy_params`
- 配置导出/导入时只导出字符串，无参数信息
- UI 与注册表不同步：注册表有 4 种策略，UI 只有 2 种选项

---

## 三、项目整体重构方案

### Phase 0：消除冗余与建立 Schema（优先级：P0，前置依赖）

**目标**：为后续重构建立安全基础

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 0.1 | 删除根目录 `worst_impact.py`，统一使用 `core/worst_impact.py` | 小 |
| 0.2 | 合并两个 `docs/` 目录，保留项目根目录 | 小 |
| 0.3 | 定义 `CompactResult` dataclass 替代裸 dict | 中 |
| 0.4 | `_AllPoolsEnd` 继承 `StopCondition` 基类 | 小 |

**步骤 0.3 详细设计**：

```python
# core/result_types.py
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class CompactResult:
    draw_card_ids: List[str] = field(default_factory=list)
    draw_pool_ids: List[str] = field(default_factory=list)
    draw_times: List[float] = field(default_factory=list)
    draw_pity: List[bool] = field(default_factory=list)
    draw_pity_names: List[Optional[str]] = field(default_factory=list)
    draw_pity_counter_max: List[int] = field(default_factory=list)
    draw_resources_consumed: List[Dict[str, float]] = field(default_factory=list)
    draw_resources_gained: List[Dict[str, float]] = field(default_factory=list)
    wait_durations: List[float] = field(default_factory=list)
    total_consumed: Dict[str, float] = field(default_factory=dict)
    total_gained: Dict[str, float] = field(default_factory=dict)
    card_counts: Dict[str, int] = field(default_factory=dict)
    pool_draw_counts: Dict[str, int] = field(default_factory=dict)
    pool_card_counts: Dict[str, Dict[str, int]] = field(default_factory=dict)
    pool_pity_counts: Dict[str, int] = field(default_factory=dict)
    total_draws: int = 0
    total_waits: int = 0
    pity_triggers: int = 0
    final_resources: Dict[str, float] = field(default_factory=dict)
    final_time: float = 0.0
    final_pity_state: Dict[str, Any] = field(default_factory=dict)
    pool_end_resources: Dict[str, Dict[str, float]] = field(default_factory=dict)
    pool_end_pity_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'CompactResult':
        import dataclasses
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)
```

**过渡策略**：`run_simulation_compact` 返回 `CompactResult`，同时提供 `to_dict()` 方法保持向后兼容。消费者逐步迁移到 `CompactResult`，迁移完成后移除 `to_dict()`。

---

### Phase 1：统一模拟核心（优先级：P1）

**目标**：消除 `run_simulation` 与 `run_simulation_compact` 的代码重复

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 1.1 | 定义 `SimulationCollector` 抽象基类 | 小 |
| 1.2 | 实现 `InfoVectorCollector` 和 `CompactCollector` | 中 |
| 1.3 | 重构 `GachaService.run_simulation` 使用 Collector 模式 | 中 |
| 1.4 | 删除旧的 `run_simulation_compact`，用 `run_simulation(collector=CompactCollector())` 替代 | 小 |

**步骤 1.1-1.2 详细设计**：

```python
# core/collector.py
from abc import ABC, abstractmethod

class SimulationCollector(ABC):
    @abstractmethod
    def on_draw(self, reward, pool, spent, pity_triggered, triggered_pity_name,
                pity_counter_max, resources_before, resources_after): ...
    @abstractmethod
    def on_wait(self, duration, resources_gained, real_time_before, real_time_after): ...
    @abstractmethod
    def on_pool_end(self, pool_id, resources, pity_state_dict): ...
    @abstractmethod
    def get_result(self): ...

class InfoVectorCollector(SimulationCollector):
    def __init__(self, session_id):
        self._history = []
        self._session_id = session_id
        self._stats = SimulationStats()
    def get_result(self) -> List[InfoVector]:
        return self._history

class CompactCollector(SimulationCollector):
    def __init__(self):
        self._result = CompactResult()
    def get_result(self) -> CompactResult:
        return self._result
```

---

### Phase 2：统一策略体系（优先级：P1）

**目标**：消除两套策略体系，所有策略继承 `Strategy` 基类

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 2.1 | `Strategy` 基类增加 `observe()` 方法（默认空实现） | 小 |
| 2.2 | 将 `_PoolQuotaStrategy`、`_PityReserveStrategy`、`_StopOnTargetStrategy` 迁移到 `core/strategy.py`，继承 `Strategy` | 中 |
| 2.3 | 将 `STRATEGY_REGISTRY` 迁移到 `core/strategy.py` | 小 |
| 2.4 | 消除策略对全局变量的依赖，改用构造参数注入 `SimulationContext` | 中 |
| 2.5 | `batch_simulator.py` 的工厂函数改为从 `core.strategy` 导入 | 小 |

**步骤 2.4 关键设计——消除全局变量依赖**：

```python
# core/strategy.py
class PityReserveStrategy(Strategy):
    lookahead = None

    def __init__(self, target_set, pity_threshold_pct=80.0,
                 pity_engine=None, pity_state_init=None, all_pools=None):
        self.target_set = target_set
        self.pity_threshold_pct = pity_threshold_pct / 100.0
        self._pity_engine = pity_engine
        self._pity_state_init = pity_state_init
        self._all_pools = all_pools or []
        self.acquired = {}

    def select_action(self, state, history, current_pools, ...):
        pools = self._all_pools or current_pools
        for t in self.target_set.targets:
            if self.acquired.get(t.card_id, 0) >= t.quantity_needed:
                continue
            for pool in pools:
                if pool.is_exchange and pool.exchange_card_id == t.card_id:
                    if pool.is_available_at(state.real_time) and state.can_afford(pool.cost):
                        return DrawAction(pool_id=pool.id)
        ...
```

**`batch_simulator.py` 工厂函数适配**：

```python
# gui/batch_simulator.py
from gacha_simulator.core.strategy import (
    SmartStrategy, PoolQuotaStrategy, PityReserveStrategy, StopOnTargetStrategy
)

def _create_pity_reserve_strategy(target_set, params):
    pct = params.get('pity_threshold_pct', 80.0)
    return PityReserveStrategy(
        target_set, pity_threshold_pct=pct,
        pity_engine=_wk_pity_engine,
        pity_state_init=_wk_pity_state_init,
        all_pools=_wk_pools,
    )
```

---

### Phase 3：统一 GDR 判定（优先级：P2）

**目标**：所有 GDR 判定统一使用 `SuccessChecker`

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 3.1 | `vulnerability.py` 的 `_is_success()` 替换为 `SuccessChecker` | 小 |
| 3.2 | `streaming.py` 的 `extract_process()` 使用 `SuccessChecker` | 小 |
| 3.3 | `analysis_panel.py` 的 GDR 调用统一为 `SuccessChecker` | 小 |
| 3.4 | `UNIFIED_GDR_REGISTRY` 增加 `register_gdr()` 函数，带冲突检测 | 小 |

---

### Phase 4：ConfigStore 与 UI 联动（优先级：P2）

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 4.1 | `ConfigStore` 增加 `strategy_name: str` 和 `strategy_params: Dict` | 小 |
| 4.2 | 添加旧字段迁移逻辑（`strategy_type` → `strategy_name`） | 小 |
| 4.3 | `config_panel.py` 从 `STRATEGY_REGISTRY` 动态生成策略下拉框 | 中 |
| 4.4 | 策略参数配置区根据 `params` 定义动态生成控件 | 中 |
| 4.5 | 移除 5 处硬编码 `strategy_name='smart'`，改用 ConfigStore 值 | 小 |
| 4.6 | GUI 面板权重获取改为通过 `set_store()` / 信号，而非 `self.window()` | 中 |

---

### Phase 5：高级功能（优先级：P3）

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 5.1 | 实现策略比较面板（已有计划文档） | 中 |
| 5.2 | 停止条件注册表 | 中 |
| 5.3 | `_PityReserveStrategy` 性能优化：保底概率缓存或通过 `select_action` 上下文传入 | 中 |
| 5.4 | compact dict 元数据：记录策略名、版本号、生成时间 | 小 |

---

## 四、重构实施路线图

```
Phase 0 (消除冗余 + Schema)     ──→  Phase 1 (统一模拟核心)
    │                                    │
    │                                    ↓
    └──→  Phase 2 (统一策略体系)  ←──  Phase 1 完成
              │
              ↓
         Phase 3 (统一 GDR 判定)
              │
              ↓
         Phase 4 (ConfigStore + UI 联动)
              │
              ↓
         Phase 5 (高级功能)
```

**关键依赖关系**：
- Phase 1 和 Phase 2 可并行，但都依赖 Phase 0 的 `CompactResult`
- Phase 3 依赖 Phase 2（策略迁移后 GDR 判定位置才稳定）
- Phase 4 依赖 Phase 2（ConfigStore 需要统一的策略注册表）
- Phase 5 依赖 Phase 2 + Phase 4

---

## 五、风险应对措施汇总

| 风险 | 严重程度 | 应对 Phase | 关键措施 |
|------|---------|-----------|---------|
| R1: compact dict 无 Schema | 🔴 高 | Phase 0 | 定义 `CompactResult` dataclass |
| R2: 模拟方法代码重复 | 🔴 高 | Phase 1 | Collector 模式统一 |
| R3: 全局变量模式 | 🔴 高 | Phase 2 | 构造参数注入 `SimulationContext` |
| R4: 两套策略体系 | 🟡 中 | Phase 2 | 统一继承 `Strategy` 基类 |
| R5: SuccessChecker 不一致 | 🟡 中 | Phase 3 | 全面替换为 `SuccessChecker` |
| R6: GDR 注册无冲突检测 | 🟡 中 | Phase 3 | `register_gdr()` 函数 |
| R7: 两个 worst_impact.py | 🟡 中 | Phase 0 | 删除根目录版本 |
| R8: 两个 docs/ 目录 | 🟢 低 | Phase 0 | 合并到根目录 |
| R9: _AllPoolsEnd 无基类 | 🟡 中 | Phase 0 | 继承 `StopCondition` |
| R10: 保底状态重建 O(N²) | 🔴 高 | Phase 5 | 保底概率缓存 |
| R11: GUI 面板耦合 MainWindow | 🟡 中 | Phase 4 | 信号/参数注入 |
| R12: ConfigStore 不完整 | 🟡 中 | Phase 4 | 增加 strategy_params |

---

## 六、向后兼容性策略

### 6.1 compact dict 过渡

```python
# gacha_service.py
def run_simulation_compact(self, initial_state, ...) -> Dict[str, Any]:
    result = self.run_simulation(initial_state, collector=CompactCollector(), ...)
    return result.to_dict()  # 过渡期保持 dict 返回

# 未来版本
def run_simulation_compact(self, initial_state, ...) -> CompactResult:
    return self.run_simulation(initial_state, collector=CompactCollector(), ...)
```

### 6.2 ConfigStore 迁移

```python
@dataclass
class ConfigStore:
    strategy_type: str = '按需追卡'
    strategy_name: str = 'smart'
    strategy_params: Dict[str, Any] = dc_field(default_factory=dict)

    def __post_init__(self):
        if self.strategy_type and self.strategy_name == 'smart':
            old_to_new = {"按需追卡": "smart", "指定池抽卡": "pool_quota"}
            if self.strategy_type in old_to_new:
                self.strategy_name = old_to_new[self.strategy_type]
```

### 6.3 历史模拟结果兼容

所有读取 compact dict 的代码已使用 `.get()` 带默认值。`CompactResult.from_dict()` 会忽略未知字段并补全缺失字段为默认值。

---

## 七、测试策略

### 7.1 重构前必写的回归测试

| 测试 | 覆盖路径 | 优先级 |
|------|---------|--------|
| `test_compact_result_roundtrip` | CompactResult ↔ dict 转换 | P0 |
| `test_simulation_compact_equals_dict` | 新 CompactCollector 输出与旧 dict 输出一致 | P1 |
| `test_all_strategies_inherit_base` | 所有策略类 isinstance(strategy, Strategy) | P2 |
| `test_strategy_registry_complete` | 注册表 key 与工厂函数对应 | P2 |
| `test_config_store_migration` | 旧 strategy_type → 新 strategy_name | P4 |
| `test_pool_end_pity_states_chain` | 链式模拟保底状态传递正确性 | P0 |

### 7.2 性能基准测试

| 测试 | 目的 |
|------|------|
| `bench_compact_vs_infovector` | 验证 Collector 模式不引入性能回退 |
| `bench_pity_reserve_strategy` | 量化 O(N²) 问题，为 Phase 5 优化提供基线 |

---

## 八、参考文档

- [docs/superpowers/plans/2026-05-13-strategy-comparison-infra.md](file:///workspace/docs/superpowers/plans/2026-05-13-strategy-comparison-infra.md)
- [docs/superpowers/plans/2026-05-13-strategy-comparison.md](file:///workspace/docs/superpowers/plans/2026-05-13-strategy-comparison.md)
- [docs/superpowers/plans/2026-05-13-strategy-comparison-panel.md](file:///workspace/docs/superpowers/plans/2026-05-13-strategy-comparison-panel.md)
- [docs/HANDOVER.md](file:///workspace/docs/HANDOVER.md)

---

## 九、变更追踪

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-05-20 | v1 | 初始版本：策略代码调查 |
| 2026-05-20 | v2 | 第二次更新：反映 worst_impact.py 和 gacha_service.py 变更 |
| 2026-05-20 | v3 | 第三次更新：扩展为项目整体重构方案，新增 12 个风险点、5 个 Phase、CompactResult Schema 设计、Collector 模式设计 |
