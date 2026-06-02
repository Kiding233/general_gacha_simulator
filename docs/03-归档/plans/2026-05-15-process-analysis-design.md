# 过程分析功能设计（v6）

> 基于 v5 设计文档更新，新增条件 GDR 分布设计

## 1. 目标

记录每个模拟样本在每个池子的出卡过程，为每个池子标注**两个独立的维度**——事件类型和成败状态，然后对这两个维度的交叉进行四种统计分析。

## 2. 核心概念：事件与成败是平行的两个维度

每个池子有两个独立的标签：

| 维度 | 取值 | 判定依据 |
|------|------|---------|
| **事件**（A 维度） | 抽卡池5种 + 兑换池2种 + 资源池2种 | 策略行为 + 抽卡结果 |
| **成败**（B 维度） | 成功/失败 | 池子级别 GDR 阈值判定 |

**两者独立**：一个池子可以是"保底前出 + 失败"（出了目标卡但 GDR 未达标），也可以是"抽了没出 + 成功"（未出目标卡但资源剩余等 GDR 指标达标）。

**注意**：事件中的"保底出"/"提前出"描述的是"出了目标卡"这个事实，这**不等于**"成功"——成功由 GDR 阈值独立判定。

## 3. 事件定义（A 维度）

### 3.1 抽卡池事件类型

| 事件类型 | 编码 | 含义 | 附加数据 |
|---------|------|------|---------|
| 忽略 | `ignore` | 本池没有未完成目标卡，策略直接等待过去 | 无 |
| 跳过 | `skip` | 本池有未完成目标卡，但策略选择不抽，等到池子结束 | 无 |
| 保底出 | `pity_hit` | 在保底机制触发时抽到目标卡 | `pity_name`（具体保底机制名），`draws`（本池总抽卡数） |
| 提前出 | `early_hit` | 在保底触发前抽到目标卡 | `draws`（本池总抽卡数），`counter_max`（保底计数器最大值） |
| 没出 | `miss` | 抽了卡但没抽到目标卡 | `draws`（本池总抽卡数） |

**判断逻辑**：
- **忽略**：池子可用期间，策略从未对该池执行 DrawAction，且该池没有未完成目标卡
- **跳过**：池子可用期间，策略从未对该池执行 DrawAction，但该池有未完成目标卡
- **保底出**：池子可用期间执行了 DrawAction，且目标卡是在某保底机制触发的那次抽卡中获得的
- **提前出**：池子可用期间执行了 DrawAction，且目标卡在保底触发前获得
- **没出**：池子可用期间执行了 DrawAction，但始终未获得目标卡

**保底名区分**：
- `raw` 模式：区分具体保底机制名，如 `pity_hit:ssr_soft` vs `pity_hit:ssr_hard`
- 其他模式（sequence/set/count_set/custom）：不区分，统一为 `pity_hit`

### 3.2 兑换池事件类型

| 事件类型 | 编码 | 含义 |
|---------|------|------|
| 兑换 | `exchange` | 成功兑换了目标卡 |
| 未兑换 | `no_exchange` | 未进行兑换 |

**判断逻辑**：
- **兑换**：策略对该兑换池执行了 DrawAction（兑换操作在模拟中也是一次 DrawAction）
- **未兑换**：策略未对该兑换池执行 DrawAction（有目标卡但没兑换，或没有目标卡不需要兑换）

**兑换池识别**：`Pool.is_exchange = True`（`core/pool.py:142`）。兑换池的 `draw()` 直接返回固定兑换卡（概率 1.0），不走随机抽卡逻辑。

### 3.3 资源池事件类型

| 事件类型 | 编码 | 含义 |
|---------|------|------|
| 抽资源 | `resource_draw` | 从资源池抽了卡 |
| 资源忽略 | `resource_ignore` | 未从资源池抽卡 |

**注意**：资源池的"忽略"（`resource_ignore`）是独立的事件类型，不与抽卡池的"忽略"（`ignore`）合计。

**资源池识别**：当前代码中**没有** `is_resource` 标记字段。资源池通过配置中的 `pool_type`（如 `type: 资源`）和池子 ID 前缀推断，但这些信息**不会进入 compact 数据**。需要在 compact 中新增 `pool_types: Dict[str, str]` 字段才能在过程分析中区分。

### 3.4 事件类型汇总

| 池子类型 | 事件类型 | 编码 | 当前实现 |
|---------|---------|------|---------|
| 抽卡池 | 忽略 | `ignore` | ✅ |
| 抽卡池 | 跳过 | `skip` | ✅ |
| 抽卡池 | 保底出 | `pity_hit` | ✅ |
| 抽卡池 | 提前出 | `early_hit` | ✅ |
| 抽卡池 | 没出 | `miss` | ✅ |
| 兑换池 | 兑换 | `exchange` | ❌ 未实现 |
| 兑换池 | 未兑换 | `no_exchange` | ❌ 未实现 |
| 资源池 | 抽资源 | `resource_draw` | ❌ 未实现 |
| 资源池 | 资源忽略 | `resource_ignore` | ❌ 未实现 |

## 4. 成败定义（B 维度）

### 4.1 两种成败定义

代码中存在两种"成功"定义，在不同分析模块中使用：

| 定义 | 代码 | 含义 | 使用位置 |
|------|------|------|---------|
| 整体成功 `is_success` | `val >= threshold`（整体GDR） | 最终目标达成率是否≥阈值 | AB 的 `overall_success_prob`、BA 的条件概率分组 |
| 池子成功 `pool_success[pid]` | `pool_gdr_val >= threshold`（池子GDR） | 单池GDR是否≥阈值 | BB 的模式表、BB 的从未失败/从未成功概率、AB 的 `success_distribution` |

**设计意图**：两种定义各有用途，混用是合理的：
- BB 分析关注池子级别的成败分布，所以用池子级定义
- AB/BA 分析关注"知道事件后，最终结果的概率"，所以用整体级定义
- AB 的 `success_distribution` 提供池子级别的细节分布，`overall_success_prob` 提供最终结果概率，两者互补

### 4.2 池子级别 GDR 计算

每个池子的"成功/失败"基于池子级别 GDR 值与阈值比较判定。

**两种计算方式，让用户在 UI 中选择：**

**方式一：截止到该池子结束的全部历史（累积快照）**
- 使用从模拟开始到该池子结束的所有抽卡记录计算 GDR
- 理论意义：该池子结束时，整体进度的 GDR 评估
- 数据来源：`DrawSequenceExtractor._update_cumulative` 产生的累积快照
- 计算方式：`compute_gdr_from_cumulative(cum_snapshot, target_specs, gdr_key)`

**方式二：仅在该池子产生的历史（单池快照）**
- 只使用该池子内的抽卡记录计算 GDR
- 理论意义：该池子本身的 GDR 表现
- 数据来源：从 `extract_aggregate` 的池子级别数据构建 pseudo_compact
- 计算方式：构建 pseudo_compact 后调用 `compute_gdr_from_compact`

### 4.3 整体成败

整体模拟的成败使用 `compute_gdr_from_compact` 从 aggregate 数据判定，与池子级别成败独立。

## 5. 四种分析：A × B 交叉

两个维度（事件 A、成败 B）各有两种统计方向（无条件统计、条件统计），交叉得到四种分析：

```
A（事件维度）× B（成败维度）
├── AA：P(事件模式) — 纯事件统计，不看成败
├── BB：P(成败模式) — 纯成败统计，不看事件
├── AB：P(成败模式 | 事件模式) — 给定事件，成败的概率
└── BA：P(事件模式 | 成败模式) — 给定成败，事件的概率
```

### 5.1 AA：纯事件统计

统计每种事件组合出现的概率：

```
P(event_pattern) = count(event_pattern) / N
```

### 5.2 BB：纯成败统计

统计每种成败组合出现的概率：

```
P(success_pattern) = count(success_pattern) / N
```

统计项：

| 统计项 | 公式 | 成功定义 |
|--------|------|---------|
| P(成败模式) | count(pattern) / N | 池子级 |
| P(从未成功) | count(所有池子都失败) / N | 池子级 |
| P(从未失败) | count(所有池子都成功) / N | 池子级 |
| P(特定池子成功) | count(pool_k 成功) / N | 池子级 |

### 5.3 AB：事件 → 成败（给定事件，成败的概率）

**两个统计量**：

| 字段 | 成功定义 | 回答的问题 |
|------|---------|-----------|
| `overall_success_prob` | 整体级 `is_success` | "给定这个事件模式，最终整体成功的概率是多少？" |
| `success_distribution` | 池子级 `pool_success` | "给定这个事件模式，池子级别成败模式的完整分布是什么？" |

**理论意义**：
- `overall_success_prob`：回答"如果某个池子提前出了，整体成功的概率是多少？"
- `success_distribution`：回答"保底出的池子本身成功率是多少？提前出但整体失败的样本中，池子级别的成败分布是什么样的？"

**当前状态**：`success_distribution` 已计算但 UI 未展示，是死字段。

### 5.4 BA：成败 → 事件（给定成败，事件的概率）

```
P(event_pattern | success) = count(event_pattern ∧ success) / count(success)
P(event_pattern | failure) = count(event_pattern ∧ failure) / count(failure)
```

条件概率分组基于整体成功 `is_success`。

## 6. 事件组合模式

### 6.1 事件组合模式（A 维度）— 5种

| 模式 | 编码 | 输出类型 | 保底名区分 | 说明 |
|------|------|---------|-----------|------|
| 原始轨迹 | `raw` | `Tuple[str, ...]` | ✅ 区分 | 含保底名和抽卡数 |
| 事件类型序列 | `sequence` | `Tuple[str, ...]` | ❌ 不区分 | 有序，忽略附加数据 |
| 事件类型集合 | `set` | `Tuple[str, ...]` | ❌ 不区分 | 无序，忽略附加数据 |
| 事件计数组合 | `count_set` | `Tuple[int, ...]` | ❌ 不区分 | 5种事件类型的计数元组 |
| 自定义模式 | `custom` | `Dict[str, str]` | ❌ 不区分 | 自定义约束分桶聚合 |

#### 自定义模式逻辑

每种事件类型可独立设置操作符（任意/=/≥/≤/>/<）和阈值 N：
- **任意**：该事件类型不参与模式键
- **非任意**：根据操作符分为两个桶（满足/不满足）
- 有约束时，模式键只包含非任意约束的事件类型字段
- 枚举所有 2^k 种桶组合，零样本组合也显示（count=0）

### 6.2 成败组合模式（B 维度）— 4种

| 模式 | 编码 | 输出类型 | 说明 |
|------|------|---------|------|
| 成败序列 | `sequence` | `Tuple[bool, ...]` | 有序 |
| 成败集合 | `set` | `Tuple[int, int]` | (成功数, 失败数) |
| 成败计数 | `count` | `int` | 成功池数 |
| 自定义模式 | `custom` | `str` | 操作符+N分桶 |

#### 成败自定义模式逻辑

操作符（=/≥/≤/>/<）+ 阈值 N，将成功池数分为两个桶，枚举所有桶，零样本桶也显示。

## 7. 数据采集

### 7.1 compact 数据中的池子类型信息

**当前状态**：compact 数据中**没有记录池子类型信息**（`is_exchange`、`pool_type` 等），只有 `pool_id`。

**兑换池识别**：`Pool.is_exchange = True`（`core/pool.py:142`）。兑换池在模拟中通过 `DrawAction` 执行兑换操作，`draw()` 直接返回固定兑换卡（概率 1.0），不走随机抽卡逻辑。compact 中兑换池的 `draw_pool_ids` 会出现该池 ID，`draw_pity` 为 False，`pool_card_counts` 会记录兑换卡。

**资源池识别**：当前代码中**没有** `is_resource` 标记字段。资源池通过配置中的 `pool_type`（如 `type: 资源`）和池子 ID 前缀推断，但这些信息**不会进入 compact 数据**。

**需要新增**：在 compact 中新增 `pool_types: Dict[str, str]` 字段，记录每个池子的类型（`draw`/`exchange`/`resource`），才能在过程分析中区分兑换池和资源池。

### 7.2 已有字段

| 字段 | 说明 | 状态 |
|------|------|------|
| `draw_pool_ids` | 每次抽卡的池子ID | ✅ |
| `draw_card_ids` | 每次抽卡的卡ID | ✅ |
| `draw_pity` | 每次抽卡是否触发保底 | ✅ |
| `draw_pity_names` | 每次抽卡触发的保底机制名 | ✅ |
| `draw_pity_counter_max` | 每次抽卡时该池保底计数器最大值 | ✅ |
| `pool_card_counts` | 每池每卡获得数量 | ✅ |
| `pool_draw_counts` | 每池抽卡次数 | ✅ |
| `pool_pity_counts` | 每池保底触发次数 | ✅ |
| `pool_types` | 每池类型 | ❌ 需新增 |

### 7.3 数据结构

```python
@dataclass
class PoolEvent:
    pool_id: str
    pool_type: str          # 'draw' / 'exchange' / 'resource'
    event_type: str         # 9种事件类型之一
    pity_name: Optional[str]
    draws: int
    counter_max: int

@dataclass
class SampleTrace:
    events: List[PoolEvent]           # A 维度：每个池子的事件
    pool_success: Dict[str, bool]     # B 维度：每个池子的成败
    is_success: bool                  # 整体成败
    gdr_value: float                  # 整体 GDR 值
    pool_gdr_values: Dict[str, float] # 每个池子的 GDR 值
```

## 8. UI 设计

### 8.1 配置区

| 配置项 | 控件 | 说明 |
|--------|------|------|
| GDR 指标 | ComboBox | 复用 `UNIFIED_GDR_REGISTRY` |
| 成功阈值 | DoubleSpinBox | 0.0-1.0，步长0.05 |
| 池子GDR方式 | ComboBox | 累积 / 单池 |
| 事件组合模式 | ComboBox | 序列/集合/计数组合/原始/自定义 |
| 事件自定义约束（5项） | 操作符ComboBox + N SpinBox × 5 | 保底出/提前出/没出/跳过/忽略 |
| 成败组合模式 | ComboBox | 计数/序列/集合/自定义 |
| 成败自定义约束 | 操作符ComboBox + N SpinBox | 选择"自定义模式"时显示 |

### 8.2 结果区（5个Tab）

| Tab | 名称 | 表格列 |
|-----|------|--------|
| Tab 1 | 事件统计 | 事件组合, 出现次数, 概率, 累计概率 |
| Tab 2 | 成败统计 | 成败模式, 出现次数, 概率, 累计概率 + 统计摘要 |
| Tab 3 | 事件→成败 | 事件组合, P(成功\|组合), P(失败\|组合), 出现次数, 成功数, 失败数 |
| Tab 4 | 成败→事件 | 事件组合, P(组合\|成功), P(组合\|失败), 比值, 出现次数 |
| Tab 5 | 轨迹详情 | 池子ID, 事件类型, 保底名, 抽卡数, 计数器最大值, 池GDR值, 池成败 |

## 9. 待定事项

1. ~~**池子级别 GDR 计算方式**~~：已实现两种方式
2. ~~**BB 分析中"整体成败"的定义**~~：BB 用池子级，AB/BA 用整体级，各有用途
3. **`success_distribution` 是否展示**：AB 分析中已计算但 UI 未展示，需决定是否添加展示列
4. **兑换池/资源池事件类型**：需新增 `pool_types` 字段到 compact 数据，然后实现 `exchange`/`no_exchange`/`resource_draw`/`resource_ignore` 事件推断
5. **`EVENT_TYPE_ORDER` 扩展**：当前只有抽卡池5种事件，需扩展为9种（加入 `exchange`/`no_exchange`/`resource_draw`/`resource_ignore`），`resource_ignore` 不与 `ignore` 合计
6. **条件 GDR 分布**：以事件组合为条件查看任意 GDR 指标的分布，是 AB 分析的连续扩展（B 维度从离散"成功/失败"扩展到连续"GDR 值分布"）。所有 13 种 GDR 指标均可行，详见实施计划 Task 9
