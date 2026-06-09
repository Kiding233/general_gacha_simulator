# 抽卡模拟器实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个完整的抽卡模拟器，支持灵活的策略、资源管理、保底机制、可视化分析

**Architecture:** 分层架构 + 插件化设计，核心层定义抽象接口，预设实现通过插件提供，服务层编排业务逻辑，GUI层提供交互界面

**Tech Stack:** Python 3.10+, PyQt6, SQLite, JSON, Matplotlib

---

## 文件结构

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
│   └── config_service.py          # 配置管理服务
├── gui/                           # GUI层
│   ├── __init__.py
│   ├── main_window.py             # 主窗口
│   ├── config_panel.py            # 配置面板
│   ├── gacha_panel.py             # 抽卡面板
│   └── analysis_panel.py          # 分析面板
├── visualization/                 # 可视化模块
│   ├── __init__.py
│   ├── pmf_plot.py                # PMF图表
│   ├── cdf_plot.py                # CDF图表
│   └── time_series_plot.py        # 时间序列图表
├── data/                          # 数据层
│   ├── __init__.py
│   └── records.db                 # SQLite数据库
└── main.py                        # 入口文件
```

---

## Phase 1: 核心数据模型

### Task 1: 基础数据结构和枚举

**Files:**
- Create: `gacha_simulator/core/__init__.py`
- Create: `gacha_simulator/core/pool.py`
- Create: `gacha_simulator/core/action.py`
- Create: `gacha_simulator/core/state.py`
- Create: `gacha_simulator/core/info_vector.py`
- Test: `tests/core/test_pool.py`
- Test: `tests/core/test_action.py`
- Test: `tests/core/test_state.py`

- [ ] **Step 1: 创建 core/__init__.py**

```python
from .pool import Pool, Reward
from .action import Action, DrawAction, WaitAction
from .state import GachaState
from .info_vector import InfoVector

__all__ = [
    'Pool', 'Reward',
    'Action', 'DrawAction', 'WaitAction',
    'GachaState',
    'InfoVector',
]
```

- [ ] **Step 2: 创建 core/pool.py**

```python
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any
import random


@dataclass
class Reward:
    id: str
    name: str
    resources_gained: Dict[str, float] = field(default_factory=dict)
    extra_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Pool:
    id: str
    name: str
    cost: Dict[str, float]  # {resource_name: amount}
    rewards: List[Tuple[Reward, float]]  # [(reward, probability), ...]
    available_from: Optional[float] = None
    available_until: Optional[float] = None
    is_exchange: bool = False

    def draw(self) -> Reward:
        if self.is_exchange:
            if not self.rewards:
                raise ValueError(f"Exchange pool {self.id} has no rewards")
            return self.rewards[0][0]
        weights = [prob for _, prob in self.rewards]
        if not weights or sum(weights) == 0:
            raise ValueError(f"Pool {self.id} has no valid rewards")
        result = random.choices([r for r, _ in self.rewards], weights=weights)[0]
        return result

    def is_available_at(self, time: float) -> bool:
        if self.available_from is not None and time < self.available_from:
            return False
        if self.available_until is not None and time > self.available_until:
            return False
        return True
```

- [ ] **Step 3: 创建 core/action.py**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, Optional


class Action(ABC):
    type: Literal['draw', 'wait']

    @abstractmethod
    def __repr__(self) -> str:
        pass


@dataclass
class DrawAction(Action):
    type: Literal['draw'] = 'draw'
    pool_id: str

    def __repr__(self) -> str:
        return f"DrawAction(pool_id='{self.pool_id}')"


@dataclass
class WaitAction(Action):
    type: Literal['wait'] = 'wait'
    duration: float

    def __repr__(self) -> str:
        return f"WaitAction(duration={self.duration})"
```

- [ ] **Step 4: 创建 core/state.py**

```python
from dataclasses import dataclass, field
from typing import Dict, Any, List
from .pool import Pool


@dataclass
class GachaState:
    resources: Dict[str, float] = field(default_factory=dict)
    pity_counters: Dict[str, int] = field(default_factory=dict)
    real_time: float = 0.0
    total_actions: int = 0
    extra_state: Dict[str, Any] = field(default_factory=dict)

    def can_afford(self, cost: Dict[str, float]) -> bool:
        for resource, amount in cost.items():
            if self.resources.get(resource, 0) < amount:
                return False
        return True

    def spend(self, cost: Dict[str, float]) -> None:
        for resource, amount in cost.items():
            if resource in self.resources:
                self.resources[resource] -= amount

    def gain(self, gains: Dict[str, float]) -> None:
        for resource, amount in gains.items():
            self.resources[resource] = self.resources.get(resource, 0) + amount

    def get_available_pools(self, pools: List[Pool]) -> List[Pool]:
        return [pool for pool in pools if pool.is_available_at(self.real_time)]

    def clone(self) -> 'GachaState':
        return GachaState(
            resources=self.resources.copy(),
            pity_counters=self.pity_counters.copy(),
            real_time=self.real_time,
            total_actions=self.total_actions,
            extra_state=self.extra_state.copy(),
        )
```

- [ ] **Step 5: 创建 core/info_vector.py**

```python
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Literal


@dataclass
class InfoVector:
    action_type: Literal['draw', 'wait']
    card_id: Optional[str]
    pool_id: Optional[str]
    resources_consumed: Dict[str, float] = field(default_factory=dict)
    resources_gained: Dict[str, float] = field(default_factory=dict)
    real_time_before: float = 0.0
    real_time_after: float = 0.0
    time_elapsed: float = 0.0
    pity_state: Dict[str, Any] = field(default_factory=dict)
    action_index: int = 0
    session_id: str = ''
    free_params: Dict[str, Any] = field(default_factory=dict)

    @property
    def time_delta(self) -> float:
        return self.real_time_after - self.real_time_before
```

- [ ] **Step 6: 创建测试 tests/core/test_pool.py**

```python
import pytest
from gacha_simulator.core.pool import Pool, Reward


def test_pool_draw_returns_reward():
    r1 = Reward(id='r1', name='Reward 1')
    r2 = Reward(id='r2', name='Reward 2')
    pool = Pool(
        id='test_pool',
        name='Test Pool',
        cost={'primogem': 160},
        rewards=[(r1, 0.6), (r2, 0.4)],
    )
    result = pool.draw()
    assert result in [r1, r2]


def test_exchange_pool_returns_first_reward():
    r = Reward(id='exchange', name='Exchange')
    pool = Pool(
        id='exchange_pool',
        name='Exchange Pool',
        cost={'stardust': 75},
        rewards=[(r, 1.0)],
        is_exchange=True,
    )
    result = pool.draw()
    assert result == r


def test_pool_availability():
    pool = Pool(
        id='limited_pool',
        name='Limited Pool',
        cost={'primogem': 160},
        rewards=[],
        available_from=0,
        available_until=100,
    )
    assert pool.is_available_at(50) is True
    assert pool.is_available_at(150) is False
    assert pool.is_available_at(-10) is False
```

- [ ] **Step 7: 创建测试 tests/core/test_action.py**

```python
import pytest
from gacha_simulator.core.action import Action, DrawAction, WaitAction


def test_draw_action_repr():
    action = DrawAction(pool_id='standard')
    assert "DrawAction" in repr(action)
    assert "standard" in repr(action)


def test_wait_action_repr():
    action = WaitAction(duration=3600)
    assert "WaitAction" in repr(action)
    assert "3600" in repr(action)


def test_action_type():
    draw = DrawAction(pool_id='test')
    wait = WaitAction(duration=100)
    assert draw.type == 'draw'
    assert wait.type == 'wait'
```

- [ ] **Step 8: 创建测试 tests/core/test_state.py**

```python
import pytest
from gacha_simulator.core.state import GachaState
from gacha_simulator.core.pool import Pool, Reward


def test_can_afford():
    state = GachaState(resources={'primogem': 160, 'acronym': 0})
    assert state.can_afford({'primogem': 160}) is True
    assert state.can_afford({'primogem': 161}) is False
    assert state.can_afford({'acronym': 1}) is False


def test_spend_and_gain():
    state = GachaState(resources={'primogem': 1000})
    state.spend({'primogem': 160})
    assert state.resources['primogem'] == 840
    state.gain({'primogem': 100})
    assert state.resources['primogem'] == 940


def test_get_available_pools():
    pool1 = Pool('p1', 'Pool 1', {}, [], available_from=0, available_until=100)
    pool2 = Pool('p2', 'Pool 2', {}, [], available_from=50, available_until=200)
    state = GachaState(real_time=75)
    available = state.get_available_pools([pool1, pool2])
    assert len(available) == 1
    assert available[0].id == 'p2'


def test_clone():
    state = GachaState(resources={'a': 1}, pity_counters={'p1': 5}, real_time=100)
    clone = state.clone()
    assert clone.resources == {'a': 1}
    assert clone.pity_counters == {'p1': 5}
    assert clone.real_time == 100
    clone.resources['a'] = 999
    assert state.resources['a'] == 1
```

- [ ] **Step 9: 运行测试验证**

Run: `cd /workspace && python -m pytest tests/core/ -v`

Expected: 所有测试通过

---

### Task 2: 保底机制 (Pity Mechanism)

**Files:**
- Create: `gacha_simulator/core/pity.py`
- Test: `tests/core/test_pity.py`

- [ ] **Step 1: 创建 core/pity.py**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class GachaContext:
    pool_id: str
    base_probabilities: Dict[str, float]
    pity_counters: Dict[str, int]
    total_draws: int
    extra_data: Dict[str, Any] = field(default_factory=dict)


class PityMechanism(ABC):
    @abstractmethod
    def apply(self, context: GachaContext) -> Dict[str, float]:
        """返回调整后的概率分布"""
        pass


class HardPity(PityMechanism):
    """硬保底：第N抽必出指定稀有度"""

    def __init__(self, counter_name: str, threshold: int, target_probability: float = 1.0):
        self.counter_name = counter_name
        self.threshold = threshold
        self.target_probability = target_probability

    def apply(self, context: GachaContext) -> Dict[str, float]:
        adjusted = context.base_probabilities.copy()
        current_count = context.pity_counters.get(self.counter_name, 0)
        if current_count >= self.threshold:
            adjusted = {k: v * (1 - self.target_probability) for k, v in adjusted.items()}
            adjusted['pity_trigger'] = self.target_probability
        return adjusted


class SoftPity(PityMechanism):
    """软保底：从第M抽开始概率递增"""

    def __init__(self, counter_name: str, start_at: int, increment_per_pull: float = 0.01):
        self.counter_name = counter_name
        self.start_at = start_at
        self.increment_per_pull = increment_per_pull

    def apply(self, context: GachaContext) -> Dict[str, float]:
        adjusted = context.base_probabilities.copy()
        current_count = context.pity_counters.get(self.counter_name, 0)
        if current_count >= self.start_at:
            increment = (current_count - self.start_at) * self.increment_per_pull
            bonus = min(increment, 0.5)
            total = sum(adjusted.values())
            for k in adjusted:
                adjusted[k] = adjusted[k] / total * (1 + bonus) if total > 0 else 0
        return adjusted


class DualPity(PityMechanism):
    """双重保底：小保底+大保底"""

    def __init__(self, small_pity: HardPity, guaranteed_target: str):
        self.small_pity = small_pity
        self.guaranteed_target = guaranteed_target
        self.last_was_guaranteed = False

    def apply(self, context: GachaContext) -> Dict[str, float]:
        result = self.small_pity.apply(context)
        if self.last_was_guaranteed:
            result = {k: 0 for k in result}
            result[self.guaranteed_target] = 1.0
        return result

    def on_draw_result(self, got_guaranteed: bool) -> None:
        self.last_was_guaranteed = got_guaranteed


class CompositePity(PityMechanism):
    """组合保底：同时应用多个保底机制"""

    def __init__(self, mechanisms: List[PityMechanism]):
        self.mechanisms = mechanisms

    def apply(self, context: GachaContext) -> Dict[str, float]:
        result = context.base_probabilities.copy()
        for mechanism in self.mechanisms:
            result = mechanism.apply(GachaContext(
                pool_id=context.pool_id,
                base_probabilities=result,
                pity_counters=context.pity_counters,
                total_draws=context.total_draws,
                extra_data=context.extra_data,
            ))
        return result
```

- [ ] **Step 2: 创建测试 tests/core/test_pity.py**

```python
import pytest
from gacha_simulator.core.pity import (
    PityMechanism, HardPity, SoftPity, DualPity, CompositePity, GachaContext
)


def test_hard_pity_triggers():
    pity = HardPity(counter_name='ssr', threshold=90, target_probability=1.0)
    context = GachaContext(
        pool_id='standard',
        base_probabilities={'ssr': 0.006, 'sr': 0.051, 'r': 0.943},
        pity_counters={'ssr': 90},
        total_draws=90,
    )
    result = pity.apply(context)
    assert 'pity_trigger' in result
    assert result['pity_trigger'] == 1.0


def test_soft_pity_increases_probability():
    pity = SoftPity(counter_name='ssr', start_at=70, increment_per_pull=0.01)
    context = GachaContext(
        pool_id='standard',
        base_probabilities={'ssr': 0.006, 'sr': 0.994},
        pity_counters={'ssr': 75},
        total_draws=75,
    )
    result = pity.apply(context)
    assert result['ssr'] > context.base_probabilities['ssr']


def test_soft_pity_no_increase_before_threshold():
    pity = SoftPity(counter_name='ssr', start_at=70)
    context = GachaContext(
        pool_id='standard',
        base_probabilities={'ssr': 0.006, 'sr': 0.994},
        pity_counters={'ssr': 50},
        total_draws=50,
    )
    result = pity.apply(context)
    assert abs(result['ssr'] - context.base_probabilities['ssr']) < 0.0001


def test_composite_pity():
    hard_pity = HardPity(counter_name='ssr', threshold=90)
    soft_pity = SoftPity(counter_name='ssr', start_at=70)
    composite = CompositePity([soft_pity, hard_pity])
    context = GachaContext(
        pool_id='standard',
        base_probabilities={'ssr': 0.006, 'sr': 0.994},
        pity_counters={'ssr': 90},
        total_draws=90,
    )
    result = composite.apply(context)
    assert 'pity_trigger' in result
```

- [ ] **Step 3: 运行测试验证**

Run: `cd /workspace && python -m pytest tests/core/test_pity.py -v`

Expected: 所有测试通过

---

### Task 3: 策略、停止条件、资源获取函数

**Files:**
- Create: `gacha_simulator/core/strategy.py`
- Create: `gacha_simulator/core/stop_condition.py`
- Create: `gacha_simulator/core/resource_gain.py`
- Test: `tests/core/test_strategy.py`
- Test: `tests/core/test_stop_condition.py`
- Test: `tests/core/test_resource_gain.py`

- [ ] **Step 1: 创建 core/strategy.py**

```python
from abc import ABC, abstractmethod
from typing import List, Optional, TYPE_CHECKING
from .action import Action
from .schedule import PoolSchedule
from .target_card import TargetCardSet

if TYPE_CHECKING:
    from .state import GachaState
    from .info_vector import InfoVector
    from .pool import Pool
    from .stop_condition import StopCondition


class Strategy(ABC):
    lookahead: Optional[float] = None

    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @abstractmethod
    def description(cls) -> str:
        return ""

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


class FixedCountStrategy(Strategy):
    """固定次数策略"""

    def __init__(self, count: int):
        self.count = count

    @classmethod
    def description(cls) -> str:
        return "抽指定次数后停止"

    def select_action(
        self,
        state: 'GachaState',
        history: List['InfoVector'],
        current_pools: List['Pool'],
        future_schedules: List[PoolSchedule],
        target_cards: TargetCardSet,
        stop_condition: 'StopCondition',
    ) -> Action:
        from .action import WaitAction
        if len(history) >= self.count:
            return WaitAction(duration=0)
        if not current_pools:
            return WaitAction(duration=1)
        return Action  # 需要更智能的选择


class TargetHuntingStrategy(Strategy):
    """目标狩猎策略"""

    def __init__(self, target_pool_ids: List[str]):
        self.target_pool_ids = target_pool_ids

    @classmethod
    def description(cls) -> str:
        return "优先抽目标池子直到获得目标"

    def select_action(
        self,
        state: 'GachaState',
        history: List['InfoVector'],
        current_pools: List['Pool'],
        future_schedules: List[PoolSchedule],
        target_cards: TargetCardSet,
        stop_condition: 'StopCondition',
    ) -> Action:
        from .action import DrawAction, WaitAction
        target_pools = [p for p in current_pools if p.id in self.target_pool_ids]
        for pool in target_pools:
            if state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)
        return WaitAction(duration=3600)


class CompositeStrategy(Strategy):
    """组合策略"""

    def __init__(self, strategies: List[Strategy], mode: str = 'first_valid'):
        self.strategies = strategies
        self.mode = mode

    @classmethod
    def description(cls) -> str:
        return "组合多个策略"

    def select_action(
        self,
        state: 'GachaState',
        history: List['InfoVector'],
        current_pools: List['Pool'],
        future_schedules: List[PoolSchedule],
        target_cards: TargetCardSet,
        stop_condition: 'StopCondition',
    ) -> Action:
        for strategy in self.strategies:
            action = strategy.select_action(
                state, history, current_pools, future_schedules, target_cards, stop_condition
            )
            if self.mode == 'first_valid' and action is not None:
                return action
        from .action import WaitAction
        return WaitAction(duration=0)
```

- [ ] **Step 2: 创建 core/stop_condition.py**

```python
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import GachaState
    from .info_vector import InfoVector


class StopCondition(ABC):
    @abstractmethod
    def check(self, state: 'GachaState', history: List['InfoVector']) -> bool:
        pass

    @abstractmethod
    def description(self) -> str:
        pass


class FixedActionCountCondition(StopCondition):
    def __init__(self, max_actions: int):
        self.max_actions = max_actions

    def check(self, state: 'GachaState', history: List['InfoVector']) -> bool:
        return len(history) >= self.max_actions

    def description(self) -> str:
        return f"抽满 {self.max_actions} 次后停止"


class ResourceThresholdCondition(StopCondition):
    def __init__(self, resource: str, threshold: float, operator: str = '<='):
        self.resource = resource
        self.threshold = threshold
        self.operator = operator

    def check(self, state: 'GachaState', history: List['InfoVector']) -> bool:
        current = state.resources.get(self.resource, 0)
        if self.operator == '<=':
            return current <= self.threshold
        elif self.operator == '>=':
            return current >= self.threshold
        elif self.operator == '==':
            return current == self.threshold
        return False

    def description(self) -> str:
        return f"资源 {self.resource} {self.operator} {self.threshold}"


class TargetAcquiredCondition(StopCondition):
    def __init__(self, target_id: str, quantity: int = 1):
        self.target_id = target_id
        self.quantity = quantity

    def check(self, state: 'GachaState', history: List['InfoVector']) -> bool:
        count = sum(1 for iv in history if iv.card_id == self.target_id)
        return count >= self.quantity

    def description(self) -> str:
        return f"获得 {self.quantity} 张 {self.target_id}"


class TimeLimitCondition(StopCondition):
    def __init__(self, max_time: float):
        self.max_time = max_time

    def check(self, state: 'GachaState', history: List['InfoVector']) -> bool:
        return state.real_time >= self.max_time

    def description(self) -> str:
        return f"现实时间达到 {self.max_time} 秒"


class CompositeStopCondition(StopCondition):
    def __init__(self, conditions: list, mode: str = 'any'):
        self.conditions = conditions
        self.mode = mode

    def check(self, state: 'GachaState', history: List['InfoVector']) -> bool:
        if self.mode == 'any':
            return any(c.check(state, history) for c in self.conditions)
        else:
            return all(c.check(state, history) for c in self.conditions)

    def description(self) -> str:
        ops = ' 或 ' if self.mode == 'any' else ' 且 '
        return ops.join(c.description() for c in self.conditions)
```

- [ ] **Step 3: 创建 core/resource_gain.py**

```python
from abc import ABC, abstractmethod
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from .state import GachaState


class ResourceGainFunction(ABC):
    @abstractmethod
    def compute(self, elapsed_time: float, state: 'GachaState') -> Dict[str, float]:
        pass

    @abstractmethod
    def description(self) -> str:
        pass


class LinearResourceGain(ResourceGainFunction):
    """线性资源获取：每秒获得固定数量"""

    def __init__(self, rate: Dict[str, float]):
        self.rate = rate

    def compute(self, elapsed_time: float, state: 'GachaState') -> Dict[str, float]:
        return {k: v * elapsed_time for k, v in self.rate.items()}

    def description(self) -> str:
        rates = ', '.join(f"{k}={v}/s" for k, v in self.rate.items())
        return f"线性获取: {rates}"


class PeriodicResourceGain(ResourceGainFunction):
    """周期性资源获取：每隔一定时间获得一次奖励"""

    def __init__(self, period: float, reward: Dict[str, float]):
        self.period = period
        self.reward = reward

    def compute(self, elapsed_time: float, state: 'GachaState') -> Dict[str, float]:
        if elapsed_time < self.period:
            return {k: 0 for k in self.reward}
        periods = int(elapsed_time // self.period)
        return {k: v * periods for k, v in self.reward.items()}

    def description(self) -> str:
        rewards = ', '.join(f"{k}={v}" for k, v in self.reward.items())
        return f"周期获取: 每{self.period}s获得 {rewards}"


class StepResourceGain(ResourceGainFunction):
    """阶梯式资源获取：不同时间段获取速率不同"""

    def __init__(self, steps: list):
        self.steps = sorted(steps, key=lambda x: x['time'])

    def compute(self, elapsed_time: float, state: 'GachaState') -> Dict[str, float]:
        total = {k: 0 for k in self.steps[0]['gain'].keys()}
        current_time = 0
        for step in self.steps:
            if elapsed_time <= current_time:
                break
            segment_duration = min(elapsed_time, step['time']) - current_time
            for k, v in step['gain'].items():
                total[k] += v * segment_duration
            current_time = step['time']
        return total

    def description(self) -> str:
        return "阶梯式资源获取"


class CompositeResourceGain(ResourceGainFunction):
    """组合多种资源获取方式"""

    def __init__(self, functions: list):
        self.functions = functions

    def compute(self, elapsed_time: float, state: 'GachaState') -> Dict[str, float]:
        result = {}
        for func in self.functions:
            gains = func.compute(elapsed_time, state)
            for k, v in gains.items():
                result[k] = result.get(k, 0) + v
        return result

    def description(self) -> str:
        return ' + '.join(f.description() for f in self.functions)
```

- [ ] **Step 4: 创建测试 tests/core/test_strategy.py**

```python
import pytest
from gacha_simulator.core.strategy import (
    Strategy, FixedCountStrategy, TargetHuntingStrategy, CompositeStrategy
)
from gacha_simulator.core.action import DrawAction, WaitAction
from gacha_simulator.core.state import GachaState
from gacha_simulator.core.stop_condition import FixedActionCountCondition
from gacha_simulator.core.target_card import TargetCardSet


def test_fixed_count_strategy():
    state = GachaState(resources={'primogem': 1000})
    strategy = FixedCountStrategy(count=10)
    stop = FixedActionCountCondition(max_actions=10)
    pools = []

    action = strategy.select_action(state, [], pools, [], TargetCardSet([]), stop)
    assert isinstance(action, WaitAction)

    history = [None] * 10
    action = strategy.select_action(state, history, pools, [], TargetCardSet([]), stop)
    assert action.duration == 0


def test_target_hunting_strategy():
    state = GachaState(resources={'primogem': 160})
    strategy = TargetHuntingStrategy(target_pool_ids=['standard'])
    pools = []
    from gacha_simulator.core.pool import Pool, Reward
    pools.append(Pool('standard', 'Standard', {'primogem': 160}, [(Reward('r1', 'R1'), 1.0)]))

    action = strategy.select_action(state, [], pools, [], TargetCardSet([]), FixedActionCountCondition(100))
    assert isinstance(action, DrawAction)
    assert action.pool_id == 'standard'
```

- [ ] **Step 5: 创建测试 tests/core/test_stop_condition.py**

```python
import pytest
from gacha_simulator.core.stop_condition import (
    FixedActionCountCondition, ResourceThresholdCondition,
    TargetAcquiredCondition, TimeLimitCondition, CompositeStopCondition
)
from gacha_simulator.core.state import GachaState


def test_fixed_action_count():
    cond = FixedActionCountCondition(max_actions=10)
    state = GachaState()
    assert cond.check(state, []) is False
    assert cond.check(state, [None] * 10) is True


def test_resource_threshold():
    cond = ResourceThresholdCondition('primogem', 100, '<=')
    state = GachaState(resources={'primogem': 50})
    assert cond.check(state, []) is True
    state.resources['primogem'] = 200
    assert cond.check(state, []) is False


def test_target_acquired():
    cond = TargetAcquiredCondition('character_a', quantity=2)
    state = GachaState()
    from gacha_simulator.core.info_vector import InfoVector
    history = [
        InfoVector('draw', 'character_a', 'p1', action_index=0, session_id='s1'),
        InfoVector('draw', 'character_b', 'p1', action_index=1, session_id='s1'),
    ]
    assert cond.check(state, history) is False
    history.append(InfoVector('draw', 'character_a', 'p1', action_index=2, session_id='s1'))
    assert cond.check(state, history) is True


def test_composite_any():
    cond1 = FixedActionCountCondition(5)
    cond2 = ResourceThresholdCondition('primogem', 0, '<=')
    composite = CompositeStopCondition([cond1, cond2], mode='any')
    state = GachaState(resources={'primogem': 0})
    assert composite.check(state, []) is True
```

- [ ] **Step 6: 创建测试 tests/core/test_resource_gain.py**

```python
import pytest
from gacha_simulator.core.resource_gain import (
    LinearResourceGain, PeriodicResourceGain, CompositeResourceGain
)
from gacha_simulator.core.state import GachaState


def test_linear_gain():
    func = LinearResourceGain({'primogem': 10, 'mora': 100})
    gains = func.compute(60, GachaState())
    assert gains['primogem'] == 600
    assert gains['mora'] == 6000


def test_periodic_gain():
    func = PeriodicResourceGain(period=3600, reward={'daily': 600})
    gains = func.compute(3600, GachaState())
    assert gains['daily'] == 600
    gains = func.compute(7199, GachaState())
    assert gains['daily'] == 600
    gains = func.compute(7200, GachaState())
    assert gains['daily'] == 1200


def test_composite_gain():
    linear = LinearResourceGain({'primogem': 1})
    periodic = PeriodicResourceGain(10, {'bonus': 100})
    composite = CompositeResourceGain([linear, periodic])
    gains = composite.compute(10, GachaState())
    assert gains['primogem'] == 10
    assert gains['bonus'] == 100
```

- [ ] **Step 7: 运行测试验证**

Run: `cd /workspace && python -m pytest tests/core/ -v`

Expected: 所有测试通过

---

### Task 4: 广义出率、时间表、目标卡

**Files:**
- Create: `gacha_simulator/core/generalized_drop_rate.py`
- Create: `gacha_simulator/core/schedule.py`
- Create: `gacha_simulator/core/target_card.py`
- Test: `tests/core/test_generalized_drop_rate.py`
- Test: `tests/core/test_schedule.py`
- Test: `tests/core/test_target_card.py`

- [ ] **Step 1: 创建 core/generalized_drop_rate.py**

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .info_vector import InfoVector


class GeneralizedDropRate(ABC):
    @abstractmethod
    def compute(self, t: int, history: List['InfoVector']) -> float:
        pass

    @classmethod
    def name(cls) -> str:
        return cls.__name__

    @classmethod
    @abstractmethod
    def description(cls) -> str:
        pass


class RarityValueAtT(GeneralizedDropRate):
    """第t次抽卡的稀有度价值"""

    def __init__(self, rarity_values: Dict[str, float]):
        self.rarity_values = rarity_values

    @classmethod
    def description(cls) -> str:
        return "返回第t次抽卡的稀有度价值"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        if t >= len(history):
            return 0
        iv = history[t]
        return self.rarity_values.get(iv.card_id or '', 0)


class CumulativeResourceEfficiency(GeneralizedDropRate):
    """累计资源效率"""

    @classmethod
    def description(cls) -> str:
        return "累计资源效率 = 总获得资源 / 总消耗资源"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        if t == 0:
            return 0
        total_consumed = sum(
            sum(iv.resources_consumed.values()) for iv in history[:t]
        )
        total_gained = sum(
            sum(iv.resources_gained.values()) for iv in history[:t]
        )
        if total_consumed == 0:
            return 0
        return total_gained / total_consumed


class PityProgressAtT(GeneralizedDropRate):
    """第t次抽卡时的保底进度"""

    def __init__(self, counter_name: str, threshold: int):
        self.counter_name = counter_name
        self.threshold = threshold

    @classmethod
    def description(cls) -> str:
        return "保底进度 = 当前计数 / 保底阈值"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        if t >= len(history):
            return 0
        pity_state = history[t].pity_state
        count = pity_state.get(self.counter_name, 0)
        return min(count / self.threshold, 1.0)


class DropRateBetweenT1T2(GeneralizedDropRate):
    """t1到t2之间的平均出率"""

    def __init__(self, t1: int, t2: int, target_id: str):
        self.t1 = t1
        self.t2 = t2
        self.target_id = target_id

    @classmethod
    def description(cls) -> str:
        return f"{self.t1}到{self.t2}次抽卡之间的平均出率"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        start = max(0, self.t1)
        end = min(len(history), self.t2)
        if end <= start:
            return 0
        count = sum(1 for iv in history[start:end] if iv.card_id == self.target_id)
        return count / (end - start)


class TotalValueAtT(GeneralizedDropRate):
    """第t次抽卡时的总价值"""

    def __init__(self, value_functions: List[GeneralizedDropRate], weights: List[float] = None):
        self.value_functions = value_functions
        self.weights = weights or [1.0] * len(value_functions)

    @classmethod
    def description(cls) -> str:
        return "多个价值函数的加权和"

    def compute(self, t: int, history: List['InfoVector']) -> float:
        total = 0
        for vf, weight in zip(self.value_functions, self.weights):
            total += vf.compute(t, history) * weight
        return total
```

- [ ] **Step 2: 创建 core/schedule.py**

```python
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PoolSchedule:
    """卡池开放时间表"""
    pool_id: str
    available_from: float
    available_until: float

    def is_available_at(self, time: float) -> bool:
        return self.available_from <= time <= self.available_until


class PoolScheduleManager:
    """卡池时间表管理器"""

    def __init__(self, schedules: List[PoolSchedule]):
        self.schedules = schedules

    def get_pools_at_time(self, time: float) -> List[str]:
        """获取指定时间开放的池子ID"""
        return [s.pool_id for s in self.schedules if s.is_available_at(time)]

    def get_future_schedules(
        self, from_time: float, lookahead: Optional[float] = None
    ) -> List[PoolSchedule]:
        """获取未来的卡池安排"""
        future = [s for s in self.schedules if s.available_from >= from_time]
        if lookahead is not None:
            future = [s for s in future if s.available_from < from_time + lookahead]
        return sorted(future, key=lambda s: s.available_from)

    def get_schedules_for_pool(self, pool_id: str) -> List[PoolSchedule]:
        """获取某个池子的所有时间安排"""
        return [s for s in self.schedules if s.pool_id == pool_id]
```

- [ ] **Step 3: 创建 core/target_card.py**

```python
from dataclasses import dataclass, field
from typing import List


@dataclass
class TargetCard:
    """目标卡定义"""
    card_id: str
    pool_ids: List[str]  # 这张卡可能出现的所有池子
    quantity_needed: int
    priority: int = 0

    def is_in_pool(self, pool_id: str) -> bool:
        return pool_id in self.pool_ids


@dataclass
class TargetCardSet:
    """目标卡集合"""
    targets: List[TargetCard] = field(default_factory=list)

    def get_quantity_needed(self, card_id: str) -> int:
        for t in self.targets:
            if t.card_id == card_id:
                return t.quantity_needed
        return 0

    def get_cards_by_pool(self, pool_id: str) -> List[TargetCard]:
        return [t for t in self.targets if t.is_in_pool(pool_id)]

    def get_unfinished_targets(self, acquired: dict) -> List[TargetCard]:
        result = []
        for t in self.targets:
            current = acquired.get(t.card_id, 0)
            if current < t.quantity_needed:
                result.append(t)
        return sorted(result, key=lambda x: x.priority, reverse=True)
```

- [ ] **Step 4: 创建测试 tests/core/test_generalized_drop_rate.py**

```python
import pytest
from gacha_simulator.core.generalized_drop_rate import (
    RarityValueAtT, CumulativeResourceEfficiency, PityProgressAtT
)
from gacha_simulator.core.info_vector import InfoVector


def test_rarity_value_at_t():
    rarity_values = {'ssr': 10, 'sr': 5, 'r': 1}
    gdr = RarityValueAtT(rarity_values)
    history = [
        InfoVector('draw', 'ssr', 'p1', action_index=0, session_id='s1'),
        InfoVector('draw', 'r', 'p1', action_index=1, session_id='s1'),
    ]
    assert gdr.compute(0, history) == 10
    assert gdr.compute(1, history) == 1


def test_cumulative_resource_efficiency():
    gdr = CumulativeResourceEfficiency()
    history = [
        InfoVector('draw', 'r1', 'p1', resources_consumed={'primogem': 160}, resources_gained={'char': 1}, action_index=0, session_id='s1'),
        InfoVector('draw', 'r2', 'p1', resources_consumed={'primogem': 160}, resources_gained={'item': 1}, action_index=1, session_id='s1'),
    ]
    assert gdr.compute(2, history) == 2 / 320
```

- [ ] **Step 5: 创建测试 tests/core/test_schedule.py**

```python
import pytest
from gacha_simulator.core.schedule import PoolSchedule, PoolScheduleManager


def test_pool_schedule():
    schedule = PoolSchedule('pool1', available_from=0, available_until=100)
    assert schedule.is_available_at(50) is True
    assert schedule.is_available_at(150) is False


def test_schedule_manager():
    schedules = [
        PoolSchedule('pool1', 0, 100),
        PoolSchedule('pool2', 50, 150),
        PoolSchedule('pool3', 200, 300),
    ]
    manager = PoolScheduleManager(schedules)
    assert manager.get_pools_at_time(75) == ['pool1', 'pool2']
    future = manager.get_future_schedules(100)
    assert len(future) == 2
    assert future[0].pool_id == 'pool2'
```

- [ ] **Step 6: 创建测试 tests/core/test_target_card.py**

```python
import pytest
from gacha_simulator.core.target_card import TargetCard, TargetCardSet


def test_target_card():
    card = TargetCard('character_a', ['pool1', 'pool2'], quantity_needed=2, priority=1)
    assert card.is_in_pool('pool1') is True
    assert card.is_in_pool('pool3') is False


def test_target_card_set():
    targets = [
        TargetCard('a', ['p1'], 1, priority=2),
        TargetCard('b', ['p1', 'p2'], 2, priority=1),
    ]
    tcs = TargetCardSet(targets)
    assert tcs.get_quantity_needed('a') == 1
    assert tcs.get_quantity_needed('c') == 0
    assert len(tcs.get_cards_by_pool('p2')) == 1
    unfinished = tcs.get_unfinished_targets({'a': 1, 'b': 0})
    assert len(unfinished) == 1
    assert unfinished[0].card_id == 'b'
```

- [ ] **Step 7: 运行测试验证**

Run: `cd /workspace && python -m pytest tests/core/ -v`

Expected: 所有测试通过

---

## Phase 2: 生成器和服务层

### Task 5: 生成器模块

**Files:**
- Create: `gacha_simulator/generator/__init__.py`
- Create: `gacha_simulator/generator/schedule_generator.py`
- Create: `gacha_simulator/generator/target_generator.py`
- Test: `tests/generator/test_schedule_generator.py`
- Test: `tests/generator/test_target_generator.py`

- [ ] **Step 1: 创建 generator/__init__.py**

```python
from .schedule_generator import PoolScheduleGenerator, UserDefinedScheduleGenerator, PeriodicScheduleGenerator
from .target_generator import TargetCardGenerator, UserDefinedTargetGenerator, RuleBasedTargetGenerator

__all__ = [
    'PoolScheduleGenerator', 'UserDefinedScheduleGenerator', 'PeriodicScheduleGenerator',
    'TargetCardGenerator', 'UserDefinedTargetGenerator', 'RuleBasedTargetGenerator',
]
```

- [ ] **Step 2: 创建 generator/schedule_generator.py**

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from ..core.schedule import PoolSchedule, PoolScheduleManager


class PoolScheduleGenerator(ABC):
    @abstractmethod
    def generate(self, config: Dict[str, Any], pool_ids: List[str]) -> List[PoolSchedule]:
        pass


class UserDefinedScheduleGenerator(PoolScheduleGenerator):
    """用户定义的时间表"""

    def __init__(self, schedules: List[PoolSchedule]):
        self.schedules = schedules

    def generate(self, config: Dict[str, Any], pool_ids: List[str]) -> List[PoolSchedule]:
        return self.schedules


class PeriodicScheduleGenerator(PoolScheduleGenerator):
    """周期性卡池时间表"""

    def __init__(self, period: float, active_duration: float, start_offset: float = 0):
        self.period = period
        self.active_duration = active_duration
        self.start_offset = start_offset

    def generate(self, config: Dict[str, Any], pool_ids: List[str]) -> List[PoolSchedule]:
        schedules = []
        total_duration = config.get('total_duration', 86400 * 30)
        for pool_id in pool_ids:
            t = self.start_offset
            while t < total_duration:
                schedules.append(PoolSchedule(
                    pool_id=pool_id,
                    available_from=t,
                    available_until=t + self.active_duration,
                ))
                t += self.period
        return schedules
```

- [ ] **Step 3: 创建 generator/target_generator.py**

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from ..core.schedule import PoolSchedule
from ..core.pool import Pool
from ..core.target_card import TargetCard, TargetCardSet


class TargetCardGenerator(ABC):
    @abstractmethod
    def generate(
        self,
        future_schedules: List[PoolSchedule],
        pools: List[Pool],
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> TargetCardSet:
        pass


class UserDefinedTargetGenerator(TargetCardGenerator):
    """用户指定的目标卡"""

    def __init__(self, targets: TargetCardSet):
        self.targets = targets

    def generate(
        self,
        future_schedules: List[PoolSchedule],
        pools: List[Pool],
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> TargetCardSet:
        return self.targets


class RuleBasedTargetGenerator(TargetCardGenerator):
    """基于规则的目标卡生成"""

    def __init__(self, rules: List[Dict[str, Any]]):
        self.rules = rules

    def generate(
        self,
        future_schedules: List[PoolSchedule],
        pools: List[Pool],
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> TargetCardSet:
        targets = []
        for rule in self.rules:
            rule_type = rule.get('type')
            if rule_type == 'all_in_pool':
                pool_id = rule.get('pool_id')
                quantity = rule.get('quantity', 1)
                for pool in pools:
                    if pool.id == pool_id:
                        for reward, _ in pool.rewards:
                            targets.append(TargetCard(
                                card_id=reward.id,
                                pool_ids=[pool_id],
                                quantity_needed=quantity,
                            ))
        return TargetCardSet(targets)
```

- [ ] **Step 4: 创建测试 tests/generator/test_schedule_generator.py**

```python
import pytest
from gacha_simulator.generator.schedule_generator import PeriodicScheduleGenerator
from gacha_simulator.core.schedule import PoolSchedule


def test_periodic_schedule():
    gen = PeriodicScheduleGenerator(period=100, active_duration=50, start_offset=0)
    schedules = gen.generate({'total_duration': 300}, ['pool1', 'pool2'])
    assert len(schedules) == 6
    assert all(isinstance(s, PoolSchedule) for s in schedules)
```

- [ ] **Step 5: 创建测试 tests/generator/test_target_generator.py**

```python
import pytest
from gacha_simulator.generator.target_generator import RuleBasedTargetGenerator
from gacha_simulator.core.pool import Pool, Reward
from gacha_simulator.core.schedule import PoolSchedule
from gacha_simulator.core.target_card import TargetCardSet


def test_rule_based_generator():
    pools = [
        Pool('p1', 'Pool 1', {}, [(Reward('r1', 'R1'), 1.0), (Reward('r2', 'R2'), 1.0)])
    ]
    gen = RuleBasedTargetGenerator([
        {'type': 'all_in_pool', 'pool_id': 'p1', 'quantity': 1}
    ])
    result = gen.generate([], pools)
    assert len(result.targets) == 2
    assert result.get_quantity_needed('r1') == 1
```

- [ ] **Step 6: 运行测试验证**

Run: `cd /workspace && python -m pytest tests/generator/ -v`

Expected: 所有测试通过

---

### Task 6: 服务层

**Files:**
- Create: `gacha_simulator/service/__init__.py`
- Create: `gacha_simulator/service/gacha_service.py`
- Create: `gacha_simulator/service/analysis_service.py`
- Create: `gacha_simulator/service/config_service.py`
- Create: `gacha_simulator/service/batch_service.py`
- Test: `tests/service/test_gacha_service.py`
- Test: `tests/service/test_analysis_service.py`
- Test: `tests/service/test_batch_service.py`

- [ ] **Step 1: 创建 service/__init__.py**

```python
from .gacha_service import GachaService
from .analysis_service import AnalysisService
from .config_service import ConfigService
from .batch_service import BatchService, BatchConfig, SimulationVariant, ConditionGenerator

__all__ = ['GachaService', 'AnalysisService', 'ConfigService', 'BatchService', 'BatchConfig', 'SimulationVariant', 'ConditionGenerator']
```

- [ ] **Step 2: 创建 service/gacha_service.py**

```python
from typing import List, Optional
import uuid
from ..core import (
    GachaState, Pool, Action, DrawAction, WaitAction,
    InfoVector, Strategy, StopCondition, PoolSchedule,
    TargetCardSet, ResourceGainFunction, PityMechanism, GachaContext
)


class GachaService:
    """抽卡服务"""

    def __init__(
        self,
        pools: List[Pool],
        strategy: Strategy,
        stop_condition: StopCondition,
        target_cards: TargetCardSet,
        schedule_manager: Optional['PoolScheduleManager'] = None,
        resource_gain: Optional[ResourceGainFunction] = None,
        pity_mechanism: Optional[PityMechanism] = None,
    ):
        self.pools = {p.id: p for p in pools}
        self.strategy = strategy
        self.stop_condition = stop_condition
        self.target_cards = target_cards
        self.schedule_manager = schedule_manager
        self.resource_gain = resource_gain
        self.pity_mechanism = pity_mechanism
        self.session_id = str(uuid.uuid4())

    def run_simulation(
        self, initial_state: GachaState, max_iterations: int = 100000
    ) -> List[InfoVector]:
        state = initial_state.clone()
        history: List[InfoVector] = []
        pity_counters = {k: 0 for k in state.pity_counters}

        for iteration in range(max_iterations):
            if self.stop_condition.check(state, history):
                break

            current_pools = state.get_available_pools(list(self.pools.values()))
            future_schedules = []
            if self.schedule_manager and self.strategy.lookahead:
                future_schedules = self.schedule_manager.get_future_schedules(
                    state.real_time, self.strategy.lookahead
                )

            action = self.strategy.select_action(
                state, history, current_pools, future_schedules,
                self.target_cards, self.stop_condition
            )

            info_vector = self._execute_action(
                action, state, history, pity_counters
            )
            history.append(info_vector)
            state.total_actions += 1

        return history

    def _execute_action(
        self, action: Action, state: GachaState,
        history: List[InfoVector], pity_counters: dict
    ) -> InfoVector:
        if isinstance(action, DrawAction):
            return self._execute_draw(action, state, history, pity_counters)
        elif isinstance(action, WaitAction):
            return self._execute_wait(action, state, history)
        else:
            raise ValueError(f"Unknown action type: {action}")

    def _execute_draw(
        self, action: DrawAction, state: GachaState,
        history: List[InfoVector], pity_counters: dict
    ) -> InfoVector:
        pool = self.pools.get(action.pool_id)
        if not pool:
            raise ValueError(f"Pool not found: {action.pool_id}")

        real_time_before = state.real_time
        state.spend(pool.cost)

        probabilities = {r.id: p for r, p in pool.rewards}
        if self.pity_mechanism:
            context = GachaContext(
                pool_id=pool.id,
                base_probabilities=probabilities,
                pity_counters=pity_counters,
                total_draws=len(history),
            )
            probabilities = self.pity_mechanism.apply(context)

        reward = pool.draw()
        pity_counters['draw'] = pity_counters.get('draw', 0) + 1
        pity_state = pity_counters.copy()

        resources_consumed = pool.cost.copy()
        resources_gained = reward.resources_gained.copy()
        state.gain(resources_gained)

        return InfoVector(
            action_type='draw',
            card_id=reward.id,
            pool_id=pool.id,
            resources_consumed=resources_consumed,
            resources_gained=resources_gained,
            real_time_before=real_time_before,
            real_time_after=state.real_time,
            time_elapsed=1,
            pity_state=pity_state,
            action_index=len(history),
            session_id=self.session_id,
        )

    def _execute_wait(
        self, action: WaitAction, state: GachaState, history: List[InfoVector]
    ) -> InfoVector:
        real_time_before = state.real_time
        state.real_time += action.duration

        resources_gained = {}
        if self.resource_gain:
            resources_gained = self.resource_gain.compute(action.duration, state)
            state.gain(resources_gained)

        return InfoVector(
            action_type='wait',
            card_id=None,
            pool_id=None,
            resources_consumed={},
            resources_gained=resources_gained,
            real_time_before=real_time_before,
            real_time_after=state.real_time,
            time_elapsed=action.duration,
            pity_state={},
            action_index=len(history),
            session_id=self.session_id,
        )
```

- [ ] **Step 3: 创建 service/analysis_service.py**

```python
from typing import List, Dict, Any
import numpy as np
from ..core import InfoVector, GeneralizedDropRate


class AnalysisService:
    """分析服务"""

    def __init__(self, gdr_functions: List[GeneralizedDropRate] = None):
        self.gdr_functions = gdr_functions or []

    def compute_gdr_distribution(
        self, history: List[InfoVector]
    ) -> Dict[str, List[float]]:
        result = {gdr.name(): [] for gdr in self.gdr_functions}
        for t in range(len(history)):
            for gdr in self.gdr_functions:
                value = gdr.compute(t, history)
                result[gdr.name()].append(value)
        return result

    def compute_pmf(
        self, values: List[float], bins: int = 20
    ) -> Dict[str, Any]:
        hist, edges = np.histogram(values, bins=bins)
        pmf = hist / len(values) if len(values) > 0 else []
        return {
            'pmf': pmf.tolist(),
            'edges': edges.tolist(),
            'bin_centers': ((edges[:-1] + edges[1:]) / 2).tolist(),
        }

    def compute_cdf(
        self, values: List[float], bins: int = 20
    ) -> Dict[str, Any]:
        sorted_values = sorted(values)
        cdf = np.arange(1, len(sorted_values) + 1) / len(sorted_values)
        return {
            'cdf': cdf.tolist(),
            'values': sorted_values,
        }

    def compute_basic_stats(
        self, history: List[InfoVector]
    ) -> Dict[str, Any]:
        draw_history = [iv for iv in history if iv.action_type == 'draw']
        card_counts = {}
        for iv in draw_history:
            card_counts[iv.card_id] = card_counts.get(iv.card_id, 0) + 1

        total_resources_spent = {}
        for iv in draw_history:
            for resource, amount in iv.resources_consumed.items():
                total_resources_spent[resource] = total_resources_spent.get(resource, 0) + amount

        return {
            'total_draws': len(draw_history),
            'total_wait_time': sum(iv.time_elapsed for iv in history if iv.action_type == 'wait'),
            'card_counts': card_counts,
            'total_resources_spent': total_resources_spent,
        }

    def compute_time_series(
        self, history: List[InfoVector], value_name: str
    ) -> List[Dict[str, Any]]:
        result = []
        cumulative = 0
        for iv in history:
            if iv.action_type == 'draw':
                if iv.card_id == value_name:
                    cumulative += 1
            result.append({
                'action_index': iv.action_index,
                'real_time': iv.real_time_after,
                'cumulative': cumulative,
            })
        return result
```

- [ ] **Step 4: 创建 service/config_service.py**

```python
import json
from pathlib import Path
from typing import Dict, Any, List
from ..core import Pool, Reward, GachaState


class ConfigService:
    """配置管理服务"""

    def __init__(self, config_dir: str = 'data/config'):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def save_config(self, name: str, config: Dict[str, Any]) -> None:
        path = self.config_dir / f'{name}.json'
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def load_config(self, name: str) -> Dict[str, Any]:
        path = self.config_dir / f'{name}.json'
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def list_configs(self) -> List[str]:
        return [p.stem for p in self.config_dir.glob('*.json')]

    def export_pool_to_config(self, pools: List[Pool]) -> Dict[str, Any]:
        return {
            'pools': [
                {
                    'id': p.id,
                    'name': p.name,
                    'cost': p.cost,
                    'rewards': [
                        {'id': r.id, 'name': r.name, 'probability': prob}
                        for r, prob in p.rewards
                    ],
                    'available_from': p.available_from,
                    'available_until': p.available_until,
                    'is_exchange': p.is_exchange,
                }
                for p in pools
            ]
        }

    def import_pool_from_config(self, config: Dict[str, Any]) -> List[Pool]:
        pools = []
        for p_data in config.get('pools', []):
            rewards = [
                (Reward(r['id'], r['name']), r['probability'])
                for r in p_data.get('rewards', [])
            ]
            pools.append(Pool(
                id=p_data['id'],
                name=p_data['name'],
                cost=p_data.get('cost', {}),
                rewards=rewards,
                available_from=p_data.get('available_from'),
                available_until=p_data.get('available_until'),
                is_exchange=p_data.get('is_exchange', False),
            ))
        return pools
```

- [ ] **Step 5: 创建 service/batch_service.py（批量模拟服务）**

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Callable, Optional, Union
from concurrent.futures import ProcessPoolExecutor, as_completed
from ..core import GachaState, InfoVector
from .gacha_service import GachaService
import random


@dataclass
class SimulationVariant:
    """模拟变体定义"""
    name: str
    initial_state_fn: Callable[[], GachaState]  # 生成初始状态的函数
    description: str = ""


@dataclass
class BatchSimulationResult:
    """批量模拟结果"""
    variant_name: str
    histories: List[List[InfoVector]]
    total_simulations: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchConfig:
    """批量模拟配置"""
    simulations_per_variant: int = 100
    max_workers: int = 4
    seed: Optional[int] = None  # 随机种子

    def __post_init__(self):
        if self.seed is not None:
            random.seed(self.seed)


class BatchService:
    """批量模拟服务"""

    def __init__(self, service_factory: Callable[[], GachaService]):
        self.service_factory = service_factory

    def run_batch(
        self,
        variants: List[SimulationVariant],
        config: BatchConfig,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[BatchSimulationResult]:
        """
        运行批量模拟

        Args:
            variants: 模拟变体列表
            config: 批量配置
            progress_callback: 进度回调函数 (current, total)

        Returns:
            每个变体的模拟结果列表
        """
        results = []
        total_tasks = sum(config.simulations_per_variant for _ in variants)

        for variant in variants:
            variant_results = []
            for i in range(config.simulations_per_variant):
                initial_state = variant.initial_state_fn()
                service = self.service_factory()
                history = service.run_simulation(initial_state)
                variant_results.append(history)

                if progress_callback:
                    completed = sum(
                        config.simulations_per_variant * idx + i + 1
                        for idx, v in enumerate(variants[:variants.index(variant)])
                    ) + i + 1
                    progress_callback(completed, total_tasks)

            results.append(BatchSimulationResult(
                variant_name=variant.name,
                histories=variant_results,
                total_simulations=len(variant_results),
            ))

        return results

    def run_parallel(
        self,
        variants: List[SimulationVariant],
        config: BatchConfig,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[BatchSimulationResult]:
        """并行运行批量模拟"""
        def run_single_simulation(variant_idx: int, sim_idx: int, variant: SimulationVariant):
            initial_state = variant.initial_state_fn()
            service = self.service_factory()
            history = service.run_simulation(initial_state)
            return variant_idx, sim_idx, history

        results = [
            BatchSimulationResult(
                variant_name=v.name,
                histories=[],
                total_simulations=config.simulations_per_variant,
            )
            for v in variants
        ]

        total_tasks = sum(config.simulations_per_variant for _ in variants)
        completed = 0

        with ProcessPoolExecutor(max_workers=config.max_workers) as executor:
            futures = []
            for variant_idx, variant in enumerate(variants):
                for sim_idx in range(config.simulations_per_variant):
                    futures.append(executor.submit(
                        run_single_simulation, variant_idx, sim_idx, variant
                    ))

            for future in as_completed(futures):
                variant_idx, sim_idx, history = future.result()
                results[variant_idx].histories.append(history)
                completed += 1
                if progress_callback:
                    progress_callback(completed, total_tasks)

        return results


class ConditionGenerator:
    """条件生成器 - 用于随机生成模拟条件"""

    @staticmethod
    def fixed_state(resources: Dict[str, float], pity_counters: Dict[str, int] = None) -> SimulationVariant:
        """固定条件"""
        def factory() -> GachaState:
            return GachaState(
                resources=resources.copy(),
                pity_counters=(pity_counters or {}).copy(),
            )
        return SimulationVariant(
            name="固定条件",
            initial_state_fn=factory,
            description=f"初始资源: {resources}",
        )

    @staticmethod
    def random_resources(
        resource_ranges: Dict[str, tuple],
        pity_counter_range: tuple = (0, 90),
    ) -> SimulationVariant:
        """随机资源条件"""
        def factory() -> GachaState:
            resources = {
                k: random.uniform(v[0], v[1])
                for k, v in resource_ranges.items()
            }
            pity = {'ssr': random.randint(*pity_counter_range)}
            return GachaState(resources=resources, pity_counters=pity)
        return SimulationVariant(
            name="随机资源",
            initial_state_fn=factory,
            description=f"资源范围: {resource_ranges}",
        )

    @staticmethod
    def monte_carlo_sampling(
        base_resources: Dict[str, float],
        variance: float = 0.2,
    ) -> SimulationVariant:
        """蒙特卡洛采样条件"""
        def factory() -> GachaState:
            resources = {
                k: v * random.uniform(1 - variance, 1 + variance)
                for k, v in base_resources.items()
            }
            return GachaState(resources=resources)
        return SimulationVariant(
            name="蒙特卡洛采样",
            initial_state_fn=factory,
            description=f"基准: {base_resources}, 方差: {variance}",
        )
```

- [ ] **Step 6: 创建测试 tests/service/test_batch_service.py**

```python
import pytest
from gacha_simulator.service.batch_service import (
    BatchService, BatchConfig, SimulationVariant, ConditionGenerator
)
from gacha_simulator.service.gacha_service import GachaService
from gacha_simulator.core import GachaState, Pool, Reward, Strategy, StopCondition, TargetCardSet
from gacha_simulator.core.action import DrawAction, WaitAction


class DummyStrategy(Strategy):
    lookahead = None
    @classmethod
    def description(cls): return "Dummy"
    def select_action(self, state, history, pools, futures, targets, stop):
        if len(history) >= 5:
            return WaitAction(0)
        return DrawAction('test')


class DummyStop(StopCondition):
    def check(self, state, history): return len(history) >= 5
    def description(self): return ""


def create_service_factory():
    pool = Pool('test', 'Test', {'gem': 10}, [(Reward('a', 'A'), 0.5), (Reward('b', 'B'), 0.5)])
    def factory() -> GachaService:
        return GachaService([pool], DummyStrategy(), DummyStop(), TargetCardSet([]))
    return factory


def test_batch_service_run():
    service = BatchService(create_service_factory())
    variant = SimulationVariant(
        name="test",
        initial_state_fn=lambda: GachaState(resources={'gem': 100}),
    )
    results = service.run_batch([variant], BatchConfig(simulations_per_variant=5))
    assert len(results) == 1
    assert results[0].total_simulations == 5
    assert len(results[0].histories) == 5


def test_condition_generator_fixed():
    variant = ConditionGenerator.fixed_state({'gem': 1000}, {'ssr': 50})
    state = variant.initial_state_fn()
    assert state.resources['gem'] == 1000
    assert state.pity_counters['ssr'] == 50


def test_condition_generator_random():
    variant = ConditionGenerator.random_resources({'gem': (0, 1000)})
    states = [variant.initial_state_fn() for _ in range(100)]
    gem_values = [s.resources['gem'] for s in states]
    assert min(gem_values) >= 0
    assert max(gem_values) <= 1000
```

- [ ] **Step 7: 运行测试验证**

Run: `cd /workspace && python -m pytest tests/service/ -v`

Expected: 所有测试通过

```python
import pytest
from gacha_simulator.service.gacha_service import GachaService
from gacha_simulator.core import (
    GachaState, Pool, Reward, Strategy, StopCondition,
    TargetCardSet, DrawAction, WaitAction
)
from gacha_simulator.core.schedule import PoolScheduleManager


class SimpleStrategy(Strategy):
    def __init__(self, pool_id: str, count: int):
        self.pool_id = pool_id
        self.count = count
        self.lookahead = None

    @classmethod
    def description(cls) -> str:
        return "Simple strategy"

    def select_action(self, state, history, current_pools, future_schedules, target_cards, stop_condition):
        if len(history) >= self.count:
            return WaitAction(duration=0)
        return DrawAction(pool_id=self.pool_id)


def test_gacha_service_run():
    pool = Pool('standard', 'Standard', {'primogem': 160}, [
        (Reward('ssr', 'SSR'), 0.006),
        (Reward('sr', 'SR'), 0.051),
        (Reward('r', 'R'), 0.943),
    ])
    state = GachaState(resources={'primogem': 1600})
    strategy = SimpleStrategy('standard', 10)
    stop = StopCondition()
    
    class AlwaysFalse(StopCondition):
        def check(self, state, history): return False
        def description(self): return ""
    
    service = GachaService([pool], strategy, AlwaysFalse(), TargetCardSet([]))
    history = service.run_simulation(state, max_iterations=10)
    assert len(history) == 10
```

- [ ] **Step 6: 创建测试 tests/service/test_analysis_service.py**

```python
import pytest
from gacha_simulator.service.analysis_service import AnalysisService
from gacha_simulator.core import InfoVector
from gacha_simulator.core.generalized_drop_rate import RarityValueAtT


def test_compute_basic_stats():
    service = AnalysisService()
    history = [
        InfoVector('draw', 'ssr', 'p1', resources_consumed={'primogem': 160}, action_index=0, session_id='s1'),
        InfoVector('draw', 'r', 'p1', resources_consumed={'primogem': 160}, action_index=1, session_id='s1'),
        InfoVector('wait', None, None, resources_gained={'primogem': 100}, action_index=2, session_id='s1'),
    ]
    stats = service.compute_basic_stats(history)
    assert stats['total_draws'] == 2
    assert stats['card_counts']['ssr'] == 1
    assert stats['card_counts']['r'] == 1
    assert stats['total_resources_spent']['primogem'] == 320


def test_compute_pmf():
    service = AnalysisService()
    result = service.compute_pmf([1, 1, 2, 3, 3, 3], bins=3)
    assert 'pmf' in result
    assert 'edges' in result
```

- [ ] **Step 7: 运行测试验证**

Run: `cd /workspace && python -m pytest tests/service/ -v`

Expected: 所有测试通过

---

## Phase 3: 可视化和GUI

### Task 7: 可视化模块

**Files:**
- Create: `gacha_simulator/visualization/__init__.py`
- Create: `gacha_simulator/visualization/pmf_plot.py`
- Create: `gacha_simulator/visualization/cdf_plot.py`
- Create: `gacha_simulator/visualization/time_series_plot.py`
- Test: `tests/visualization/test_plots.py`

- [ ] **Step 1: 创建 visualization/__init__.py**

```python
from .pmf_plot import plot_pmf
from .cdf_plot import plot_cdf
from .time_series_plot import plot_time_series

__all__ = ['plot_pmf', 'plot_cdf', 'plot_time_series']
```

- [ ] **Step 2: 创建 visualization/pmf_plot.py**

```python
import matplotlib.pyplot as plt
import numpy as np
from typing import List, Dict, Any, Optional


def plot_pmf(
    values: List[float],
    bins: int = 20,
    title: str = "Probability Mass Function",
    xlabel: str = "Value",
    ylabel: str = "Probability",
    save_path: Optional[str] = None,
) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 6))
    hist, edges = np.histogram(values, bins=bins)
    pmf = hist / len(values) if len(values) > 0 else []
    bin_centers = (edges[:-1] + edges[1:]) / 2

    ax.bar(bin_centers, pmf, width=edges[1] - edges[0], alpha=0.7, edgecolor='black')
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(axis='y', alpha=0.3)

    if save_path:
        fig.savefig(save_path)
    return fig
```

- [ ] **Step 3: 创建 visualization/cdf_plot.py**

```python
import matplotlib.pyplot as plt
import numpy as np
from typing import List, Optional


def plot_cdf(
    values: List[float],
    title: str = "Cumulative Distribution Function",
    xlabel: str = "Value",
    ylabel: str = "Cumulative Probability",
    save_path: Optional[str] = None,
) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 6))
    sorted_values = np.sort(values)
    cdf = np.arange(1, len(sorted_values) + 1) / len(sorted_values)

    ax.plot(sorted_values, cdf, drawstyle='steps-post', linewidth=2)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(alpha=0.3)
    ax.set_ylim(0, 1)

    if save_path:
        fig.savefig(save_path)
    return fig
```

- [ ] **Step 4: 创建 visualization/time_series_plot.py**

```python
import matplotlib.pyplot as plt
from typing import List, Dict, Any, Optional


def plot_time_series(
    data: List[Dict[str, Any]],
    x_key: str = 'action_index',
    y_key: str = 'cumulative',
    title: str = "Time Series",
    xlabel: str = "Action Index",
    ylabel: str = "Cumulative Count",
    save_path: Optional[str] = None,
) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 6))
    x_values = [d[x_key] for d in data]
    y_values = [d[y_key] for d in data]

    ax.plot(x_values, y_values, linewidth=2, marker='o', markersize=3)
    ax.fill_between(x_values, y_values, alpha=0.3)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(alpha=0.3)

    if save_path:
        fig.savefig(save_path)
    return fig
```

- [ ] **Step 5: 创建测试 tests/visualization/test_plots.py**

```python
import pytest
import matplotlib
matplotlib.use('Agg')
from gacha_simulator.visualization import plot_pmf, plot_cdf, plot_time_series


def test_plot_pmf():
    fig = plot_pmf([1, 1, 2, 2, 2, 3], bins=3)
    assert fig is not None


def test_plot_cdf():
    fig = plot_cdf([1, 2, 3, 4, 5])
    assert fig is not None


def test_plot_time_series():
    data = [{'action_index': i, 'cumulative': i * 2} for i in range(10)]
    fig = plot_time_series(data)
    assert fig is not None
```

- [ ] **Step 6: 运行测试验证**

Run: `cd /workspace && python -m pytest tests/visualization/ -v`

Expected: 所有测试通过

---

### Task 8: GUI层

**Files:**
- Create: `gacha_simulator/gui/__init__.py`
- Create: `gacha_simulator/gui/main_window.py`
- Create: `gacha_simulator/gui/config_panel.py`
- Create: `gacha_simulator/gui/gacha_panel.py`
- Create: `gacha_simulator/gui/analysis_panel.py`
- Create: `gacha_simulator/main.py`

- [ ] **Step 1: 创建 gui/__init__.py**

```python
from .main_window import MainWindow

__all__ = ['MainWindow']
```

- [ ] **Step 2: 创建 gui/main_window.py**

```python
from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout
from PyQt6.QtCore import QTimer
from .config_panel import ConfigPanel
from .gacha_panel import GachaPanel
from .analysis_panel import AnalysisPanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("抽卡模拟器")
        self.setGeometry(100, 100, 1200, 800)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.config_panel = ConfigPanel(self)
        self.gacha_panel = GachaPanel(self)
        self.analysis_panel = AnalysisPanel(self)

        self.tabs.addTab(self.config_panel, "配置")
        self.tabs.addTab(self.gacha_panel, "抽卡")
        self.tabs.addTab(self.analysis_panel, "分析")

        self.gacha_panel.simulation_finished.connect(self.analysis_panel.update_results)
```

- [ ] **Step 3: 创建 gui/config_panel.py**

```python
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QSpinBox, QDoubleSpinBox, QPushButton, QGroupBox, QFormLayout
)
from PyQt6.QtCore import pyqtSignal


class ConfigPanel(QWidget):
    config_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        self.setLayout(layout)

        pool_group = QGroupBox("池子配置")
        pool_layout = QFormLayout()
        self.pool_combo = QComboBox()
        self.pool_combo.addItems(["标准池", "限定池", "兑换商店"])
        pool_layout.addRow("选择池子:", self.pool_combo)
        pool_group.setLayout(pool_layout)
        layout.addWidget(pool_group)

        strategy_group = QGroupBox("策略配置")
        strategy_layout = QFormLayout()
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["目标狩猎", "固定次数", "资源优化"])
        strategy_layout.addRow("选择策略:", self.strategy_combo)
        self.max_actions_spin = QSpinBox()
        self.max_actions_spin.setRange(1, 100000)
        self.max_actions_spin.setValue(100)
        strategy_layout.addRow("最大行动次数:", self.max_actions_spin)
        strategy_group.setLayout(strategy_layout)
        layout.addWidget(strategy_group)

        state_group = QGroupBox("初始状态")
        state_layout = QFormLayout()
        self.primogem_spin = QSpinBox()
        self.primogem_spin.setRange(0, 1000000)
        self.primogem_spin.setValue(1600)
        state_layout.addRow("原石:", self.primogem_spin)
        self.pity_spin = QSpinBox()
        self.pity_spin.setRange(0, 90)
        self.pity_spin.setValue(0)
        state_layout.addRow("保底计数:", self.pity_spin)
        state_group.setLayout(state_layout)
        layout.addWidget(state_group)

        layout.addStretch()
```

- [ ] **Step 4: 创建 gui/gacha_panel.py**

```python
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTextEdit, QLabel, QProgressBar, QGroupBox
)
from PyQt6.QtCore import QThread, pyqtSignal
import time


class SimulationThread(QThread):
    finished = pyqtSignal(list)
    progress = pyqtSignal(int)

    def __init__(self, service, initial_state):
        super().__init__()
        self.service = service
        self.initial_state = initial_state

    def run(self):
        history = self.service.run_simulation(self.initial_state)
        self.finished.emit(history)


class GachaPanel(QWidget):
    simulation_finished = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        self.setLayout(layout)

        control_group = QGroupBox("控制面板")
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("开始模拟")
        self.start_btn.clicked.connect(self.start_simulation)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        result_group = QGroupBox("结果预览")
        result_layout = QVBoxLayout()
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        result_layout.addWidget(self.result_text)
        result_group.setLayout(result_layout)
        layout.addWidget(result_group)

    def start_simulation(self):
        from gacha_simulator.service import GachaService
        from gacha_simulator.core import GachaState, Pool, Reward, Strategy, StopCondition, TargetCardSet
        from gacha_simulator.core.action import DrawAction

        pool = Pool('standard', 'Standard', {'primogem': 160}, [
            (Reward('ssr', 'SSR', {'items': 1}), 0.006),
            (Reward('sr', 'SR', {'items': 1}), 0.051),
            (Reward('r', 'R', {'items': 1}), 0.943),
        ])

        class DemoStrategy(Strategy):
            lookahead = None
            def description(cls): return "Demo"
            def select_action(self, state, history, current_pools, future, target_cards, stop):
                if len(history) >= 100:
                    from gacha_simulator.core.action import WaitAction
                    return WaitAction(0)
                if not state.can_afford({'primogem': 160}):
                    from gacha_simulator.core.action import WaitAction
                    return WaitAction(3600)
                return DrawAction('standard')

        class DemoStop(StopCondition):
            def check(self, state, history): return len(history) >= 100
            def description(self): return "100次"

        state = GachaState(resources={'primogem': 16000})
        service = GachaService([pool], DemoStrategy(), DemoStop(), TargetCardSet([]))

        self.thread = SimulationThread(service, state)
        self.thread.finished.connect(self.on_simulation_finished)
        self.thread.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def on_simulation_finished(self, history):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.simulation_finished.emit(history)

        draw_history = [iv for iv in history if iv.action_type == 'draw']
        ssr_count = sum(1 for iv in draw_history if iv.card_id == 'ssr')
        self.result_text.append(f"总抽卡次数: {len(draw_history)}")
        self.result_text.append(f"SSR数量: {ssr_count}")
        self.result_text.append(f"SSR概率: {ssr_count/len(draw_history)*100:.2f}%")
```

- [ ] **Step 5: 创建 gui/analysis_panel.py**

```python
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGroupBox, QComboBox, QLabel
)
from PyQt6.QtCore import Qt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class AnalysisPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()
        self.setLayout(layout)

        control_group = QGroupBox("分析控制")
        control_layout = QHBoxLayout()
        self.type_combo = QComboBox()
        self.type_combo.addItems(["PMF", "CDF", "时间序列"])
        control_layout.addWidget(QLabel("图表类型:"))
        control_layout.addWidget(self.type_combo)
        self.plot_btn = QPushButton("生成图表")
        self.plot_btn.clicked.connect(self.generate_plot)
        control_layout.addWidget(self.plot_btn)
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)

        self.canvas = FigureCanvasQTAgg(Figure(figsize=(10, 6)))
        layout.addWidget(self.canvas)

        self.history_data = []

    def update_results(self, history):
        self.history_data = history

    def generate_plot(self):
        if not self.history_data:
            return
        from gacha_simulator.visualization import plot_pmf, plot_cdf, plot_time_series
        chart_type = self.type_combo.currentText()
        self.canvas.figure.clear()
        ax = self.canvas.figure.add_subplot(111)

        if chart_type == "PMF":
            values = [1 if iv.card_id == 'ssr' else 0 for iv in self.history_data if iv.action_type == 'draw']
            from gacha_simulator.visualization import plot_pmf
            plot_pmf(values, title="SSR出率分布")
        elif chart_type == "CDF":
            draw_indices = [i for i, iv in enumerate(self.history_data) if iv.action_type == 'draw']
            if draw_indices:
                plot_cdf(draw_indices, title="累计抽卡CDF")
        self.canvas.draw()
```

- [ ] **Step 6: 创建 main.py**

```python
import sys
from PyQt6.QtWidgets import QApplication
from gacha_simulator.gui import MainWindow


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
```

- [ ] **Step 7: 运行GUI测试验证**

Run: `cd /workspace && python -c "from gacha_simulator.gui import MainWindow; print('GUI import OK')"`

Expected: 无错误输出

---

## Phase 4: 测试框架和项目配置

### Task 9: 测试框架和项目配置

**Files:**
- Create: `pytest.ini` 或 `pyproject.toml`
- Create: `tests/conftest.py`
- Create: `tests/__init__.py`
- Modify: 各个目录添加 `__init__.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=45", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "gacha_simulator"
version = "0.1.0"
description = "A flexible gacha simulation system"
requires-python = ">=3.10"
dependencies = [
    "PyQt6>=6.0",
    "numpy>=1.20",
    "matplotlib>=3.5",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

- [ ] **Step 2: 创建 tests/conftest.py**

```python
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
```

- [ ] **Step 3: 运行完整测试**

Run: `cd /workspace && python -m pytest tests/ -v --tb=short`

Expected: 所有核心测试通过

---

## 实现顺序

1. **Task 1**: 基础数据结构 (core/)
2. **Task 2**: 保底机制
3. **Task 3**: 策略、停止条件、资源获取
4. **Task 4**: 广义出率、时间表、目标卡
5. **Task 5**: 生成器模块
6. **Task 6**: 服务层（GachaService, AnalysisService, ConfigService, **BatchService**）
7. **Task 7**: 可视化
8. **Task 8**: GUI层
9. **Task 9**: 测试框架

---

## 批量模拟说明

统计分析需要进行多次模拟。BatchService 支持：

1. **固定条件模拟**: 多次模拟使用相同的初始条件
2. **随机条件模拟**: 每次模拟使用随机生成的初始条件
3. **变体对比模拟**: 对比不同条件下的模拟结果

### 使用示例

```python
# 创建服务工厂
def create_service():
    return GachaService(pools, strategy, stop_condition, target_cards)

batch_service = BatchService(create_service)

# 固定条件：1000次相同条件模拟
variant1 = ConditionGenerator.fixed_state({'primogem': 16000}, {'ssr': 0})

# 随机条件：每次初始保底计数随机
variant2 = ConditionGenerator.random_resources({'primogem': (10000, 20000)})

# 蒙特卡洛采样
variant3 = ConditionGenerator.monte_carlo_sampling({'primogem': 16000}, variance=0.3)

# 运行批量模拟
results = batch_service.run_batch(
    variants=[variant1, variant2, variant3],
    config=BatchConfig(simulations_per_variant=1000, seed=42),
)

# 分析结果
for result in results:
    all_ssr_counts = [sum(1 for iv in h if iv.card_id == 'ssr') for h in result.histories]
    print(f"{result.variant_name}: 平均SSR = {sum(all_ssr_counts)/len(all_ssr_counts):.2f}")
```

---

**Plan complete!** 文件保存在 `docs/superpowers/plans/2026-05-07-gacha-simulator-implementation-plan.md`
