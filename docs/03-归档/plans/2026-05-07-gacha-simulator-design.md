# 抽卡模拟器设计文档

## 1. 项目概述

**项目名称**: Gacha Simulator (抽卡模拟器)
**项目类型**: Python GUI 应用程序
**核心功能**: 模拟抽卡过程，支持灵活的策略、资源管理、保底机制，以及详细的统计分析

---

## 2. 技术栈

| 组件 | 技术选型 |
|------|----------|
| 语言 | Python 3.10+ |
| GUI框架 | PyQt6 |
| 数据存储 | SQLite + JSON |
| 可视化 | Matplotlib |
| 架构风格 | 分层架构 + 插件化设计 |

---

## 3. 核心概念

### 3.1 Pool（池子）

抽象池子定义，由以下要素组成：
- 消耗的资源
- 可能的资源获取
- 基础概率分布

商店兑换可视为抽卡的退化版本（概率100%）。

```python
@dataclass
class Reward:
    id: str
    name: str
    resources_gained: Dict[str, float]
    extra_info: Dict[str, Any]

@dataclass
class Pool:
    id: str
    name: str
    cost: Dict[str, float]                    # 每次抽取消耗的资源
    rewards: List[Tuple[Reward, float]]       # (奖励, 概率) 对
    available_from: Optional[float] = None    # 开放起始时间
    available_until: Optional[float] = None   # 开放结束时间
    is_exchange: bool = False                 # 是否为兑换
```

### 3.2 Action（行动）

策略输出的行动类型：

```python
class Action(ABC):
    type: Literal['draw', 'wait']

class DrawAction(Action):
    pool_id: str

class WaitAction(Action):
    duration: float  # 等待的现实时间
```

### 3.3 GachaState（抽卡状态）

```python
@dataclass
class GachaState:
    resources: Dict[str, float]       # 当前资源
    pity_counters: Dict[str, int]    # 保底计数
    real_time: float                  # 现实时间（模型内）
    total_actions: int = 0           # 总行动次数
    extra_state: Dict[str, Any]      # 扩展状态
```

### 3.4 InfoVector（信息向量）

每次行动后生成的信息向量：

```python
@dataclass
class InfoVector:
    action_type: Literal['draw', 'wait']
    card_id: Optional[str]
    pool_id: Optional[str]
    resources_consumed: Dict[str, float]
    resources_gained: Dict[str, float]
    real_time_before: float
    real_time_after: float
    time_elapsed: float
    pity_state: Dict[str, Any]
    action_index: int
    session_id: str
    free_params: Dict[str, Any]
```

### 3.5 PityMechanism（保底机制）

可组合的保底机制：

```python
class PityMechanism(ABC):
    @abstractmethod
    def apply(self, context: GachaContext) -> float: ...

class HardPity(PityMechanism):       # 硬保底
class SoftPity(PityMechanism):       # 软保底
class DualPity(PityMechanism):       # 双重保底
class ResourcePity(PityMechanism):    # 资源保底
class CompositePity(PityMechanism):   # 组合保底
```

### 3.6 Strategy（抽卡策略）

策略接收当前状态和未来信息，输出行动：

```python
class Strategy(ABC):
    lookahead: Optional[float] = None

    @abstractmethod
    def select_action(self,
                      state: GachaState,
                      history: List[InfoVector],
                      current_pools: List[Pool],
                      future_schedules: List[PoolSchedule],
                      target_cards: TargetCardSet,
                      stop_condition: StopCondition) -> Action: ...
```

### 3.7 StopCondition（停止条件）

```python
class StopCondition(ABC):
    @abstractmethod
    def check(self, state: GachaState, history: List[InfoVector]) -> bool: ...

class FixedActionCountCondition(StopCondition):
class ResourceThresholdCondition(StopCondition):
class TargetAcquiredCondition(StopCondition):
class TimeLimitCondition(StopCondition):
```

### 3.8 ResourceGainFunction（资源获取函数）

```python
class ResourceGainFunction(ABC):
    @abstractmethod
    def compute(self, elapsed_time: float, state: GachaState) -> Dict[str, float]: ...

class LinearResourceGain(ResourceGainFunction):
class PeriodicResourceGain(ResourceGainFunction):
```

### 3.9 GeneralizedDropRate（广义出率）

基于完整抽卡历史计算的价值函数：

```python
class GeneralizedDropRate(ABC):
    @abstractmethod
    def compute(self, t: int, history: List[InfoVector]) -> float: ...
```

### 3.10 TargetCard（目标卡）

目标卡可能出现在多个池子中：

```python
@dataclass
class TargetCard:
    card_id: str
    pool_ids: List[str]           # 这张卡可能出现的所有池子
    quantity_needed: int           # 需要抽到多少张
    priority: int = 0

@dataclass
class TargetCardSet:
    targets: List[TargetCard]
```

### 3.11 PoolSchedule（卡池时间表）

```python
@dataclass
class PoolSchedule:
    pool_id: str
    available_from: float
    available_until: float
```

### 3.12 生成器

```python
class PoolScheduleGenerator(ABC):
    def generate(self, config: Dict) -> List[PoolSchedule]: ...

class TargetCardGenerator(ABC):
    def generate(self, future_schedules, pools, preferences) -> TargetCardSet: ...
```

---

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      GUI Layer (PyQt6)                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐│
│  │ 配置面板    │ │ 抽卡界面   │ │ 分析/可视化面板         ││
│  └─────────────┘ └─────────────┘ └─────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      Service Layer                           │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐│
│  │ 抽卡服务    │ │ 分析服务   │ │ 配置管理服务            ││
│  └─────────────┘ └─────────────┘ └─────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      Core Layer                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐ │
│  │ Pool     │ │ Action   │ │ Pity     │ │ Strategy       │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐ │
│  │ State    │ │ InfoVec  │ │ GDR      │ │ StopCondition  │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │ Schedule │ │ Target   │ │ Resource │                    │
│  └──────────┘ └──────────┘ └──────────┘                    │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      Generator Layer                         │
│  ┌─────────────────────┐ ┌────────────────────────────────┐│
│  │ ScheduleGenerator   │ │ TargetCardGenerator            ││
│  └─────────────────────┘ └────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      Data Layer                              │
│  ┌──────────────────────┐ ┌────────────────────────────────┐│
│  │ Config Files (JSON)  │ │ Records (SQLite)               ││
│  └──────────────────────┘ └────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 抽卡流程

```
用户输入初始状态 (GachaState)
    ↓
选择策略 (Strategy) + 停止条件 (StopCondition)
    ↓
选择/生成卡池时间表 (PoolScheduleManager)
    ↓
选择/生成目标卡集合 (TargetCardGenerator)
    ↓
    ↓ 策略可访问:
    │  - 当前可用池子
    │  - 未来卡池安排 (根据lookahead)
    │  - 目标卡集合 (要抽哪些卡，每张几张)
    ↓
循环:
    检查停止条件是否满足?
    ↓ 否
    获取当前时间可用的池子
    ↓
    根据策略的lookahead获取未来卡池安排
    ↓
    策略选择行动 (Action)
    ↓
    执行行动:
        ├─ DrawAction: 扣除资源 → 应用保底 → 抽卡 → 更新保底计数
        └─ WaitAction: 增加现实时间 → 计算资源获取 → 更新资源
    ↓
    更新状态 (GachaState)
    ↓
    生成 InfoVector，加入 history
    ↓
    计算广义出率 (访问完整 history)
    ↓
回到循环开始

是: 结束抽卡，输出完整 history 用于分析
```

---

## 6. 目录结构

```
gacha_simulator/
├── core/                          # 核心模块
│   ├── __init__.py
│   ├── pool.py                    # Pool, Reward 定义
│   ├── action.py                  # Action, DrawAction, WaitAction
│   ├── state.py                   # GachaState
│   ├── pity.py                    # PityMechanism 及其实现
│   ├── strategy.py                # Strategy 及其预设实现
│   ├── stop_condition.py          # StopCondition 及其实现
│   ├── resource_gain.py           # ResourceGainFunction 及其实现
│   ├── generalized_drop_rate.py   # 广义出率基类及预设
│   ├── info_vector.py             # InfoVector
│   ├── schedule.py                # PoolSchedule, PoolScheduleManager
│   └── target_card.py             # TargetCard, TargetCardSet
├── generator/                     # 生成器模块
│   ├── __init__.py
│   ├── schedule_generator.py      # PoolScheduleGenerator 及其实现
│   └── target_generator.py        # TargetCardGenerator 及其实现
├── service/                       # 服务层
│   ├── __init__.py
│   ├── gacha_service.py           # 抽卡服务
│   ├── analysis_service.py        # 分析服务
│   ├── config_service.py          # 配置管理服务
│   └── batch_service.py           # 批量模拟服务
├── gui/                           # GUI层
│   ├── __init__.py
│   ├── main_window.py             # 主窗口
│   ├── config_panel.py            # 配置面板
│   ├── gacha_panel.py             # 抽卡面板
│   └── analysis_panel.py           # 分析面板
├── visualization/                 # 可视化模块
│   ├── __init__.py
│   ├── pmf_plot.py                # PMF图表
│   ├── cdf_plot.py                # CDF图表
│   └── time_series_plot.py         # 时间序列图表
└── main.py                        # 入口文件
```

---

## 7. 插件化设计要点

所有可扩展的组件都遵循以下模式：

1. **基类定义接口**: `ABC` + `@abstractmethod`
2. **预设实现**: 提供常用的默认实现
3. **组合模式**: 支持组合多个机制（如 `CompositePity`）
4. **注册机制**: 通过装饰器或注册表自动发现插件

---

## 8. 配置文件格式

```json
{
  "pools": [...],
  "strategies": [...],
  "pity_mechanisms": [...],
  "resource_gain_functions": [...],
  "generalized_drop_rates": [...],
  "schedules": [...],
  "target_cards": [...]
}
```

---

## 9. 批量模拟与统计分析

统计分析需要进行多次模拟（蒙特卡洛方法）。

### 9.1 模拟变体 (SimulationVariant)

每次模拟的条件可以完全相同，也可以随机变化：

```python
@dataclass
class SimulationVariant:
    name: str                          # 变体名称
    initial_state_fn: Callable[[], GachaState]  # 生成初始状态的函数
    description: str = ""              # 描述
```

### 9.2 条件生成器 (ConditionGenerator)

提供预设的条件生成方式：

- **固定条件**: 所有模拟使用相同的初始条件
- **随机资源**: 初始资源在一定范围内随机
- **蒙特卡洛采样**: 基于基准值添加随机扰动

### 9.3 批量模拟服务 (BatchService)

```python
class BatchService:
    def run_batch(self, variants, config, progress_callback) -> List[BatchSimulationResult]
    def run_parallel(self, variants, config, progress_callback) -> List[BatchSimulationResult]
```

### 9.4 典型使用场景

1. **固定条件模拟**: 评估在特定策略下的期望收益
2. **变体对比**: 对比不同初始条件对结果的影响
3. **敏感度分析**: 随机化某些参数，观察结果分布
