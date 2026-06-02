# 退路方案搜索 — 设计文档

## 1. 概述

### 1.1 目标

基于脆弱性分析的结果，搜索"补救方案"：当某池结束时资源剩余处于脆弱区间（大概率失败），找到使成功率恢复至阈值以上的最优策略组合。

### 1.2 补救手段

三种可组合的补救手段：
1. **增加额外资源**：在脆弱池结束时注入额外资源
2. **减少目标卡**：放弃部分后续目标卡
3. **组合**：同时调整资源和目标卡，描绘 Pareto 前沿

### 1.3 核心机制

从指定池结束时刻的状态出发，只模拟后续池子：
- 初始资源 = VI 资源值（基准）+ 搜索算法找到的额外资源（变量）

  **VI 资源值**是固定的"糟糕情况基准"——比如脆弱区间均值是 2509，代表"第3池结束时资源剩余约 2509"。

  **额外资源**是搜索算法要找的变量——"在这个糟糕基础上，我还需要注入多少资源才能恢复成功率"。

  举个例子：
  - VI 均值 = 2509（第3池结束时资源剩余约 2509，处于脆弱区间）
  - 搜索发现：需要额外 12000 资源才能达到 95% 成功率
  - 截断模拟的初始资源 = 2509 + 12000 = 14509
- 初始时间 = 指定池结束时间
- 保底水位 = 用户指定（默认 0，可参考统计数据）
- 只模拟指定池之后的池子

## 2. 架构设计

### 2.1 方案选择：截断配置 + 扩展数据

**不修改核心模拟引擎**，而是构造"截断 ConfigStore"复用现有 `run_batch_parallel` 接口。

原理：将"从第 N 池结束时刻开始模拟后续池"转化为"构造一个新配置，只包含第 N+1 池及之后的池，初始资源为 VI 资源值，起始日偏移到第 N 池结束日"。

### 2.2 数据流

```
脆弱性分析结果 (VulnerabilityAnalysisResult)
    │
    ├─ 用户选择: 池子、资源值、保底水位
    │
    ▼
构造截断配置 (RetreatConfigBuilder)
    │  输入: 原始 ConfigStore + 池ID + 资源值 + 保底初始值 + 起始日偏移
    │  输出: 新 ConfigStore（只含后续池、偏移后的资源增益规则）
    │
    ▼
搜索引擎 (RetreatSearchEngine)
    │  模式1: 最少额外资源搜索（复用资源搜索二分逻辑）
    │  模式2: 最多目标卡搜索（复用后退法逻辑）
    │  模式3: Pareto 前沿（模式1+模式2 联合搜索）
    │
    ▼
搜索结果 (RetreatSearchResult)
    │  Pareto 点集: [(额外资源, 目标卡集合, 成功率), ...]
    │
    ▼
可视化 (Pareto 前沿图 + 详细表格)
```

### 2.3 关键数据结构

#### 扩展脆弱性分析输出

在 `PoolVulnerabilityResult` 中新增字段：

```python
@dataclass
class PoolVulnerabilityResult:
    # ... 现有字段 ...
    pity_stats_at_pool_end: Dict[str, PityStatSnapshot]  # 新增

@dataclass
class PityStatSnapshot:
    counter_name: str
    mean: float
    median: float
    p25: float
    p75: float
    # 仅统计失败模拟在 VI 范围内的保底计数器分布
```

在 `run_simulation_compact` 返回结果中新增：

```python
# pool_end_pity_states: Dict[pool_id, Dict[counter_name, int]]
# 记录每个池结束时的保底计数器快照
```

#### 截断配置构建器

```python
class RetreatConfigBuilder:
    @staticmethod
    def build(
        original_store: ConfigStore,
        from_pool_id: str,
        initial_resources: Dict[str, float],
        pity_counter_init: Dict[str, int],
    ) -> ConfigStore:
        """
        构造截断配置：
        1. 只保留 from_pool_id 之后的池子
        2. 池子的 start_day/end_day 减去 from_pool 结束日
        3. initial_resources 设为指定值
        4. pity.counter_init 设为指定值
        5. 资源增益规则的 day_override 日期偏移
        """
```

#### 搜索结果

```python
@dataclass
class RetreatSearchPoint:
    extra_resource: float           # 额外资源量
    target_specs: Dict[str, int]    # 目标卡集合
    success_probability: float      # 成功率

@dataclass
class RetreatSearchResult:
    from_pool_id: str
    base_resource: float            # VI 资源值（不含额外）
    pity_init: Dict[str, int]       # 保底初始值
    search_mode: str                # 'resource' / 'target' / 'pareto'
    points: List[RetreatSearchPoint]  # Pareto 前沿点集
    resource_only_result: Optional[ResourceSearchResult]  # 纯资源搜索结果
    target_only_result: Optional[BackwardResult]          # 纯目标卡搜索结果
```

## 3. 搜索算法

### 3.1 最少额外资源搜索

复用现有 `ResourceSearchWorker` 的二分搜索逻辑，但：
- 使用截断配置而非原始配置
- 搜索的初始资源 = VI 资源值 + extra_resource
- 下界 = 0（无额外资源），上界自动翻倍搜索

### 3.2 最多目标卡搜索

复用后退法逻辑，但：
- 使用截断配置
- 初始资源 = VI 资源值（无额外）
- 从完整目标卡集合开始，逐步移除最不重要的卡

### 3.3 Pareto 前沿搜索

**关键洞察**：缩减目标卡后资源需求也会减少，因此不能独立搜索再组合。

算法：
1. 先做纯资源搜索（固定完整目标卡集合），得到 `R_full`（最少额外资源，即 VI 资源值之上还需多少）
2. 用后退法逐步移除目标卡，每移除一张卡后：
   a. 用资源搜索找到当前目标卡集合的最少额外资源 `R_reduced`
   b. 记录 Pareto 点 `(R_reduced, 当前目标卡集合, 成功率)`
3. 连接所有 Pareto 点形成前沿曲线

这样每个 Pareto 点都是"在该目标卡集合下的真实最少额外资源"，而非近似。

**计算量控制**：后退法最多移除 N 张卡（N = 目标卡数量），每次移除后做一次资源搜索（约 10-20 次模拟），总计约 N × 15 次批量模拟。

## 4. UI 设计

### 4.1 新增独立 Tab 页："退路方案搜索"

布局：左右分栏（QSplitter）

**左栏：配置区**

```
┌─ 起始状态 ──────────────────────────┐
│ 起始池: [下拉选择] ▼                │
│   (只显示有脆弱区间的池)             │
│                                      │
│ 资源剩余值:                          │
│   ○ VI下限 (0)  ○ VI均值 (2509)     │
│   ○ VI上限 (5014) ○ 25%分位 (1200)  │
│   ○ 50%分位 (2400) ○ 75%分位 (3800) │
│   ○ 手动输入: [______]              │
│                                      │
│ 保底水位:                            │
│   ┌──────────────────────────────┐   │
│   │ 计数器名  均值  中位  25% 75%│   │
│   │ pity_soft  35.2  30   15  52│   │
│   │ ...                          │   │
│   └──────────────────────────────┘   │
│   初始值: [0] (默认0，可手动修改)     │
└──────────────────────────────────────┘

┌─ 搜索配置 ──────────────────────────┐
│ 搜索模式:                            │
│   ○ 最少额外资源                     │
│   ○ 最多目标卡                       │
│   ● Pareto前沿                       │
│                                      │
│ 成功率阈值: [0.95]                   │
│ 每步模拟次数: [500]                  │
│ 并行数: [4]                          │
│ GDR指标: [下拉] 阈值: [1.0]         │
└──────────────────────────────────────┘

[开始搜索]  [停止]
进度条...
状态: 就绪
```

**右栏：结果区**

```
┌─ 搜索结果 ──────────────────────────┐
│                                      │
│ [Pareto前沿图]                       │
│   X轴: 额外资源                      │
│   Y轴: 目标卡数量                    │
│   每个点可点击查看详情                │
│                                      │
└──────────────────────────────────────┘

┌─ 详细结果表 ────────────────────────┐
│ 额外资源 | 目标卡集合 | 成功率 | 详情│
│ 12000   | A×1,B×1   | 96.2% | [查看]│
│ 8000    | A×1       | 95.1% | [查看]│
│ 0       | (无)      | 100%  | [查看]│
└──────────────────────────────────────┘
```

### 4.2 与脆弱性分析的联动

- 脆弱性分析完成后，"起始池"下拉框自动填充有脆弱区间的池子
- 选择池子后，资源值预设选项自动更新为该池的 VI 统计数据
- 保底水位表格自动填充该池结束时的保底统计

### 4.3 数据来源

退路方案搜索需要脆弱性分析的结果作为输入。如果用户尚未运行脆弱性分析，应提示先运行。

## 5. 实现步骤

### Task 1: 扩展模拟结果 — 记录池结束时的保底状态

修改 `run_simulation_compact` 在记录 `pool_end_resources` 的同时记录 `pool_end_pity_states`。

修改 `compute_vulnerability_analysis` 收集并计算保底计数器的统计分布（均值、中位数、分位数），存入 `PoolVulnerabilityResult.pity_stats_at_pool_end`。

### Task 2: 实现截断配置构建器

新建 `core/retreat_config.py`，实现 `RetreatConfigBuilder.build()`：
- 过滤池子：只保留指定池之后的
- 偏移时间：start_day/end_day 减去起始池结束日
- 设置初始资源
- 设置保底初始计数器
- 偏移 day_override 日期

### Task 3: 实现退路搜索引擎

新建 `core/retreat_search.py`，实现三种搜索模式：
- `search_min_resource()`: 二分搜索最少额外资源
- `search_max_targets()`: 后退法搜索最多目标卡
- `search_pareto()`: Pareto 前沿联合搜索

### Task 4: 实现退路方案搜索面板

新建 `gui/retreat_search_panel.py`，包含：
- 配置区（起始状态 + 搜索配置）
- 结果区（Pareto 图 + 详细表格）
- 与脆弱性分析结果联动

### Task 5: 集成到主窗口

在 `MainWindow` 中添加新 tab 页"退路方案搜索"，连接信号。

### Task 6: 测试与验证

单元测试 + 集成测试。

## 6. 风险与注意事项

1. **资源增益时间偏移**：截断配置中 `day_override` 的日期需要正确偏移，否则资源获取会错位
2. **保底计数器统计**：需要在脆弱性分析的模拟过程中额外记录保底快照，增加少量内存开销
3. **Pareto 搜索计算量**：每移除一张卡做一次资源搜索，目标卡多时计算量较大。可通过减少每步模拟次数来加速
4. **策略适配**：截断配置中的策略需要正确处理"只追后续池的卡"这一约束，现有 smart 策略应能自动适配
