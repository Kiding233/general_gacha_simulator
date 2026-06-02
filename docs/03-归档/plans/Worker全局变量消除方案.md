# 2.8 Worker 全局变量完全消除方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `batch_simulator.py` 中 11 个 `_wk_*` 模块级全局变量合并为 1 个 `_wk_env: SimulationEnv`，简化接口，降低维护成本。

**Architecture:** 采用方案 A1（渐进式）——保留 `multiprocessing.Pool(initializer=_wk_init)` 模式，但 `_wk_init` 只接受 1 个参数（`SimulationEnv`），而非 11 个独立参数。`_wk_run_single()` 从 `_wk_env` 读取所有环境信息。

**Tech Stack:** Python 3.10+, multiprocessing, dataclasses

> 编写日期：2026-05-22 | 修订：v4（2026-05-25：全部完成——单进程路径已消除全局变量污染，160 项测试全部通过）
> 当前状态：**已完成**——11 个全局变量 → 2 个（仅多进程 initializer 使用），单进程路径完全不碰全局变量，`run_batch_parallel` 参数 18→10，6 个调用入口已更新，`SimulationEnv` 字段完备。

---

## 一、现状分析

### 1.1 当前全局变量清单

`service/batch_simulator.py` 中定义了 11 个模块级全局变量：

| 变量名 | 类型 | 默认值 | 用途 |
|--------|------|--------|------|
| `_wk_pools` | list | None | 所有池对象列表 |
| `_wk_schedule_mgr` | PoolScheduleManager | None | 池时间表管理器 |
| `_wk_end_time` | float | None | 模拟结束时间 |
| `_wk_pity_engine` | PityEngine | None | 保底机制引擎 |
| `_wk_resource_gain` | ResourceGain | None | 资源获取计算器 |
| `_wk_pity_state_init` | dict | None | 保底状态初始值 |
| `_wk_card_defs` | list | None | 卡牌定义列表（注意：默认值为 `None`，非 `list`） |
| `_wk_strategy_name` | str | 'smart' | 策略英文键名 |
| `_wk_strategy_params` | dict | {} | 策略参数 |
| `_wk_ssr_ids` | set | set() | SSR卡ID集合 |
| `_wk_stop_condition` | StopCondition | None | 停止条件 |

### 1.2 使用流程

```
主进程                                    子进程
──────                                    ──────
run_batch_parallel(env.*)
  │
  ├─ max_workers <= 1:
  │    _wk_init(env.*)  ──→  _wk_* = env.*
  │    for i in range(N):
  │      _wk_run_single((seed, target_specs, init_res))
  │        └─ 读取 _wk_* 全局变量
  │        └─ create_strategy(_wk_strategy_name, ...)
  │        └─ GachaService(_wk_pools, strategy, ...)
  │
  └─ max_workers > 1:
       MPPool(initializer=_wk_init, initargs=(env.*,))
       mp_pool.imap_unordered(_wk_run_single, tasks)
         └─ 每个子进程内 _wk_* 已被 initializer 设置
         └─ _wk_run_single 读取 _wk_* 全局变量
```

### 1.3 已完成的改进

- ✅ 策略类不再直接访问 `_wk_*` 全局变量（通过 `StrategyContext` 传入所需信息）
- ✅ `create_strategy()` 工厂函数不再需要 `_wk_pools`、`_wk_pity_engine` 等参数
- ✅ `SimulationEnv` 数据类已封装所有环境信息
- ✅ `SimulationEnvBuilder.from_config_store()` 已统一构建环境

### 1.4 仍存在的问题（v3 更新）

1. ✅ **已解决**：~~`_wk_init` + `_wk_*` 全局变量模式~~ → 11 个全局变量已合并为 2 个（`_wk_env` + `_wk_target_set`），`_wk_run_single()` 从 `_wk_env` 读取所有环境信息
2. ⚠️ **仍存在**：**单进程路径污染主进程全局状态**——`max_workers <= 1` 时在主进程调用 `_wk_init(env, target_specs)`，设置 `_wk_env` 和 `_wk_target_set` 全局变量
3. ✅ **已解决**：~~`run_batch_parallel` 参数过多~~ → 参数从 18 个减少到 10 个，`env: SimulationEnv` 替代 9 个独立参数
4. ✅ **已解决**：~~`_wk_run_single` 两种参数传递方式不一致~~ → 静态环境统一通过 `_wk_env` 获取，`args = (seed, initial_resources)` 只传动态参数
5. ✅ **已实现（超出原计划）**：`SimulationEnv` 已包含 `strategy_name`、`strategy_params`、`stop_condition` 字段，`SimulationEnvBuilder.from_dict()` 工厂方法已就绪

---

## 二、消除方案

### 方案 A：SimulationEnv 作为唯一环境载体（推荐）

**核心思路**：将 `SimulationEnv` 作为 `_wk_run_single` 的唯一环境参数来源，消除所有 `_wk_*` 全局变量。

#### 步骤 2.8.1：重构 `_wk_run_single` 接受 `SimulationEnv`

```python
# 修改前
def _wk_run_single(args) -> Optional[Dict[str, Any]]:
    seed, target_specs, initial_resources = args
    # ... 使用 _wk_* 全局变量 ...

# 修改后
def _wk_run_single(args) -> Optional[Dict[str, Any]]:
    seed, target_specs, initial_resources, env = args
    # ... 使用 env.* 替代 _wk_* ...
```

但这里有一个关键问题：**`SimulationEnv` 需要可 pickle 序列化**才能在多进程间传递。

#### 步骤 2.8.2：验证 SimulationEnv 的可序列化性

`SimulationEnv` 的字段中，以下可能有序列化问题：
- `pity_engine`：自定义类，需验证是否可 pickle
- `schedule_mgr`：自定义类，需验证
- `resource_gain`：自定义类，需验证
- `stop_condition`：自定义类，需验证

**如果不可序列化**，有两种子方案：

**子方案 A1**：使用 `initializer` 传入 `SimulationEnv`（保留 initializer 模式，但用单一对象替代 11 个全局变量）

```python
_wk_env = None

def _wk_init(env):
    global _wk_env
    _wk_env = env

def _wk_run_single(args):
    seed, target_specs, initial_resources = args
    env = _wk_env
    # ... 使用 env.* ...
```

优点：避免序列化问题，减少全局变量从 11 个到 1 个
缺点：仍保留全局变量模式（但大幅简化）

**子方案 A2**：使 `SimulationEnv` 可序列化，通过 `args` 传入

```python
def _wk_run_single(args):
    seed, target_specs, initial_resources, env = args
    # ... 使用 env.* ...
```

优点：完全消除全局变量
缺点：每次任务都序列化/反序列化 `SimulationEnv`，有性能开销

#### 步骤 2.8.3：重构 `run_batch_parallel` 接受 `SimulationEnv`

```python
# 修改前
def run_batch_parallel(
    pools, schedule_mgr, end_time, pity_engine,
    resource_gain, pity_state_init, card_defs,
    target_specs, initial_resources, num_simulations,
    max_workers, seed=0, progress_callback=None,
    strategy_name='smart', strategy_params=None,
    on_result=None, ssr_ids=None, stop_condition=None,
) -> List[Optional[Dict[str, Any]]]:

# 修改后
def run_batch_parallel(
    env: SimulationEnv,
    target_specs: Dict[str, int],
    initial_resources: Dict[str, float],
    num_simulations: int,
    max_workers: int = 4,
    seed: int = 0,
    progress_callback: Optional[Callable] = None,
    strategy_name: str = 'smart',
    strategy_params: Optional[dict] = None,
    on_result: Optional[Callable] = None,
) -> List[Optional[Dict[str, Any]]]:
```

参数从 18 个减少到 10 个，其中 `env` 替代了 9 个独立参数（pools, schedule_mgr, end_time, pity_engine, resource_gain, pity_state_init, card_defs, ssr_ids, stop_condition）。注意 `initial_resources` 仍保留为独立参数，因为 `retreat_search.py` 和 `worst_impact.py` 需要在调用时覆盖初始资源值。

#### 步骤 2.8.4：更新所有调用入口

需要更新的文件（6 个，共 9 个调用点）：

| 文件 | 调用点数 | 当前调用方式 | 修改后 |
|------|---------|-------------|--------|
| `gui/gacha_panel.py` | 2 | `run_batch_parallel(pools=env.pools, ...)` | `run_batch_parallel(env=env, ...)` |
| `gui/strategy_panel.py` | 3 | 同上 | 同上 |
| `gui/resource_search_panel.py` | 1 | 同上 | 同上 |
| `gui/strategy_comparison_panel.py` | 1 | 同上 | 同上 |
| `core/worst_impact.py` | 1 | 同上 | 同上 |
| `core/retreat_search.py` | 1 | 同上 | 同上 |

> **注意（2026-05-25）**：`core/worst_impact.py` 的调用参数与其余 5 个文件有两层不同：
> 1. **不使用 `SimulationEnv`**：`worst_impact.py` 通过 `prepare_simulation_config()` 内部构建 `sim_config` 字典（含 `pools`、`schedule_mgr`、`end_time` 等），而非通过 `SimulationEnvBuilder.from_config_store()` 构建 `SimulationEnv`。这意味着重构时 `worst_impact.py` 需要额外步骤——要么从 `sim_config` 构造 `SimulationEnv`，要么保留独立参数路径。
> 2. **策略和参数不同**：`strategy_name='draw_target'`、`strategy_params={'pool_id': ''}`、`max_workers` 动态计算（`os.cpu_count() or 4`）。这不影响重构方案，因为 `strategy_name` 和 `strategy_params` 在方案中仍然保留为 `run_batch_parallel` 的独立参数。
>
> **对方案 A1 的影响**：`worst_impact.py` 需要一个过渡方案。建议在 `SimulationEnvBuilder` 中新增 `from_dict(sim_config)` 工厂方法，或为 `worst_impact.py` 保留一个接受展开参数的内部包装函数。

除 `worst_impact.py` 外，其余 5 个调用入口（8 个调用点）已经先构建 `SimulationEnv`，再展开为独立参数传入。重构后直接传入 `env` 即可。`worst_impact.py` 使用内部 `sim_config` 字典，需额外适配（见上方注意事项）。

#### 步骤 2.8.5：消除单进程路径的全局变量污染

```python
# 修改前
if max_workers <= 1:
    _wk_init(pools, schedule_mgr, ...)  # 污染主进程全局变量
    for i in range(num_simulations):
        result = _wk_run_single((s, target_specs, initial_resources))

# 修改后（子方案 A1）
if max_workers <= 1:
    for i in range(num_simulations):
        result = _run_single_with_env(env, (s, target_specs, initial_resources))

# 修改后（子方案 A2）
if max_workers <= 1:
    for i in range(num_simulations):
        result = _wk_run_single((s, target_specs, initial_resources, env))
```

---

### 方案 B：使用 `concurrent.futures.ProcessPoolExecutor` + 闭包

**核心思路**：用 `ProcessPoolExecutor` 替代 `multiprocessing.Pool`，通过 `initializer` 传入 `SimulationEnv`。

此方案与方案 A 的区别仅在多进程实现层，不影响接口设计。`ProcessPoolExecutor` 的 API 更现代，但 `initializer` 模式相同。

**不推荐**：与方案 A 本质相同，但需要额外适配 `imap_unordered` 的等价功能。

---

### 方案 C：使用 `multiprocessing.shared_memory` 或 `Manager`

**核心思路**：通过共享内存或 Manager 代理传递环境数据。

**不推荐**：
- 共享内存只支持基本类型，自定义对象需要手动序列化
- Manager 代理有性能开销和复杂度
- 对当前场景过度设计

---

## 三、推荐方案：A1（渐进式）

### 3.1 为什么推荐 A1

1. **最小改动量**：将 11 个全局变量合并为 1 个 `_wk_env`，改动集中在 `batch_simulator.py` 内部
2. **无序列化风险**：保留 `initializer` 模式，`SimulationEnv` 不需要跨进程序列化
3. **接口简化**：`run_batch_parallel` 参数从 18 个减少到 10 个
4. **向后兼容**：所有调用入口已使用 `SimulationEnv`，只需改为直接传入
5. **渐进路径**：A1 完成后，如果验证了 `SimulationEnv` 可序列化，可进一步升级到 A2 完全消除全局变量

### 3.2 实施步骤

- [x] **2.8.1: 将 11 个 `_wk_*` 全局变量合并为 2 个（`_wk_env` + `_wk_target_set`）** ✅ 已完成（Phase 1.1）

```python
# 当前状态（Phase 1.1 后）
_wk_env: Optional[SimulationEnv] = None
_wk_target_set = None  # 预构建的 TargetCardSet，避免每次模拟重建
```

> 注：`_wk_target_set` 是 Phase 1.1「预构建不可变数据」优化引入的，在 `_wk_init` 中一次性构建。完全消除需将其也移入 `SimulationEnv` 或通过 args 传递，但收益极小（只省 1 个全局变量），不纳入本方案目标。

- [x] **2.8.2: 重构 `_wk_init()` 接受 `SimulationEnv` 参数** ✅ 已完成

```python
def _wk_init(env: SimulationEnv, target_specs: Dict[str, int] = None):
    global _wk_env, _wk_target_set
    _wk_env = env
    # ... 构建 _wk_target_set ...
```

- [x] **2.8.3: 重构 `_wk_run_single()` 从 `_wk_env` 读取** ✅ 已完成

当前实现从 `_wk_env` 读取 `pools`、`strategy_name`、`strategy_params`、`stop_condition`、`schedule_mgr`、`pity_engine`、`resource_gain`、`ssr_ids`、`card_defs`、`pity_state_init`。

- [x] **2.8.4: 重构 `run_batch_parallel()` 接受 `env: SimulationEnv`** ✅ 已完成

参数已从 18 个减少到 10 个。

- [x] **2.8.5: 更新 6 个调用入口** ✅ 已完成

| 文件 | 状态 |
|------|------|
| `gui/gacha_panel.py` | ✅ `run_batch_parallel(env=env, ...)` |
| `gui/strategy_panel.py` | ✅ 同上 |
| `gui/resource_search_panel.py` | ✅ 同上 |
| `gui/strategy_comparison_panel.py` | ✅ 同上 |
| `core/worst_impact.py` | ✅ 通过 `SimulationEnvBuilder.from_dict(sim_config)` 构造 env |
| `core/retreat_search.py` | ✅ 同上 |

- [x] **2.8.6: 单进程路径不再调用 `_wk_init()`，直接使用 `env`** ✅ 已完成（2026-05-25）

当前单进程路径（`max_workers <= 1`）不再调用 `_wk_init()`，改为直接调用纯函数 `_run_single(env, target_set, seed, initial_resources)`，不碰全局变量。`_wk_run_single` 简化为委托给 `_run_single(_wk_env, _wk_target_set, seed, initial_resources)`。

- [x] **2.8.7: `SimulationEnv` 添加缺失字段** ✅ 已完成

`strategy_name`、`strategy_params`、`stop_condition` 三个字段已加入 `SimulationEnv` dataclass（含默认值），`SimulationEnvBuilder.from_config_store()` 已填充。`SimulationEnvBuilder.from_dict()` 已实现，供 `worst_impact.py` 使用。

- [x] **2.8.8: 运行全部测试确认无回归** ✅ 已完成（2026-05-25）

`pytest tests/ -v` — 160 passed, 2 skipped, 0 failed。

- [x] **2.8.9: 消除单进程路径全局变量 → 提交** ✅ 已完成（2026-05-25）

### 3.3 当前状态 vs 最终目标

方案 2.8.1~2.8.5 及 2.8.7 已通过 Phase 1.1 和项目条目计划实施完成。当前全局变量已从 11 个减少到 2 个：

```python
# 当前状态（Phase 1.1 后）
_wk_env: Optional[SimulationEnv] = None
_wk_target_set = None  # Phase 1.1 预构建优化
```

`run_batch_parallel` 签名已简化为 10 个参数，所有 6 个调用入口已更新。`SimulationEnv` 已包含 `strategy_name`、`strategy_params`、`stop_condition`，`from_dict()` 已就绪。

**剩余唯一待实施项**（2.8.6）：单进程路径消除全局变量污染。

```python
# 当前（max_workers <= 1 路径）
if max_workers <= 1:
    _wk_init(env, target_specs)  # 设置全局变量
    for i in range(num_simulations):
        result = _wk_run_single((s, initial_resources))
    # 全局变量 _wk_env / _wk_target_set 残留在主进程

# 目标：单进程路径直接用局部变量，不设全局状态
if max_workers <= 1:
    # 直接内联 _wk_init 逻辑，或重构 _wk_run_single 接受 env 和 target_set 参数
    target_set = _build_target_set(env, target_specs)
    for i in range(num_simulations):
        result = _run_single(env, target_set, seed, initial_resources)
```

变更量约 15 行，风险极低。

### 3.4 已解决的额外问题（v3 更新）

> ✅ 原标注的三个缺失字段（`strategy_name`、`strategy_params`、`stop_condition`）已全部加入 `SimulationEnv` dataclass，`SimulationEnvBuilder.from_config_store()` 已填充。
> ✅ `SimulationEnvBuilder.from_dict(sim_config)` 工厂方法已实现，`worst_impact.py` 无需额外的展开参数包装函数。
> ✅ `SimulationEnv.card_defs` 与 `_wk_card_defs` 格式一致（`list[dict]`），无需转换。

**`SimulationEnv` 当前字段清单**（v3，共 17 个字段）：

| 字段 | 类型 | 默认值 | 用途 |
|------|------|--------|------|
| `pools` | list | (必填) | 所有池对象 |
| `schedule_mgr` | PoolScheduleManager | (必填) | 池时间表 |
| `end_time` | float | (必填) | 模拟结束时间 |
| `pity_engine` | PityEngine | (必填) | 保底引擎 |
| `resource_gain` | ResourceGain | (必填) | 资源获取 |
| `pity_state_init` | dict | (必填) | 保底初始状态 |
| `card_defs` | list[dict] | (必填) | 卡牌定义 |
| `initial_resources` | dict | (必填) | 初始资源 |
| `target_ids` | set | `set()` | 目标卡ID集合 |
| `ssr_ids` | set | `set()` | SSR卡ID集合 |
| `all_drawable_ids` | list | `[]` | 所有可抽卡ID |
| `pool_end_times` | dict | `{}` | 各池结束时间 |
| `gdr_context` | GDRContext | `None` | GDR上下文 |
| `daily_income` | float | `0.0` | 每日资源收入 |
| `strategy_name` | str | `'smart'` | 策略英文键名 ✅ 新增 |
| `strategy_params` | dict | `{}` | 策略参数 ✅ 新增 |
| `stop_condition` | Any | `None` | 停止条件 ✅ 新增 |

### 3.5 后续升级路径（A1 → A2）⚠ 长期目标，近期不建议

> **审查结论（2026-05-25）**：A1→A2 的 pickle 序列化障碍比原计划预估的更严重。`SimulationEnv` 包含 `PityEngine`、`PoolScheduleManager`、`ResourceGain`（可能是 `ScheduleResourceGain` 或 `CompositeResourceGain`）、`GDRContext` 等自定义对象，这些类的构造函数涉及复杂的内部状态（保底行为对象、资源调度表等），**几乎肯定无法被默认 pickle 序列化**。为这些类实现 `__getstate__`/`__setstate__` 的工作量远超 A1 本身，且收益极小（仅消除最后一个全局变量）。**建议将 A2 标记为长期目标**，完成 A1 后即视为 Worker 消除任务完结。

完成 A1 后，如果未来验证了 `SimulationEnv` 的所有字段均可 pickle 序列化，可以进一步：

1. 将 `_wk_env` 全局变量也消除
2. 改为通过 `args` 传递 `SimulationEnv`
3. 完全消除全局变量模式

验证方法：
```python
import pickle
from gacha_simulator.service.batch_simulator import SimulationEnvBuilder
env = SimulationEnvBuilder.from_config_store(config_store)
pickled = pickle.dumps(env)  # 预期失败：TypeError: cannot pickle 'PityEngine' object
restored = pickle.loads(pickled)
```

如果序列化失败，需要为相关类（`PityEngine`、`PoolScheduleManager`、`ResourceGain` 等）实现 `__getstate__`/`__setstate__` 或使用 `dataclasses` 的默认序列化。

---

## 四、风险评估

| 风险 | 概率 | 影响 | 缓解措施 | 状态 |
|------|------|------|---------|------|
| `SimulationEnv` 字段不可序列化 | 低（A1 不需要） | 无 | A1 保留 initializer 模式 | - |
| 调用入口遗漏更新 | 低 | 中 | 6 个入口已全部核实 | ✅ 已完成 |
| 单进程路径行为变化 | 低 | 低（改动 <15 行） | 保留相同逻辑，仅改变参数来源 | ⚠️ 待实施 |
| ~~`strategy_name`/`strategy_params` 迁移~~ | - | - | 已加入 `SimulationEnv`，`from_config_store()` 已填充 | ✅ 已解决 |
| ~~`worst_impact.py` 不使用 `SimulationEnv`~~ | - | - | `SimulationEnvBuilder.from_dict()` 已实现 | ✅ 已解决 |
| A1→A2 升级路径被 pickle 阻塞 | 高 | 低 | 长期目标，不纳入近期计划 | - |
| 缺少冒烟测试 | 中 | 中 | 当前 zero 测试覆盖 worker 管线，建议至少 1 个 | ⚠️ 待补充 |

---

## 五、总结

### 已完成（v3）

方案 A1 的 9 个步骤中，**7 个已通过 Phase 1.1 和项目条目计划实施完成**：

1. ✅ 将 11 个 `_wk_*` 全局变量合并为 2 个（`_wk_env` + `_wk_target_set`）
2. ✅ `_wk_init()` 接受 `SimulationEnv` + `target_specs`
3. ✅ `_wk_run_single()` 从 `_wk_env` 读取所有环境信息
4. ✅ `run_batch_parallel()` 接受 `env: SimulationEnv`，参数 18→10
5. ✅ 6 个调用入口全部更新（含 `worst_impact.py` via `from_dict()`）
6. ✅ `SimulationEnv` 新增 `strategy_name`、`strategy_params`、`stop_condition`
7. ✅ `SimulationEnvBuilder.from_dict()` 工厂方法

### 剩余工作

**全部完成。** 方案 A1 的 9 个步骤已全部实施完毕，160 项测试全部通过。

---

## 六、审查记录

### 2026-05-25 审查（第3版修订）

**核实范围**：`batch_simulator.py` 全量（161-600行）+ 6 个调用入口实际参数传递方式

**核实结果**：

| 项目 | 计划所述 | 实际状态 | 判定 |
|------|---------|---------|------|
| `_wk_*` 全局变量数量 | 11 | 11 | ✅ 一致 |
| `_wk_init` 参数数量 | 11 | 11 | ✅ 一致 |
| `run_batch_parallel` 参数数量 | 18→11 | 18→10 | ❌ 差 1，已修正 |
| `SimulationEnv` 字段数 | 未明确 | 14（缺 3） | ⚠ 已补充字段清单 |
| 调用入口数 | 6 文件 / 9 调用点 | 6 文件 / 9 调用点 | ✅ 一致 |
| 「所有入口已构建 SimulationEnv」 | 是 | `worst_impact.py` 例外 | ❌ 已修正 |
| A1→A2 pickle 可行性 | 「如果验证」 | 几乎肯定不可行 | ⚠ 已标注长期目标 |
| 测试策略 | 无 | 无 | ⚠ 已补充建议 |

**修订内容**：
1. 参数计数 11→10（3 处）
2. `worst_impact.py` 特殊性说明（不使用 `SimulationEnv`，需 `from_dict` 适配器）
3. `SimulationEnv` 当前 14 字段清单 + 缺失 3 字段的详细说明
4. A1→A2 明确标注为「长期目标，近期不建议」
5. 风险评估表新增 3 个风险项
6. 补充缺少冒烟测试的建议
