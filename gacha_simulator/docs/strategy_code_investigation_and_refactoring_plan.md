# 策略代码调查与重构方案报告

> 调查日期：2026-05-20
> 基于代码版本：v1.8.0

---

## 一、现状全景图

### 1.1 策略代码的分布位置

策略代码分散在 **5 个模块**中，形成了两套并行的策略体系：

```
gacha_simulator/
├── core/
│   ├── strategy.py          ← 基类 + 通用策略（导出）
│   └── worst_impact.py      ← 专用 _DrawTargetStrategy
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
    └── gacha_service.py     ← 策略执行引擎
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

**4. `_StopOnTargetStrategy`**
- 支持 `stop_on_featured` + `stop_on_any_target` 参数
- 有 `_stopped` 标志位

**共同特点**：
- 都有 `lookahead = None` 静态属性
- 都有 `observe()` 方法（`GachaService` 通过 `hasattr` 调用）
- 都在 `_wk_run_single` 中通过注册表工厂创建
- 都需要访问 `_wk_pools` 全局变量

---

### 2.3 `worst_impact.py` — 专用策略

**文件位置**：[core/worst_impact.py#L84-L113](file:///workspace/gacha_simulator/gacha_simulator/core/worst_impact.py#L84-L113)

```python
class _DrawTargetStrategy(Strategy):
    """最差影响分析：从目标池抽卡"""
    def __init__(self, target_card_ids: Set[str], pool_id: str):
        self.target_card_ids = target_card_ids
        self.pool_id = pool_id
        self.acquired: Dict[str, int] = {}
```

**特点**：
- **继承了 `core/strategy.py` 的 `Strategy` 基类**（这是唯一的！）
- 在链式模拟中直接创建，不经过注册表
- 有 `observe()` 方法
- 只从一个指定池抽卡

---

### 2.4 `gacha_service.py` — 策略执行引擎

**文件位置**：[service/gacha_service.py](file:///workspace/gacha_simulator/gacha_simulator/service/gacha_service.py)

```python
class GachaService:
    def __init__(
        self,
        pools: List[Pool],
        strategy: Strategy,        # ← 接收 Strategy 类型
        stop_condition: StopCondition,
        target_cards: TargetCardSet,
        ...
    ):
        self.strategy = strategy

    def _run_one_step(self, state, history, ...):
        _strategy = self.strategy.select_action  # 绑定方法
        _strategy_obj = self.strategy
        ...
        action = _strategy(state, history, current_pools, ...)
        ...
        if hasattr(_strategy_obj, 'acquired') and reward.id != _NO_CARD_ID:
            _strategy_obj.acquired[reward.id] = _strategy_obj.acquired.get(reward.id, 0) + 1
```

**关键发现**：
- `GachaService` 接收 `Strategy` 类型的参数（基类体系）
- 通过 `hasattr(strategy_obj, 'acquired')` 调用 `observe()` 方法（兼容性设计）

---

### 2.5 `run_batch_parallel` — 批量模拟入口

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
service.run_simulation_compact(state)  # 返回 compact dict
```

---

### 2.6 `ConfigStore` — 配置存储

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
| `gacha_panel.py` | [SimulationThread#L113](file:///workspace/gacha_simulator/gacha_simulator/gui/gacha_panel.py#L113) | 批量模拟面板 |
| `strategy_panel.py` | [_forward_method#L113](file:///workspace/gacha_simulator/gacha_simulator/gui/strategy_panel.py#L113) | 前进法 |
| `strategy_panel.py` | [_backward_method#L173,226](file:///workspace/gacha_simulator/gacha_simulator/gui/strategy_panel.py#L173) | 后退法 |
| `retreat_search.py` | [RetreatSearchWorker#L96](file:///workspace/gacha_simulator/gacha_simulator/core/retreat_search.py#L96) | 退路搜索 |
| `resource_search_panel.py` | [ResourceSearchWorker#L125](file:///workspace/gacha_simulator/gacha_simulator/gui/resource_search_panel.py#L125) | 资源搜索 |

**共 5 处硬编码**。

### 3.2 硬编码策略类型映射

[config_panel.py#L2481-L2482](file:///workspace/gacha_simulator/gacha_simulator/gui/config_panel.py#L2481-L2482)：
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

### 3.4 专用策略未入注册表

`_DrawTargetStrategy`（worst_impact.py）和 `_AllPoolsEnd`（batch_simulator.py）都是：
- 独立定义
- 不通过注册表创建
- 无法被用户选择或配置

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

`_AllPoolsEnd` 是硬编码的，没有类似 `STOP_CONDITION_REGISTRY` 的机制。

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

### 5.6 预估工作量

| 任务 | 优先级 | 工作量 |
|------|--------|--------|
| 迁移策略类到 core/strategy.py | P1 | 中 |
| 统一注册表到 core/ | P1 | 小 |
| ConfigStore 增加 strategy_params | P2 | 小 |
| config_panel 从注册表动态生成 UI | P2 | 中 |
| 移除 5 处硬编码 smart | P2 | 小 |
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

**Phase 3：高级功能（P3）**
8. 实现策略比较面板（已有详细计划文档）
9. 停止条件注册表
10. 策略保存/加载（导出配置包含完整参数）

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
# ConfigStore 中添加
@dataclass
class ConfigStore:
    strategy_type: str = '按需追卡'  # 保留旧字段
    strategy_name: str = 'smart'
    strategy_params: Dict[str, Any] = dc_field(default_factory=dict)
    
    def __post_init__(self):
        # 自动迁移
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

**示例**：
```python
# gui/batch_simulator.py 中
from gacha_simulator.core.strategy import (
    SmartStrategy, PoolQuotaStrategy, PityReserveStrategy, StopOnTargetStrategy
)

def _create_smart_strategy(target_set, params):
    return SmartStrategy(target_set)  # 工厂只负责创建
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

**应对措施**：
1. 确保策略语义完全不变（仅调整代码结构）
2. 在结果元数据中记录生成时的策略名和版本
3. 添加结果兼容性检查，若版本不兼容给出提示

---

## 八、参考文档与计划

- [docs/superpowers/plans/2026-05-13-strategy-comparison-infra.md](file:///workspace/gacha_simulator/docs/superpowers/plans/2026-05-13-strategy-comparison-infra.md)
- [docs/superpowers/plans/2026-05-13-strategy-comparison.md](file:///workspace/gacha_simulator/docs/superpowers/plans/2026-05-13-strategy-comparison.md)
- [docs/superpowers/plans/2026-05-13-strategy-comparison-panel.md](file:///workspace/gacha_simulator/docs/superpowers/plans/2026-05-13-strategy-comparison-panel.md)
