# 策略代码调查与重构方案报告

> 调查日期：2026-05-20（第六次更新版）
> 基于代码版本：v1.8.0
> 变更说明：本次更新对计划进行全面审查，发现并修正 7 个问题：compact 模式下 history 为空导致 PityReserve 已失效、acquired 语义差异、_StopOnTargetStrategy 不可变状态缺失、_pool_to_targets 预计算丢失、Phase 依赖矛盾、pity_state 引用安全、过渡代码过时。

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

## 二-B、性能影响分析（v5 新增）

### 2B.1 当前热路径性能特征

`GachaService.run_simulation_compact()` 是批量模拟的热路径，每次模拟可能执行 100-500 次循环迭代，批量模拟通常运行 1000-10000 次。以下是对主循环每次迭代的操作分析：

| 操作 | 时间复杂度 | 当前开销 | 备注 |
|------|-----------|---------|------|
| `stop_condition.check()` | O(1) | 极低 | 简单比较 |
| `current_pools` 列表过滤 | O(P) | 低 | P=池数，通常 2-5 |
| `strategy.select_action()` | O(1)~O(N²) | **关键瓶颈** | PityReserve 为 O(N²)，其余 O(1) |
| `state.spend()` | O(C) | 低 | C=货币种类 |
| `pity_engine.before_draw()` | O(K) | 低 | K=保底规则数 |
| `pool.draw()` | O(log R) | 低 | 二分查找，R=奖励数 |
| `pity_engine.after_draw()` | O(K) | 低 | |
| `dict.append()` 系列 | O(1) | 极低 | compact 模式 |

**关键发现**：除 `_PityReserveStrategy` 外，每次迭代的主要开销是 `before_draw()` + `draw()` + `after_draw()`，约 3-5μs。`_PityReserveStrategy` 的 history 重放使得每次迭代额外增加 O(N) 开销，N 为当前迭代数。

### 2B.2 v4 方案中 `StrategyContext` 的性能问题

v4 方案提出在每次循环迭代中预计算所有池的保底概率：

```python
pity_probabilities = {}
if _pity_engine:
    for pool in current_pools:       # O(P) 个池
        if not pool.is_exchange:
            probs = {r.id: p for r, p in pool.rewards}  # O(R) 构建概率表
            modified = _pity_engine.before_draw(pool.id, pity_state, probs)  # O(K)
            pity_probabilities[pool.id] = modified
```

**问题**：
1. **每次迭代对所有池调用 `before_draw()`**：即使策略只关心 1 个池，也要计算所有池的保底概率。当前代码只在策略选择 DrawAction 后才对选中的池调用 `before_draw()`
2. **概率字典构建开销**：`{r.id: p for r, p in pool.rewards}` 每次迭代都重新创建，但 `pool.rewards` 不变
3. **`StrategyContext` dataclass 构建开销**：每次迭代创建一个 dataclass 实例，包含 9 个字段赋值

**量化估算**（假设 P=3 个池，R=10 个奖励，K=2 个保底规则）：

| 操作 | 当前开销/迭代 | v4 方案开销/迭代 | 增幅 |
|------|-------------|----------------|------|
| `before_draw()` 调用次数 | 1（选中池） | 3（所有非兑换池） | 3x |
| 概率字典构建 | 1 | 3 | 3x |
| `StrategyContext` 构建 | 0 | 1 dataclass | 新增 |
| 策略 `self.acquired` 更新 | 1 dict 操作 | 0（从 ctx 读） | 减少 |
| **净效果** | 基准 | +15-30% | ⚠️ |

### 2B.3 修正方案：惰性计算保底概率

不在每次迭代中预计算所有池的保底概率，而是将 `PityEngine` 和 `PityState` 的引用传入 `StrategyContext`，让策略按需计算：

```python
@dataclass
class StrategyContext:
    state: GachaState
    current_pools: List[Pool]
    all_pools: List[Pool]
    future_schedules: List[PoolSchedule]
    target_cards: TargetCardSet
    stop_condition: StopCondition
    pity_engine: Optional[PityEngine] = None
    pity_state: Optional[PityState] = None
    acquired: Dict[str, int] = field(default_factory=dict)
    pool_draw_counts: Dict[str, int] = field(default_factory=dict)

    def get_pity_probabilities(self, pool_id: str) -> Dict[str, float]:
        if self.pity_engine is None:
            return {}
        pool = next((p for p in self.current_pools if p.id == pool_id), None)
        if pool is None or pool.is_exchange:
            return {}
        probs = {r.id: p for r, p in pool.rewards}
        return self.pity_engine.before_draw(pool_id, self.pity_state, probs)
```

**优势**：
- 只有 `PityReserveStrategy` 调用 `get_pity_probabilities()`，其余策略零开销
- 每次迭代最多计算 1 个池的保底概率（策略只关心当前决策的池）
- `GachaService` 中实际抽卡时的 `before_draw()` 调用不受影响
- 消除了 O(N²) 重放：`PityReserveStrategy` 直接调用 `ctx.get_pity_probabilities(pool.id)` 而非重放 history

**注意**：`get_pity_probabilities()` 的调用结果与 `GachaService` 中实际抽卡时的 `before_draw()` 结果相同（因为 `after_draw` 尚未被调用，pity_state 未变），但会被调用两次。未来可通过缓存优化。

### 2B.4 `GachaService` 中 `before_draw` 双重调用问题

当前流程：
```
策略选择池 → before_draw(修改概率) → draw(抽卡) → after_draw(更新计数器)
```

修正后的流程：
```
策略调用 ctx.get_pity_probabilities(pool_id) → before_draw(只读，不修改池概率)
策略选择池 → before_draw(修改概率) → draw(抽卡) → after_draw(更新计数器)
```

`before_draw()` 被调用两次，但：
1. `PityState` 在两次调用之间未改变（`after_draw` 还没执行）
2. `before_draw()` 是纯函数（只读取 pity_state 计算概率），结果相同
3. 只有 `PityReserveStrategy` 会触发双重调用，其余策略不调用 `get_pity_probabilities()`

**性能影响**：对于 `PityReserveStrategy`，每次迭代多一次 `before_draw()` 调用（约 1-2μs），但消除了 O(N) 的 history 重放（N=当前迭代数，100+ 抽时约 100-500μs）。净效果：**大幅提升性能**。

---

## 二-C、重构范围评估（v5 新增）

### 2C.1 模拟调用链全景

```
GUI 面板                    调用入口                  模拟核心                策略来源
────────                    ────────                  ────────                ────────

gacha_panel.py ────────→ run_batch_parallel() ──→ _wk_run_single() ──→ GachaService.run_simulation_compact()
                          strategy_name='smart'     STRATEGY_REGISTRY       _wk_* 全局变量

batch_simulator.py ────→ run_batch_parallel() ──→ _wk_run_single() ──→ GachaService.run_simulation_compact()
                          strategy_name=用户选择    STRATEGY_REGISTRY       _wk_* 全局变量

strategy_panel.py ─────→ run_batch_parallel() ──→ _wk_run_single() ──→ GachaService.run_simulation_compact()
                          strategy_name='smart'     STRATEGY_REGISTRY       _wk_* 全局变量

resource_search_panel.py → run_batch_parallel() ──→ _wk_run_single() ──→ GachaService.run_simulation_compact()
                          strategy_name='smart'     STRATEGY_REGISTRY       _wk_* 全局变量

retreat_search.py ─────→ run_batch_parallel() ──→ _wk_run_single() ──→ GachaService.run_simulation_compact()
                          strategy_name='smart'     STRATEGY_REGISTRY       _wk_* 全局变量

worst_impact.py ───────→ 直接创建 GachaService ──→ run_simulation_compact()
                          STRATEGY_REGISTRY['smart'] 统一接口    StrategyContext
```

**关键发现**：

1. **所有 GUI 面板都通过 `run_batch_parallel()` 间接调用 `GachaService.run_simulation_compact()`**，无一例外
2. **没有 GUI 面板直接调用 `GachaService.run_simulation()`**（InfoVector 版本）
3. **`run_simulation()`（InfoVector 版本）仅被 `worst_impact.py` 的旧版本使用**（根目录版本已计划删除）
4. **`GachaService` 是唯一的模拟执行引擎**——`run_batch_parallel()` 只是包装层

### 2C.2 是否需要从底层重构？

**结论：是的，必须从底层（GachaService）开始重构。**

理由：

| 层级 | 修改内容 | 能否跳过？ |
|------|---------|-----------|
| **GachaService** | `select_action` 调用方式改为传入 `StrategyContext`；消除 `hasattr(acquired)` 检查；统一 `run_simulation` 和 `run_simulation_compact` | ❌ 不能跳过——这是策略接口的唯一调用点 |
| **Strategy 基类** | `select_action` 签名改为 `select_action(self, ctx)` | ❌ 不能跳过——所有策略的接口定义 |
| **具体策略类** | 适配新签名，消除 `self.acquired`，消除全局变量 | ❌ 不能跳过——否则策略无法工作 |
| **batch_simulator.py** | 适配 `StrategyContext`，消除 `_wk_*` 全局变量 | ❌ 不能跳过——所有 GUI 面板的调用入口 |
| **GUI 面板** | 移除硬编码 `strategy_name='smart'`，适配新接口 | ⚠️ 可以后续做——但硬编码问题会持续 |

**依赖链**：
```
GachaService（底层）→ Strategy 基类 → 具体策略 → batch_simulator → GUI 面板
```

如果只改上层（GUI 面板），底层的问题（信息传入错位、代码重复、全局变量）依然存在，上层改动也无法生效。因此**必须从底层开始**。

### 2C.3 重构是否需要同时修改所有文件？

**不需要一次性修改所有文件，但需要按依赖链顺序推进。**

建议的"原子提交"策略：

**提交 1：底层接口变更（GachaService + Strategy + 具体策略）**
- 修改 `Strategy.select_action` 签名
- 修改 `GachaService` 构建 `StrategyContext`
- 迁移 3 个 batch 策略到 `core/strategy.py`
- 消除 `self.acquired` 和 `observe()`
- **此时 `batch_simulator.py` 和 GUI 面板暂不修改**，通过适配层兼容

**提交 2：中间层适配（batch_simulator.py）**
- 消除 `_wk_*` 全局变量
- 工厂函数改为从 `core.strategy` 导入
- `_AllPoolsEnd` 继承 `StopCondition`

**提交 3：上层清理（GUI 面板）**
- 移除硬编码 `strategy_name='smart'`
- 从 `ConfigStore` 读取策略配置
- 权重获取改为信号/参数注入

这种分步策略确保每个提交都是可编译、可测试的，降低回归风险。

### 2C.4 `run_simulation`（InfoVector 版本）的处理

当前 `run_simulation()` 返回 `List[InfoVector]`，但：
- **无 GUI 面板使用它**
- **仅 `worst_impact.py` 的根目录旧版本使用**（已计划删除）
- **`run_simulation_compact()` 是实际使用的路径**

建议：
1. Phase 1 中不急于删除 `run_simulation()`，而是先实现 Collector 模式
2. 验证 `CompactCollector` 输出与 `run_simulation_compact()` 完全一致后，再替换
3. `InfoVectorCollector` 保留用于调试和可视化场景（如单次模拟的详细步骤展示）

---

## 二-D、计划审查与修正（v6 新增）

> 对 v1-v5 的计划进行全面审查，对照实际代码验证假设，发现并修正以下 7 个问题。

### 问题 I1：`run_simulation_compact` 传入空 history，PityReserve 策略已失效（🔴 严重）

**发现**：[gacha_service.py:252](file:///workspace/gacha_simulator/gacha_simulator/service/gacha_service.py#L252) 中：
```python
action = _strategy(state, [], current_pools, future_schedules, _target_cards, _stop)
```
`run_simulation_compact` 传入 `history=[]`（空列表），而 `_PityReserveStrategy` 的保底重放依赖遍历 history。这意味着 **PityReserve 策略在 compact 模式下根本无法正确计算保底概率**——它每次都从初始保底状态开始计算，相当于忽略所有历史抽卡。

**影响**：当前批量模拟中使用 PityReserve 策略时，保底概率判定是错误的。这不是重构引入的问题，而是现有 bug。

**修正**：Phase 2 的 `StrategyContext.get_pity_probabilities()` 方案直接解决了此问题——它使用 `GachaService` 维护的 `pity_state`（实时更新），而非重放 history。此 bug 的存在反而增强了 Phase 2 的必要性。

**新增风险 R14**：PityReserve 策略在 compact 模式下保底概率计算错误。

---

### 问题 I2：`acquired` 与 `card_counts` 语义不同（🔴 严重）

**发现**：
- 策略的 `self.acquired` 只在 `reward.id != _NO_CARD_ID` 时更新（[gacha_service.py:146-147](file:///workspace/gacha_simulator/gacha_simulator/service/gacha_service.py#L146)）
- `SimulationStats.card_counts` 在 `on_draw()` 中无条件更新，包含 `_NO_CARD_ID`（[gacha_service.py:36-37](file:///workspace/gacha_simulator/gacha_simulator/service/gacha_service.py#L36)）

v5 计划中 `ctx.acquired = stats.card_counts` 会包含 `_no_card` 条目，导致策略误判目标完成度。

**修正**：
1. `SimulationStats.on_draw()` 中增加 `_NO_CARD_ID` 过滤，或
2. `StrategyContext` 中增加 `acquired` 的过滤逻辑，或
3. 新增 `SimulationStats.acquired_counts` 字段，仅统计非 `_NO_CARD_ID` 的卡

推荐方案 3：在 `SimulationStats` 中新增 `acquired_counts` 字段，与 `card_counts` 分离。`card_counts` 保留完整统计（含 `_no_card`），`acquired_counts` 仅统计有效卡牌。

---

### 问题 I3：`_StopOnTargetStrategy` 有不可替代的内部状态（🟡 中等）

**发现**：`_StopOnTargetStrategy` 有 `self._stopped` 状态，在 `observe()` 中根据 `iv.pity_triggered` 设置。这个状态**无法从 `ctx.acquired` 推导**——它取决于"最后一次抽卡是否触发了保底"，这是一个事件而非计数。

v5 计划说"策略变为无状态"，但 `_StopOnTargetStrategy` 需要保留这个状态。

**修正**：`StrategyContext` 需要增加一个字段来传递此信息：

```python
@dataclass
class StrategyContext:
    ...
    last_draw_pity_triggered: bool = False
```

`GachaService` 在每次抽卡后更新此字段。`_StopOnTargetStrategy` 从 `ctx.last_draw_pity_triggered` 读取，不再需要 `self._stopped` 和 `observe()`。

---

### 问题 I4：`SmartStrategy._pool_to_targets` 预计算丢失（🟡 中等）

**发现**：当前 `SmartStrategy.__init__` 在构造时预计算 `_pool_to_targets` 映射（pool_id → targets 列表），使得 `_pool_needs_target()` 查找为 O(1)。

v5 计划将 `SmartStrategy` 改为无构造参数，每次 `select_action` 都从 `ctx.target_cards` 重新遍历构建映射，这是 O(T×P) 的性能回退（T=目标数，P=每个目标的池数）。

**修正**：策略可以保留**不可变的预计算缓存**（从 `target_cards` 推导的映射），只要不维护**可变运行时状态**（如 `acquired`）。具体方案：

```python
class SmartStrategy(Strategy):
    def __init__(self):
        self._pool_to_targets: Dict[str, list] = {}
        self._last_target_cards_id: int = 0

    def _ensure_pool_to_targets(self, ctx: StrategyContext):
        tc_id = id(ctx.target_cards)
        if tc_id != self._last_target_cards_id:
            self._pool_to_targets.clear()
            for t in ctx.target_cards.targets:
                for pid in t.pool_ids:
                    if pid not in self._pool_to_targets:
                        self._pool_to_targets[pid] = []
                    self._pool_to_targets[pid].append(t)
            self._last_target_cards_id = tc_id
```

这样策略仍然是"逻辑上无状态"的——所有决策信息从 `ctx` 获取，缓存只是性能优化，可随时丢弃重建。

---

### 问题 I5：Phase 1 和 Phase 2 依赖关系矛盾（🟡 中等）

**发现**：计划第五章"重构实施路线图"中说"Phase 1 和 Phase 2 可并行"，但同一段又说"Phase 2 的 StrategyContext 设计依赖 Phase 1 的 SimulationStats 统一"。这两句矛盾。

**分析**：实际上 Phase 2 确实依赖 Phase 1：
- `StrategyContext.acquired` 来自 `SimulationStats`，而 `SimulationStats` 在 Phase 1 的 Collector 模式中被统一管理
- 如果先做 Phase 2（不改 GachaService 内部），`acquired` 仍需从 `SimulationStats` 传入，但 `SimulationStats` 在 `run_simulation` 和 `run_simulation_compact` 中的使用方式不同

**修正**：Phase 2 必须在 Phase 1 之后。更新路线图。

---

### 问题 I6：`pity_state` 引用传入的变异风险（🟡 中等）

**发现**：v5 方案将 `pity_state` 以引用传入 `StrategyContext`，策略可以通过 `ctx.get_pity_probabilities()` 调用 `before_draw()`。但 `before_draw()` 虽然不修改 `pity_state`，它是一个"读+计算"操作，不是纯函数——如果未来 `before_draw()` 实现变化引入副作用，策略可能意外修改保底状态。

更严重的是，策略持有 `pity_engine` 和 `pity_state` 的引用，理论上可以调用 `after_draw()` 修改状态。

**修正**：将 `get_pity_probabilities()` 的实现改为只暴露计算结果，不暴露引擎引用：

```python
@dataclass
class StrategyContext:
    ...
    _pity_engine: Optional[PityEngine] = field(default=None, repr=False)
    _pity_state: Optional[PityState] = field(default=None, repr=False)

    def get_pity_probabilities(self, pool_id: str) -> Dict[str, float]:
        if self._pity_engine is None:
            return {}
        pool = next((p for p in self.current_pools if p.id == pool_id), None)
        if pool is None or pool.is_exchange:
            return {}
        probs = {r.id: p for r, p in pool.rewards}
        return self._pity_engine.before_draw(pool_id, self._pity_state, probs)
```

使用下划线前缀表示"内部实现细节，策略不应直接访问"。虽然 Python 无法强制私有化，但这比暴露 `pity_engine` 和 `pity_state` 公共字段更安全。

---

### 问题 I7：过渡代码 `select_action_legacy` 过时（🟢 低）

**发现**：第七章 7.2 节的 `select_action_legacy` 仍使用 v4 的 `pity_probabilities={}` 字段，但 v5 已改为 `pity_engine`/`pity_state`。

**修正**：更新过渡代码。

---

### 问题 I8：`FixedCountStrategy` 使用 `len(history)` 判断抽卡次数（🟡 中等）（v6 新增）

**发现**：`FixedCountStrategy` 在 `select_action` 中使用 `len(history)` 判断已执行抽卡次数。重构后 `select_action` 签名变为 `select_action(self, ctx)`，不再接收 `history` 参数。

**修正**：`StrategyContext` 增加 `total_draws: int = 0` 字段，`FixedCountStrategy` 改用 `ctx.total_draws`。

---

### 修正汇总

| 问题 | 严重程度 | 影响的 Phase | 修正措施 |
|------|---------|-------------|---------|
| I1: PityReserve compact 模式已失效 | 🔴 严重 | Phase 2 | `get_pity_probabilities()` 直接解决；新增 R14 |
| I2: acquired 含 _no_card | 🔴 严重 | Phase 2 | `SimulationStats` 新增 `acquired_counts` |
| I3: _StopOnTarget 不可变状态 | 🟡 中等 | Phase 2 | `StrategyContext` 增加 `last_draw_pity_triggered` |
| I4: _pool_to_targets 预计算丢失 | 🟡 中等 | Phase 2 | 策略保留不可变缓存，按需重建 |
| I5: Phase 1/2 依赖矛盾 | 🟡 中等 | 路线图 | Phase 2 必须在 Phase 1 之后 |
| I6: pity_state 引用安全 | 🟡 中等 | Phase 2 | 字段改为下划线前缀，只暴露方法 |
| I7: 过渡代码过时 | 🟢 低 | 第七章 | 更新代码 |
| I8: FixedCountStrategy 用 len(history) | 🟡 中等 | Phase 2 | `StrategyContext` 增加 `total_draws` |

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
    _pity_engine: Optional[PityEngine] = field(default=None, repr=False)
    _pity_state: Optional[PityState] = field(default=None, repr=False)
    acquired: Dict[str, int] = field(default_factory=dict)
    pool_draw_counts: Dict[str, int] = field(default_factory=dict)
    total_draws: int = 0
    last_draw_pity_triggered: bool = False

    def get_pity_probabilities(self, pool_id: str) -> Dict[str, float]:
        if self._pity_engine is None:
            return {}
        pool = next((p for p in self.current_pools if p.id == pool_id), None)
        if pool is None or pool.is_exchange:
            return {}
        probs = {r.id: p for r, p in pool.rewards}
        return self._pity_engine.before_draw(pool_id, self._pity_state, probs)
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
| `_pity_engine` | `GachaService.pity_engine` | **新增**，惰性计算保底概率，下划线前缀防止策略直接调用 `after_draw()` |
| `_pity_state` | `GachaService.pity_state` | **新增**，配合 pity_engine 使用，下划线前缀保护 |
| `acquired` | `SimulationStats.acquired_counts` | **新增**，仅统计非 `_NO_CARD_ID` 的有效卡牌（修正 I2） |
| `pool_draw_counts` | `SimulationStats.pool_draw_counts` | **新增**，由 `GachaService` 维护并传入 |
| `total_draws` | `SimulationStats.total_draws` | **新增**（修正 I8），当前模拟已执行的总抽卡次数，替代 `len(history)` |
| `last_draw_pity_triggered` | `GachaService` 上一次抽卡结果 | **新增**（修正 I3），供 `_StopOnTargetStrategy` 使用 |

**性能设计要点**：
- `_pity_engine` 和 `_pity_state` 以引用传入，不预计算保底概率
- `get_pity_probabilities()` 是惰性方法，只有 `PityReserveStrategy` 调用时才计算
- 其余策略零额外开销，`StrategyContext` 构建成本仅为字段赋值
- 下划线前缀防止策略直接修改保底状态（修正 I6）

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

**步骤 2.4 `STRATEGY_REGISTRY` 迁移与扩展**：

```python
# core/strategy.py
STRATEGY_REGISTRY = {
    'smart': {
        'display_name': '按需追卡',
        'description': '优先兑换→按目标追卡→等待下一个池',
        'class': SmartStrategy,
        'params': {},
    },
    'pool_quota': {
        'display_name': '指定池配额',
        'description': '在指定池子抽指定数量后切换',
        'class': PoolQuotaStrategy,
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
        'class': PityReserveStrategy,
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
        'class': StopOnTargetStrategy,
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
    'target_hunting': {
        'display_name': '指定池追卡',
        'description': '只从指定池子抽卡',
        'class': TargetHuntingStrategy,
        'params': {
            'target_pool_ids': {
                'type': 'string_list',
                'display_name': '目标池ID列表',
                'default': [],
            },
        },
    },
    'fixed_count': {
        'display_name': '固定次数',
        'description': '抽指定次数后停止',
        'class': FixedCountStrategy,
        'params': {
            'count': {
                'type': 'int',
                'display_name': '抽卡次数',
                'default': 100,
                'min': 1,
            },
        },
    },
}
```

**与当前 `STRATEGY_REGISTRY` 的差异**：

| 策略 | 当前 batch_simulator.py | 重构后 core/strategy.py | 变化 |
|------|------------------------|------------------------|------|
| `smart` | ✅ 有 | ✅ 保留 | 类从 core 导入 |
| `pool_quota` | ✅ 有 | ✅ 迁移 | 从 batch_simulator 迁入 |
| `pity_reserve` | ✅ 有 | ✅ 迁移 | 从 batch_simulator 迁入 |
| `stop_on_target` | ✅ 有 | ✅ 迁移 | 从 batch_simulator 迁入 |
| `target_hunting` | ❌ 无（core/strategy.py 有类但无注册） | ✅ **新增注册** | 之前无法通过注册表使用 |
| `fixed_count` | ❌ 无（core/strategy.py 有类但无注册） | ✅ **新增注册** | 之前无法通过注册表使用 |
| `composite` | ❌ 无 | ❌ 不注册 | 组合策略，由代码内部使用 |

**关键改进**：`TargetHuntingStrategy` 和 `FixedCountStrategy` 之前虽然存在于 `core/strategy.py`，但未注册到 `STRATEGY_REGISTRY`，无法被 GUI 面板选择使用。重构后统一注册，所有策略都可选择。`params` 从简单列表升级为带类型、默认值、显示名的结构化定义，支持 Phase 4 的 UI 动态生成。

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

    ctx = StrategyContext(
        state=state,
        current_pools=current_pools,
        all_pools=pools_list,
        future_schedules=future_schedules,
        target_cards=_target_cards,
        stop_condition=_stop,
        _pity_engine=_pity_engine,
        _pity_state=pity_state,
        acquired=stats.acquired_counts,
        pool_draw_counts=stats.pool_draw_counts,
        total_draws=stats.total_draws,
        last_draw_pity_triggered=last_pity_triggered,
    )

    action = _strategy(ctx)
    ...
```

**注意**：`_pity_engine` 和 `_pity_state` 以引用传入 `StrategyContext`，不预计算保底概率。只有策略调用 `ctx.get_pity_probabilities()` 时才触发 `before_draw()` 计算。`GachaService` 中实际抽卡时的 `before_draw()` 调用不受影响——两次调用之间 `pity_state` 未改变，结果相同。`stats.acquired_counts` 仅统计非 `_NO_CARD_ID` 的有效卡牌（修正 I2）。`last_draw_pity_triggered` 在每次抽卡后更新（修正 I3）。

**步骤 2.6-2.7 策略迁移示例**：

```python
# core/strategy.py
class SmartStrategy(Strategy):
    lookahead = None

    def __init__(self):
        self._pool_to_targets: Dict[str, list] = {}
        self._last_target_cards_id: int = 0

    @classmethod
    def description(cls) -> str:
        return "按需追卡：优先兑换→按目标追卡→等待下一个池"

    def _ensure_pool_to_targets(self, ctx: StrategyContext):
        tc_id = id(ctx.target_cards)
        if tc_id != self._last_target_cards_id:
            self._pool_to_targets.clear()
            for t in ctx.target_cards.targets:
                for pid in t.pool_ids:
                    if pid not in self._pool_to_targets:
                        self._pool_to_targets[pid] = []
                    self._pool_to_targets[pid].append(t)
            self._last_target_cards_id = tc_id

    def _pool_needs_target(self, pool_id: str, ctx: StrategyContext) -> bool:
        self._ensure_pool_to_targets(ctx)
        for t in self._pool_to_targets.get(pool_id, []):
            if ctx.acquired.get(t.card_id, 0) < t.quantity_needed:
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

            pool_probs = ctx.get_pity_probabilities(pool.id)
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
- `SmartStrategy` 不再需要 `target_set` 和 `all_pools` 构造参数——所有决策信息从 `ctx` 获取
- `SmartStrategy` 保留 `_pool_to_targets` 不可变缓存（修正 I4），按需重建，不影响逻辑无状态性
- `PityReserveStrategy` 不再需要 O(N²) 重放——保底概率从 `ctx.get_pity_probabilities()` 直接读取
- 不再需要 `self.acquired`——已获卡计数从 `ctx.acquired` 获取（`stats.acquired_counts`，修正 I2）
- 不再需要 `observe()` 方法——`GachaService` 通过 `SimulationStats` 维护所有计数
- `_StopOnTargetStrategy` 从 `ctx.last_draw_pity_triggered` 获取保底触发事件（修正 I3）

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

**目标**：所有 GUI 面板从统一注册表选择策略，消除硬编码

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| 4.1 | `ConfigStore` 增加 `strategy_name: str` 和 `strategy_params: Dict` | 小 |
| 4.2 | 添加旧字段迁移逻辑（`strategy_type` → `strategy_name`，中文→英文 key） | 小 |
| 4.3 | `config_panel.py` 从 `STRATEGY_REGISTRY` 动态生成策略下拉框 | 中 |
| 4.4 | 策略参数配置区根据 `params` 定义动态生成控件（int→QSpinBox, float→QDoubleSpinBox, bool→QCheckBox, pool_int_map→自定义控件） | 中 |
| 4.5 | 移除 4 处硬编码 `strategy_name='smart'`（gacha_panel、strategy_panel、resource_search_panel、retreat_search_panel），改用 ConfigStore 值 | 小 |
| 4.6 | GUI 面板权重获取改为通过 `set_store()` / 信号，而非 `self.window()` | 中 |
| 4.7 | `worst_impact.py` 使用统一策略调用接口，固定选择特制策略（不从 ConfigStore 读取用户配置） | 小 |

**步骤 4.2 旧字段迁移**：

```python
OLD_TO_NEW = {
    "按需追卡": "smart",
    "指定池抽卡": "target_hunting",
    "指定池配额": "pool_quota",
    "保底预留": "pity_reserve",
    "目标即停": "stop_on_target",
    "固定次数": "fixed_count",
}
```

**步骤 4.3 动态生成策略下拉框**：

当前 `config_panel.py` 硬编码了 2 个选项：
```python
self.strategy_type.addItems(["按需追卡", "指定池抽卡"])
```

重构后从注册表动态生成：
```python
from gacha_simulator.core.strategy import STRATEGY_REGISTRY

items = []
self._strategy_keys = []
for key, defn in STRATEGY_REGISTRY.items():
    items.append(defn['display_name'])
    self._strategy_keys.append(key)
self.strategy_type.addItems(items)
```

**步骤 4.7 `worst_impact.py` 使用统一策略调用接口，固定选择特制策略**：

`worst_impact.py` 构建虚拟池环境（`_worst_impact_pool_0` 等），需要配合这些虚拟池使用特定策略。重构后 `worst_impact.py` **仍然使用统一的策略调用接口**——通过 `STRATEGY_REGISTRY` 创建策略实例，通过 `StrategyContext` 传入信息，调用 `select_action(ctx)` ——只是它**固定选择特定策略**（如 `smart`），而非从 `ConfigStore` 读取用户配置的策略。这是因为虚拟池环境需要与之配合的特定策略逻辑，而非用户面向的通用策略选择。

```python
# worst_impact.py 重构后的策略创建方式
from gacha_simulator.core.strategy import STRATEGY_REGISTRY

def _create_worst_impact_strategy():
    strategy_def = STRATEGY_REGISTRY['smart']
    return strategy_def['class']()  # 统一接口，固定选择 smart 策略
```

同理，`worst_impact_panel.py` 也不需要策略选择下拉框——它的策略由分析逻辑内部决定，但调用方式与其他面板完全一致。

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
Phase 0 (消除冗余 + Schema) ──→  Phase 1 (统一模拟核心) ──→  Phase 2 (统一策略体系 + StrategyContext)
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
- Phase 1 必须在 Phase 2 之前（修正 I5）：`StrategyContext.acquired` 来自 `SimulationStats.acquired_counts`，而 `SimulationStats` 在 Phase 1 的 Collector 模式中被统一管理
- Phase 0 是 Phase 1 和 Phase 2 的共同前置依赖
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
| R10: 保底状态重建 O(N²) | 🔴 高 | Phase 2 | `StrategyContext.get_pity_probabilities()` 惰性计算 |
| R11: GUI 面板耦合 MainWindow | 🟡 中 | Phase 4 | 信号/参数注入 |
| R12: ConfigStore 不完整 | 🟡 中 | Phase 4 | 增加 strategy_params |
| R13: 策略信息传入错位 | 🔴 高 | Phase 2 | `StrategyContext` 统一信息传入 |
| R14: PityReserve compact 模式保底概率错误 | 🔴 高 | Phase 2 | `get_pity_probabilities()` 使用实时 pity_state（修正 I1） |

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
                              future_schedules, target_cards, stop_condition,
                              pity_engine=None, pity_state=None,
                              acquired=None, pool_draw_counts=None,
                              total_draws=0,
                              last_draw_pity_triggered=False):
        ctx = StrategyContext(
            state=state, current_pools=current_pools,
            all_pools=current_pools,
            future_schedules=future_schedules,
            target_cards=target_cards, stop_condition=stop_condition,
            _pity_engine=pity_engine, _pity_state=pity_state,
            acquired=acquired or {},
            pool_draw_counts=pool_draw_counts or {},
            total_draws=total_draws,
            last_draw_pity_triggered=last_draw_pity_triggered,
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
| `test_pity_reserve_compact_mode_correct` | PityReserve 在 compact 模式下保底概率正确（验证 R14 修复） | P2 |
| `test_acquired_excludes_no_card` | ctx.acquired 不含 `_no_card` 条目（验证 I2 修正） | P2 |
| `test_stop_on_target_uses_ctx` | _StopOnTargetStrategy 从 ctx.last_draw_pity_triggered 读取（验证 I3 修正） | P2 |
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
| 2026-05-20 | v5 | 第五次更新：新增"性能影响分析"（二-B）和"重构范围评估"（二-C）两个专题；修正 Phase 2 保底概率方案从预计算改为惰性计算（`get_pity_probabilities()`）；论证必须从底层（GachaService）开始重构；提出三步原子提交策略 |
| 2026-05-20 | v6 | 第六次更新：全面审查发现并修正 8 个问题（二-D）——I1: PityReserve compact 模式已失效（新增 R14）、I2: acquired 含 _no_card（新增 acquired_counts）、I3: _StopOnTarget 不可变状态（新增 last_draw_pity_triggered）、I4: _pool_to_targets 预计算丢失（保留不可变缓存）、I5: Phase 1/2 依赖矛盾（修正路线图）、I6: pity_state 引用安全（下划线前缀）、I7: 过渡代码过时（更新）、I8: FixedCountStrategy 用 len(history)（新增 total_draws） |
| 2026-05-20 | v6.1 | 修正 worst_impact.py 策略调用方式：使用统一策略调用接口（STRATEGY_REGISTRY + StrategyContext + select_action(ctx)），固定选择特制策略而非从 ConfigStore 读取用户配置；更新调用链全景图 |
| 2026-05-20 | v7 | Phase 5 全部完成：5.4 compact 元数据（strategy_name/result_version/generated_at）、5.3 保底概率缓存（StrategyContext._pity_cache）、5.2 停止条件注册表（STOP_CONDITION_REGISTRY + create_stop_condition + AllPoolsEndCondition + ConfigStore.stop_condition_type/params）、5.1 策略比较面板（StrategyComparisonPanel）、5.5 ssr_ids（Phase 2 已完成） |
