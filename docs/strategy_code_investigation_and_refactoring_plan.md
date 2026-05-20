# 策略代码调查与重构方案报告

> 调查日期：2026-05-20（第四次更新版）
> 基于代码版本：v1.8.0
> 变更说明：本次更新新增"策略信息传入机制"专题分析，提出 `StrategyContext` 统一方案，重构 Phase 2 设计以解决信息传入不统一问题。

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

## 二、策略信息传入机制分析（v4 新增）

### 2.1 当前 `select_action` 签名

```python
class Strategy(ABC):
    @abstractmethod
    def select_action(
        self,
        state: GachaState,              # 资源、保底计数器、时间、extra_state
        history: List[InfoVector],       # 完整历史记录
        current_pools: List[Pool],       # 当前可用池
        future_schedules: List[PoolSchedule],  # 未来池时间表
        target_cards: TargetCardSet,     # 目标卡集合
        stop_condition: StopCondition,   # 停止条件
    ) -> Action:
```

### 2.2 各策略实际使用的信息差异

| 信息 | SmartStrategy (core) | _PoolQuotaStrategy | _PityReserveStrategy | _StopOnTargetStrategy |
|------|---------------------|--------------------|-----------------------|-----------------------|
| `state` (资源/时间) | ✅ `can_afford`, `real_time` | ✅ `can_afford`, `real_time` | ✅ `can_afford`, `real_time` | ✅ `can_afford`, `real_time` |
| `history` | ❌ 不用 | ❌ 不用 | ✅ **重放历史重建保底** | ❌ 不用 |
| `current_pools` | ✅ 部分用 | ✅ 部分用 | ✅ 部分用 | ✅ 部分用 |
| `future_schedules` | ❌ 不用 | ❌ 不用 | ❌ 不用 | ❌ 不用 |
| `target_cards` | ❌ 不用（用构造时 `target_set`） | ❌ 不用 | ❌ 不用 | ❌ 不用 |
| `stop_condition` | ❌ 不用 | ❌ 不用 | ❌ 不用 | ❌ 不用 |
| `_wk_pools` 全局变量 | ❌ | ✅ **兑换池查找** | ✅ **兑换池查找** | ✅ **兑换池查找** |
| `_wk_pity_engine` 全局变量 | ❌ | ❌ | ✅ **保底概率计算** | ❌ |
| `self.acquired` 自维护 | ✅ | ✅ | ✅ | ✅ |
| `self.pool_draw_counts` 自维护 | ❌ | ✅ | ❌ | ❌ |

### 2.3 五个核心问题

**问题 P1：兑换池查找绕过 `current_pools`**

所有 batch 策略通过 `_wk_pools`（全局变量）查找兑换池，而非使用 `current_pools` 参数。原因是 `current_pools` 只包含当前时间可用的池，但策略需要知道所有池（含不可用的）来规划兑换路径。`SmartStrategy`（core 版）通过构造时的 `all_pools` 参数解决此问题，而 batch 版的策略直接用全局变量——两种方式不一致。

**问题 P2：保底概率信息完全缺失**

`select_action` 的参数中**没有任何保底概率信息**。`_PityReserveStrategy` 不得不从头重放整个 history 来重建保底状态，这是 O(N²) 的。而 `GachaService` 内部已经维护了 `pity_state` 和 `pity_engine`，每次抽卡前都调用 `before_draw()` 计算过保底概率，但策略无法访问这个计算结果。

**问题 P3：`history` 是低效的信息载体**

策略需要的信息（已获得哪些卡、各池抽了多少次）被编码在 `history: List[InfoVector]` 中，需要遍历才能提取。所以每个策略都自维护 `self.acquired` 字典来追踪，这本身就是对 `history` 信息不足的补偿。`GachaService` 内部已有 `SimulationStats` 维护了 `card_counts` 和 `pool_draw_counts`，但策略无法访问。

**问题 P4：`future_schedules` 和 `stop_condition` 无人使用**

这两个参数传入了但没有任何策略使用，增加了接口复杂度。`future_schedules` 需要 `strategy.lookahead` 非空时 `GachaService` 才会计算，但当前所有策略的 `lookahead` 都是 `None`。`stop_condition` 的信息对策略决策无意义——策略不需要知道何时停止，那是 `GachaService` 循环控制的事。

**问题 P5：`target_cards` 参数与构造时 `target_set` 重复**

策略通过构造函数接收 `target_set`，又通过 `select_action` 参数接收 `target_cards`，两者是同一个东西但来源不同。所有策略都忽略 `target_cards` 参数，只用构造时的 `target_set`。

### 2.4 信息流向图

```
GachaService 内部状态                    select_action 参数          策略实际需要
─────────────────                    ──────────────────         ────────────
state.resources ───────────────────→ state ──────────────────→ ✅ 直接使用
state.real_time ───────────────────→ state ──────────────────→ ✅ 直接使用
state.pity_counters ───────────────→ state ──────────────────→ ❌ 不用
state.extra_state ─────────────────→ state ──────────────────→ ❌ 不用

pity_state + pity_engine ─────────→ ❌ 未传入 ──────────────→ 🔴 保底概率（PityReserve 需重放）
simulation_stats.card_counts ─────→ ❌ 未传入 ──────────────→ 🔴 已获卡计数（策略自维护 acquired）
simulation_stats.pool_draw_counts → ❌ 未传入 ──────────────→ 🔴 各池抽卡次数（PoolQuota 自维护）

all_pools（含不可用池）───────────→ ❌ 未传入 ──────────────→ 🔴 兑换池查找（batch 策略用全局变量）
current_pools ─────────────────────→ current_pools ──────────→ ✅ 部分使用
future_schedules ──────────────────→ future_schedules ───────→ ❌ 无人使用
target_cards ──────────────────────→ target_cards ───────────→ ❌ 与构造时 target_set 重复
stop_condition ────────────────────→ stop_condition ─────────→ ❌ 无人使用
history ───────────────────────────→ history ────────────────→ ⚠️ 仅 PityReserve 用于重放
```

**结论**：策略真正需要的信息有 3 类未传入（保底概率、已获卡计数、全部池列表），而 3 个传入的参数无人使用（future_schedules、target_cards、stop_condition）。信息传入与实际需求严重错位。

---

## 三、项目整体架构风险分析

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

**建议方案**：见 Phase 2 的 `StrategyContext` 设计

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

### 风险 R8：两个 `docs/` 文件夹内容重复（严重程度：🟢 低）→ ✅ 已解决

两个 `docs/` 目录已合并到 `/workspace/docs/`，`/workspace/gacha_simulator/docs/` 已删除。

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

**建议方案**：见 Phase 2 的 `StrategyContext.pity_probabilities` 设计

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

### 风险 R13：策略信息传入与实际需求严重错位（严重程度：🔴 高）（v4 新增）

**位置**：`Strategy.select_action` 签名、`GachaService` 调用点、`batch_simulator.py` 全局变量

**问题描述**：详见第二章"策略信息传入机制分析"。核心矛盾：

| 传入但无人使用 | 需要但未传入 |
|---------------|-------------|
| `future_schedules` | 保底概率（`pity_probabilities`） |
| `target_cards`（与构造时 `target_set` 重复） | 已获卡计数（`acquired`/`card_counts`） |
| `stop_condition` | 全部池列表（`all_pools`，含不可用池） |

**后果**：
1. 策略被迫自维护状态（`self.acquired`、`self.pool_draw_counts`），与 `GachaService` 的 `SimulationStats` 重复
2. 保底概率缺失导致 `_PityReserveStrategy` 的 O(N²) 重放（R10）
3. 全部池列表缺失导致 batch 策略依赖全局变量（R3）
4. `observe()` 方法成为必要但非标准的补丁——`GachaService` 通过 `hasattr(strategy, 'acquired')` 判断是否调用

**建议方案**：见 Phase 2 的 `StrategyContext` 设计

---

## 四、项目整体重构方案

### Phase 0：消除冗余与建立 Schema（优先级：P0，前置依赖）

**目标**：为后续重构建立安全基础

| 步骤 | 内容 | 工作量 | 状态 |
|------|------|--------|------|
| 0.1 | 删除根目录 `worst_impact.py`，统一使用 `core/worst_impact.py` | 小 | 待实施 |
| 0.2 | 合并两个 `docs/` 目录，保留项目根目录 | 小 | ✅ 已完成 |
| 0.3 | 定义 `CompactResult` dataclass 替代裸 dict | 中 | 待实施 |
| 0.4 | `_AllPoolsEnd` 继承 `StopCondition` 基类 | 小 | 待实施 |

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

### Phase 2：统一策略体系 + 信息传入机制（优先级：P1）（v4 重构）

**目标**：消除两套策略体系，引入 `StrategyContext` 统一信息传入，消除全局变量依赖和策略自维护状态

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 2.1 | 定义 `StrategyContext` dataclass | 小 |
| 2.2 | 修改 `Strategy.select_action` 签名为 `select_action(self, ctx: StrategyContext) -> Action` | 中 |
| 2.3 | 将 `_PoolQuotaStrategy`、`_PityReserveStrategy`、`_StopOnTargetStrategy` 迁移到 `core/strategy.py`，继承 `Strategy` | 中 |
| 2.4 | 将 `STRATEGY_REGISTRY` 迁移到 `core/strategy.py` | 小 |
| 2.5 | 修改 `GachaService` 在每次循环中构建 `StrategyContext` 并传入 | 中 |
| 2.6 | 消除策略的 `self.acquired` 和 `self.pool_draw_counts` 自维护 | 中 |
| 2.7 | 消除 `_PityReserveStrategy` 的 O(N²) 保底重放 | 小 |
| 2.8 | 消除 batch 策略对全局变量的依赖 | 中 |
| 2.9 | 删除 `observe()` 方法和 `hasattr(strategy, 'acquired')` 检查 | 小 |
| 2.10 | `batch_simulator.py` 的工厂函数改为从 `core.strategy` 导入 | 小 |

**步骤 2.1 `StrategyContext` 详细设计**：

```python
# core/strategy.py（新增）

@dataclass
class StrategyContext:
    state: GachaState
    current_pools: List[Pool]
    all_pools: List[Pool]
    future_schedules: List[PoolSchedule]
    target_cards: TargetCardSet
    stop_condition: StopCondition
    pity_probabilities: Dict[str, Dict[str, float]]
    acquired: Dict[str, int]
    pool_draw_counts: Dict[str, int]
```

**字段说明**：

| 字段 | 来源 | 说明 |
|------|------|------|
| `state` | `GachaState` | 不变，直接传入 |
| `current_pools` | `GachaService` 过滤 | 不变，当前可用池 |
| `all_pools` | `GachaService._pools_list` | **新增**，替代全局变量 `_wk_pools` 和构造时 `all_pools` |
| `future_schedules` | `ScheduleManager` | 保留，未来策略可能使用 |
| `target_cards` | `GachaService.target_cards` | 保留，消除构造时 `target_set` 重复 |
| `stop_condition` | `GachaService.stop_condition` | 保留，未来策略可能使用 |
| `pity_probabilities` | `PityEngine.before_draw()` | **新增**，由 `GachaService` 在每次循环中计算后传入，消除 O(N²) 重放 |
| `acquired` | `SimulationStats.card_counts` | **新增**，由 `GachaService` 维护并传入，消除策略自维护 |
| `pool_draw_counts` | `SimulationStats.pool_draw_counts` | **新增**，由 `GachaService` 维护并传入，消除策略自维护 |

**步骤 2.2 新 `select_action` 签名**：

```python
class Strategy(ABC):
    lookahead: Optional[float] = None

    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @classmethod
    @abstractmethod
    def description(cls) -> str:
        return ""

    @abstractmethod
    def select_action(self, ctx: StrategyContext) -> Action:
        pass
```

**步骤 2.5 `GachaService` 构建 `StrategyContext`**：

```python
# gacha_service.py 主循环中
for iteration in range(max_iterations):
    if _check(state, history, stats):
        break

    current_pools = [p for p in pools_list
                     if (p.available_from is None or real_time >= p.available_from)
                     and (p.available_until is None or real_time <= p.available_until)]

    future_schedules = []
    if _schedule_mgr and _lookahead:
        future_schedules = _schedule_mgr.get_future_schedules(real_time, _lookahead)

    pity_probabilities = {}
    if _pity_engine:
        for pool in current_pools:
            if not pool.is_exchange:
                probs = {r.id: p for r, p in pool.rewards}
                modified = _pity_engine.before_draw(pool.id, pity_state, probs)
                pity_probabilities[pool.id] = modified

    ctx = StrategyContext(
        state=state,
        current_pools=current_pools,
        all_pools=pools_list,
        future_schedules=future_schedules,
        target_cards=_target_cards,
        stop_condition=_stop,
        pity_probabilities=pity_probabilities,
        acquired=stats.card_counts,
        pool_draw_counts=stats.pool_draw_counts,
    )

    action = _strategy(ctx)
    ...
```

**注意**：保底概率计算从"策略内部重放"变为"GachaService 预计算"。`_pity_engine.before_draw()` 被调用两次（一次在 `StrategyContext` 构建，一次在实际抽卡时），但第二次调用时保底状态未改变（因为 `after_draw` 还没被调用），所以结果相同。未来可优化为缓存，避免重复计算。

**步骤 2.6-2.7 策略迁移示例**：

```python
# core/strategy.py
class SmartStrategy(Strategy):
    lookahead = None

    def __init__(self):
        pass

    @classmethod
    def description(cls) -> str:
        return "按需追卡：优先兑换→按目标追卡→等待下一个池"

    def _pool_needs_target(self, pool_id: str, ctx: StrategyContext) -> bool:
        for t in ctx.target_cards.targets:
            if pool_id in t.pool_ids and ctx.acquired.get(t.card_id, 0) < t.quantity_needed:
                return True
        return False

    def _get_needed_card_exchange(self, ctx: StrategyContext) -> Optional[str]:
        for t in ctx.target_cards.targets:
            if ctx.acquired.get(t.card_id, 0) >= t.quantity_needed:
                continue
            for pool in ctx.all_pools:
                if pool.is_exchange and pool.exchange_card_id == t.card_id:
                    if pool.is_available_at(ctx.state.real_time) and ctx.state.can_afford(pool.cost):
                        return pool.id
        return None

    def select_action(self, ctx: StrategyContext) -> Action:
        exchange_pool_id = self._get_needed_card_exchange(ctx)
        if exchange_pool_id:
            return DrawAction(pool_id=exchange_pool_id)

        for pool in ctx.current_pools:
            if not pool.is_exchange and self._pool_needs_target(pool.id, ctx) and ctx.state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)

        wait_time = 86400
        for pool in ctx.current_pools:
            if hasattr(pool, 'available_until') and pool.available_until and pool.available_until > ctx.state.real_time:
                wait_time = min(wait_time, pool.available_until - ctx.state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)


class PityReserveStrategy(Strategy):
    lookahead = None

    def __init__(self, pity_threshold_pct: float = 80.0):
        self.pity_threshold_pct = pity_threshold_pct / 100.0

    @classmethod
    def description(cls) -> str:
        return "保底预留：只在大保底概率≥阈值时才抽卡"

    def _pool_needs_target(self, pool_id: str, ctx: StrategyContext) -> bool:
        for t in ctx.target_cards.targets:
            if pool_id in t.pool_ids and ctx.acquired.get(t.card_id, 0) < t.quantity_needed:
                return True
        return False

    def select_action(self, ctx: StrategyContext) -> Action:
        for t in ctx.target_cards.targets:
            if ctx.acquired.get(t.card_id, 0) >= t.quantity_needed:
                continue
            for pool in ctx.all_pools:
                if pool.is_exchange and pool.exchange_card_id == t.card_id:
                    if pool.is_available_at(ctx.state.real_time) and ctx.state.can_afford(pool.cost):
                        return DrawAction(pool_id=pool.id)

        for pool in ctx.current_pools:
            if pool.is_exchange or not ctx.state.can_afford(pool.cost):
                continue
            if not self._pool_needs_target(pool.id, ctx):
                continue

            pool_probs = ctx.pity_probabilities.get(pool.id, {})
            ssr_prob = sum(p for cid, p in pool_probs.items() if 'ssr' in cid.lower())
            if ssr_prob >= self.pity_threshold_pct:
                return DrawAction(pool_id=pool.id)

        wait_time = 86400
        for pool in ctx.current_pools:
            if hasattr(pool, 'available_until') and pool.available_until and pool.available_until > ctx.state.real_time:
                wait_time = min(wait_time, pool.available_until - ctx.state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)
```

**关键变化**：
- `SmartStrategy` 不再需要 `target_set` 和 `all_pools` 构造参数——所有信息从 `ctx` 获取
- `PityReserveStrategy` 不再需要 O(N²) 重放——保底概率从 `ctx.pity_probabilities` 直接读取
- 不再需要 `self.acquired`——已获卡计数从 `ctx.acquired` 获取
- 不再需要 `observe()` 方法——`GachaService` 通过 `SimulationStats` 维护所有计数

**步骤 2.8 消除全局变量**：

```python
# gui/batch_simulator.py
from gacha_simulator.core.strategy import (
    SmartStrategy, PoolQuotaStrategy, PityReserveStrategy, StopOnTargetStrategy,
    STRATEGY_REGISTRY
)

def _create_smart_strategy(target_set, params):
    return SmartStrategy()

def _create_pity_reserve_strategy(target_set, params):
    pct = params.get('pity_threshold_pct', 80.0)
    return PityReserveStrategy(pity_threshold_pct=pct)
```

工厂函数不再传入 `_wk_pools`、`_wk_pity_engine` 等全局变量，因为策略不再需要这些构造参数。

**步骤 2.9 删除 `observe()` 和 `hasattr` 检查**：

```python
# gacha_service.py 主循环中，删除以下代码：
# if hasattr(_strategy_obj, 'acquired') and reward.id != _NO_CARD_ID:
#     _strategy_obj.acquired[reward.id] = _strategy_obj.acquired.get(reward.id, 0) + 1

# 改为：SimulationStats.on_draw() 已维护 card_counts，通过 StrategyContext 传入
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
| 5.3 | 保底概率缓存优化：`GachaService` 中 `before_draw` 调用结果缓存，避免重复计算 | 小 |
| 5.4 | compact dict 元数据：记录策略名、版本号、生成时间 | 小 |
| 5.5 | `StrategyContext` 增加 `ssr_ids: Set[str]`，消除 `'ssr' in cid.lower()` 脆弱匹配 | 小 |

---

## 五、重构实施路线图

```
Phase 0 (消除冗余 + Schema)     ──→  Phase 1 (统一模拟核心)
    │                                    │
    │                                    ↓
    └──→  Phase 2 (统一策略体系 + StrategyContext)  ←──  Phase 1 完成
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
- Phase 2 的 `StrategyContext` 设计依赖 Phase 1 的 `SimulationStats` 统一（`acquired` 和 `pool_draw_counts` 的来源）
- Phase 3 依赖 Phase 2（策略迁移后 GDR 判定位置才稳定）
- Phase 4 依赖 Phase 2（ConfigStore 需要统一的策略注册表）
- Phase 5 依赖 Phase 2 + Phase 4

---

## 六、风险应对措施汇总

| 风险 | 严重程度 | 应对 Phase | 关键措施 |
|------|---------|-----------|---------|
| R1: compact dict 无 Schema | 🔴 高 | Phase 0 | 定义 `CompactResult` dataclass |
| R2: 模拟方法代码重复 | 🔴 高 | Phase 1 | Collector 模式统一 |
| R3: 全局变量模式 | 🔴 高 | Phase 2 | `StrategyContext.all_pools` 替代全局变量 |
| R4: 两套策略体系 | 🟡 中 | Phase 2 | 统一继承 `Strategy` 基类 |
| R5: SuccessChecker 不一致 | 🟡 中 | Phase 3 | 全面替换为 `SuccessChecker` |
| R6: GDR 注册无冲突检测 | 🟡 中 | Phase 3 | `register_gdr()` 函数 |
| R7: 两个 worst_impact.py | 🟡 中 | Phase 0 | 删除根目录版本 |
| R8: 两个 docs/ 目录 | 🟢 低 | Phase 0 | ✅ 已合并 |
| R9: _AllPoolsEnd 无基类 | 🟡 中 | Phase 0 | 继承 `StopCondition` |
| R10: 保底状态重建 O(N²) | 🔴 高 | Phase 2 | `StrategyContext.pity_probabilities` 预计算 |
| R11: GUI 面板耦合 MainWindow | 🟡 中 | Phase 4 | 信号/参数注入 |
| R12: ConfigStore 不完整 | 🟡 中 | Phase 4 | 增加 strategy_params |
| R13: 策略信息传入错位 | 🔴 高 | Phase 2 | `StrategyContext` 统一信息传入 |

---

## 七、向后兼容性策略

### 7.1 compact dict 过渡

```python
# gacha_service.py
def run_simulation_compact(self, initial_state, ...) -> Dict[str, Any]:
    result = self.run_simulation(initial_state, collector=CompactCollector(), ...)
    return result.to_dict()  # 过渡期保持 dict 返回

# 未来版本
def run_simulation_compact(self, initial_state, ...) -> CompactResult:
    return self.run_simulation(initial_state, collector=CompactCollector(), ...)
```

### 7.2 select_action 签名过渡

```python
# 过渡期：同时支持旧签名和新签名
class Strategy(ABC):
    @abstractmethod
    def select_action(self, ctx: StrategyContext) -> Action:
        pass

    def select_action_legacy(self, state, history, current_pools,
                              future_schedules, target_cards, stop_condition):
        ctx = StrategyContext(
            state=state, current_pools=current_pools,
            all_pools=current_pools,  # 旧版无 all_pools，降级为 current_pools
            future_schedules=future_schedules,
            target_cards=target_cards, stop_condition=stop_condition,
            pity_probabilities={}, acquired={}, pool_draw_counts={},
        )
        return self.select_action(ctx)
```

### 7.3 ConfigStore 迁移

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

### 7.4 历史模拟结果兼容

所有读取 compact dict 的代码已使用 `.get()` 带默认值。`CompactResult.from_dict()` 会忽略未知字段并补全缺失字段为默认值。

---

## 八、测试策略

### 8.1 重构前必写的回归测试

| 测试 | 覆盖路径 | 优先级 |
|------|---------|--------|
| `test_compact_result_roundtrip` | CompactResult ↔ dict 转换 | P0 |
| `test_simulation_compact_equals_dict` | 新 CompactCollector 输出与旧 dict 输出一致 | P1 |
| `test_strategy_context_fields` | StrategyContext 所有字段正确填充 | P2 |
| `test_all_strategies_inherit_base` | 所有策略类 isinstance(strategy, Strategy) | P2 |
| `test_strategy_registry_complete` | 注册表 key 与工厂函数对应 | P2 |
| `test_smart_strategy_no_state` | SmartStrategy 无 self.acquired，从 ctx 读取 | P2 |
| `test_pity_reserve_no_history_replay` | PityReserveStrategy 不再遍历 history | P2 |
| `test_config_store_migration` | 旧 strategy_type → 新 strategy_name | P4 |
| `test_pool_end_pity_states_chain` | 链式模拟保底状态传递正确性 | P0 |

### 8.2 性能基准测试

| 测试 | 目的 |
|------|------|
| `bench_compact_vs_infovector` | 验证 Collector 模式不引入性能回退 |
| `bench_pity_reserve_before_after` | 对比 PityReserveStrategy 重构前后性能（消除 O(N²)） |
| `bench_pity_probabilities_overhead` | 量化 StrategyContext 中保底概率预计算的额外开销 |

---

## 九、参考文档

- [docs/superpowers/plans/2026-05-13-strategy-comparison-infra.md](file:///workspace/docs/superpowers/plans/2026-05-13-strategy-comparison-infra.md)
- [docs/superpowers/plans/2026-05-13-strategy-comparison.md](file:///workspace/docs/superpowers/plans/2026-05-13-strategy-comparison.md)
- [docs/superpowers/plans/2026-05-13-strategy-comparison-panel.md](file:///workspace/docs/superpowers/plans/2026-05-13-strategy-comparison-panel.md)
- [docs/HANDOVER.md](file:///workspace/docs/HANDOVER.md)

---

## 十、变更追踪

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-05-20 | v1 | 初始版本：策略代码调查 |
| 2026-05-20 | v2 | 第二次更新：反映 worst_impact.py 和 gacha_service.py 变更 |
| 2026-05-20 | v3 | 第三次更新：扩展为项目整体重构方案，新增 12 个风险点、5 个 Phase、CompactResult Schema 设计、Collector 模式设计 |
| 2026-05-20 | v4 | 第四次更新：新增"策略信息传入机制"专题分析（第二章），新增风险 R13，重构 Phase 2 设计引入 `StrategyContext`，消除策略自维护状态和 O(N²) 保底重放，更新路线图和测试策略 |
