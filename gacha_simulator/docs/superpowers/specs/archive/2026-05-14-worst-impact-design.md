# 最差后期影响分析 — 设计文档（修订版 v3）

## 1. 设计意图解读

### 1.1 核心思想

"最差后期影响"分析回答的是：**在当前策略下，如果运气不好（处于条件分布的下尾），全部池子抽完后还剩多少资源？这些剩余资源能支撑多少个"新池子"？**

关键区别：
- **不是**考察"已有的后续池子还能抽几个"
- **而是**考察"全部抽完后，剩余资源还能抽多少个新生成的池子"
- 新池子 = 与已有池子同分布的假设池子

### 1.2 为什么用最终资源而非每个池子的资源？

最差后期影响是"后期影响"——只关心**全部抽完后的最终结果**。

- 从批量模拟结果中，只提取 `final_resources`（最终资源）
- 不提取 `pool_end_resources`（每个池子结束时的资源）
- 简化数据流，减少复杂度

### 1.3 条件分布

仍然条件于成功/失败情形：
- 只取失败情形的最终资源分布（默认）
- 在该分布中取下尾分位数作为保守估计
- 成功/失败判断基于 `card_counts` 字典与 `target_specs` 的比较

### 1.4 两个分析维度

| 维度 | 问题 | 计算方法 |
|------|------|----------|
| **大保底资源占比** | 剩余资源能覆盖多少次大保底？ | 剩余资源 / 大保底所需资源 |
| **可抽新池子数** | 用保守资源能抽多少个新池子？ | 分布+期望（PMF + E[X]） |

> v3 变更：删除了"阈值连续"模式。原因见 §3.2。

---

## 2. 数据模型

### 2.1 输入数据

```python
@dataclass
class WorstImpactInput:
    simulation_results: List[dict]      # 批量模拟结果
    target_specs: Dict[str, int]        # 目标卡需求 {card_id: quantity}
    condition: str                       # 'success' | 'failure' | 'all'
    alpha: float                         # 下尾分位数 (默认 0.05)
    num_simulations: int                 # 每步模拟次数 (默认 500)
```

### 2.2 关键数据结构

```python
sim_result = {
    'final_resources': {'draw_resource': 500, ...},
    'card_counts': {'char_a': 1, 'char_b': 0, ...},
    'pool_end_pity_states': {'pool_1': {'counters': {'pity': 45}}},
    ...
}
```

### 2.3 条件资源分布构建

```python
def _check_success_from_counts(card_counts: Dict[str, int],
                                target_specs: Dict[str, int]) -> bool:
    for card_id, qty in target_specs.items():
        if card_counts.get(card_id, 0) < qty:
            return False
    return True


class ConditionalResourceDistribution:
    def __init__(self, simulation_results, target_specs,
                 resource='draw_resource'):
        self.success_resources: List[float] = []
        self.failure_resources: List[float] = []

        for r in simulation_results:
            is_success = _check_success_from_counts(
                r.get('card_counts', {}), target_specs
            )
            final_res = r.get('final_resources', {})
            res_val = final_res.get(resource, 0.0)

            if is_success:
                self.success_resources.append(res_val)
            else:
                self.failure_resources.append(res_val)
```

---

## 3. 分析维度的详细设计

### 3.1 维度一：大保底资源占比

**计算**：
```python
def compute_pity_coverage(resource, pity_cost):
    if pity_cost <= 0:
        return float('inf')
    return resource / pity_cost
```

**大保底成本**：
- 从保底配置读取 `end` 参数（如 90）
- 乘以抽卡成本（如 160）
- `pity_cost = end * cost_per_draw`
- 注意：`PityDef.params` 类型为 `Dict[str, str]`，需要 `int()` 转换

---

### 3.2 维度二：可抽新池子数（分布+期望）

**核心问题**：用保守估计的最终资源，能成功抽取多少个"新池子"？

**新池子的定义**：
- 与已有池子同分布（使用第一个池子的 `PoolEntry.distribution`）
- 包含限定SSR作为目标卡
- 有相同的保底机制
- **每个新池子是独立的 `Pool` 对象**（不同 id、独立时间范围）

**新池子的构造**：
```python
def _create_new_pool(self, pool_index: int):
    pid = f'_worst_impact_pool_{pool_index}'
    pool_duration = (end_day - start_day) * DAY
    pool = Pool(
        id=pid,
        name=f'新池子#{pool_index}',
        cost=parsed_cost,
        rewards=rewards,
        available_from=0,
        available_until=pool_duration,
    )
    return pool
```

**目标卡提取**：
```python
def _build_target_card_set(self, pool_id: str):
    for card_id in self._featured_ids:
        targets.append(TargetCard(
            card_id=card_id,
            pool_ids=[pool_id],
            quantity_needed=1,
        ))
    return TargetCardSet(targets)
```

**算法**：

```python
def _compute_pool_distribution(self, resource, pity_state,
                                num_simulations, progress_callback=None):
    success_counts = defaultdict(int)

    for sim_idx in range(num_simulations):
        current_resource = resource
        current_pity = dict(pity_state)
        consecutive = 0
        pool_index = 0

        while current_resource > 0:
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
                current_pity = result['final_pity_state']
                pool_index += 1
            else:
                break

        success_counts[consecutive] += 1

    distribution = {k: count / n for k, count in sorted(success_counts.items())}
    expected = sum(k * prob for k, prob in distribution.items())
    return {'distribution': distribution, 'expected': expected}
```

**结果数据结构**：

```python
@dataclass
class WorstImpactResult:
    worst_resource: float
    pity_coverage: float
    pool_distribution: Dict[int, float] = field(default_factory=dict)
    expected_pools: float = 0.0

    def get_p_ge(self, k: int) -> float:
        """P(X >= k)"""
        return sum(p for kk, p in self.pool_distribution.items() if kk >= k)

    def get_max_consecutive_at_threshold(self, threshold: float) -> int:
        """给定阈值推导最大连续数"""
        for k in sorted(self.pool_distribution.keys(), reverse=True):
            if self.get_p_ge(k) >= threshold:
                return k
        return 0
```

**关于"阈值连续"问题**：

原设计有两种模式（分布+期望 / 阈值连续），v3 删除了阈值连续模式。

删除原因：模式B用平均剩余资源做确定性近似，丢失了剩余资源的不确定性信息，结果不如模式A准确。而模式A的分布 P(X≥k) 已经能直接回答阈值问题——找到最大的 k 使得 P(X≥k) ≥ threshold 即可。因此模式B在准确性和信息量上都不如模式A，属于冗余设计。

用户如需回答"以95%把握至少能抽几个池子"，只需查看表格中 P(X≥k) 列，找到 P(X≥k) ≥ 95% 的最大 k。

---

## 4. 关于"链式模拟"

"链式模拟"就是**循环调用现有的普通模拟引擎**。

每次循环：
1. 用当前资源作为初始资源
2. 用当前保底状态作为初始保底
3. 调用 `GachaService.run_simulation_compact` 运行一次普通模拟
4. 如果成功，用结束时的资源和保底状态进入下一次循环
5. 如果失败，停止

没有新的"链式模拟引擎"，只有对现有引擎的循环调用。

---

## 5. 架构设计

### 5.1 分层原则

核心引擎 `worst_impact.py` 位于 `core/` 层，**不依赖** `gui/` 层。

在 core 层实现 `_TargetPoolEnd`（停止条件）和 `_DrawTargetStrategy`（抽卡策略），而非从 `gui.batch_simulator` 导入。

### 5.2 保底引擎构建

`PityEngine` 构造需要 `(pool_specs, pity_defs, behaviors)` 三个参数，参考 `batch_simulator._build_pity_engine_from_gui` 的实现。

### 5.3 模拟结果中的保底状态

`run_simulation_compact` 返回 `pool_end_pity_states`（非 `final_pity_state`），格式为 `{pool_id: {'counters': {counter_name: value}}}`。

---

## 6. UI 设计

### 6.1 面板布局

```
┌─────────────────────────────────────────────────────────────┐
│  最差后期影响分析                                              │
├──────────────────────────────┬──────────────────────────────┤
│  配置区                       │  结果区                       │
│  ┌────────────────────────┐  │  ┌────────────────────────┐  │
│  │ 条件选择                │  │  │ 结果摘要                │  │
│  │ ○ 全部情形              │  │  │  保守资源: 14400        │  │
│  │ ○ 成功情形              │  │  │  大保底覆盖: 1.00 倍    │  │
│  │ ● 失败情形              │  │  │  期望新池子数: 2.34     │  │
│  ├────────────────────────┤  │  └────────────────────────┘  │
│  │ 分位数 α               │  │  ┌────────────────────────┐  │
│  │  [5% ▼]                │  │  │ 大保底资源覆盖           │  │
│  ├────────────────────────┤  │  │  图表: 覆盖倍数           │  │
│  │ 模拟次数                │  │  └────────────────────────┘  │
│  │  [500]                 │  │  ┌────────────────────────┐  │
│  └────────────────────────┘  │  │ 新池子数分布             │  │
│  [开始分析]                   │  │  PMF 柱状图              │  │
│  进度条                       │  └────────────────────────┘  │
│                               │  ┌────────────────────────┐  │
│                               │  │ 详细数据表格             │  │
│                               │  │ k|P(X=k)|P(X>=k)|...  │  │
│                               │  └────────────────────────┘  │
└──────────────────────────────┴──────────────────────────────┘
```

> v3 变更：配置区删除了"分析模式"和"成功率阈值"选项，简化为只有条件、分位数、模拟次数三个配置项。

### 6.2 数据传递

```python
target_specs = {tc.card_id: getattr(tc, 'quantity', 1)
                for tc in getattr(self._store, 'target_cards', [])}
self.worst_impact_panel.set_simulation_results(results, target_specs)
```

### 6.3 结果展示

- PMF 柱状图：X轴=成功抽取新池子数k，Y轴=P(X=k)，标注期望值 E[X]
- 表格：k | P(X=k) | P(X>=k) | 累计概率 | 说明
- P(X≥k) 列可直接回答阈值问题

---

## 7. 测试策略

1. **`_check_success_from_counts`**：测试全达成、部分达成、空目标
2. **`ConditionalResourceDistribution`**：测试成功/失败筛选、分位数计算
3. **`WorstImpactResult`**：测试数据类构造、`get_p_ge`、`get_max_consecutive_at_threshold`
4. **集成**：测试无资源→{0:1.0}、资源充足→分布右偏

---

## 8. 文件结构

```
gacha_simulator/
├── core/
│   ├── worst_impact.py          # 核心分析引擎
│   └── __init__.py              # 导出
├── gui/
│   ├── worst_impact_panel.py    # UI 面板
│   └── main_window.py           # 集成
└── tests/
    └── core/
        └── test_worst_impact.py # 测试
```

---

## 修订记录

| 日期 | 修订内容 |
|------|----------|
| 2026-05-14 | 初始版本 |
| 2026-05-14 | v2 修订：修复12项 API/架构问题 |
| 2026-05-14 | **v3 修订**：删除模式B（阈值连续），只保留分布+期望 |
| | 原因：模式B用确定性近似丢失不确定性，且模式A的 P(X≥k) 已能回答阈值问题 |
| | `WorstImpactResult` 新增 `get_p_ge(k)` 和 `get_max_consecutive_at_threshold(threshold)` |
| | UI 删除模式选择和成功率阈值配置 |
