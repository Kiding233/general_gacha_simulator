# 过程分析功能实施计划（v8）

> 基于 v7 计划更新，新增 Task 9（条件 GDR 分布）、修复 GDR 阈值范围限制

## 设计逻辑

过程分析功能的核心是：为每个模拟样本的每个池子标注"事件"（A维度）和"成败"（B维度），然后对两个维度的交叉进行四种统计分析。

## 实施状态总览

| Task | 内容 | 状态 | 说明 |
|------|------|------|------|
| Task 1 | compact 新增保底名字段 | ✅ 完成 | `draw_pity_names` + `draw_pity_counter_max` |
| Task 2 | 数据结构 + 轨迹推断 + 池子GDR | ✅ 完成 | 双路径推断（raw compact + aggregate） |
| Task 3 | 四种统计分析 + 模式转换 | ✅ 完成 | 自定义模式 + 零样本枚举 |
| Task 4 | 过程分析面板 UI | ✅ 完成 | 5个Tab + 自定义约束控件 |
| Task 5 | 集成测试 + Bug修复 | ✅ 完成 | 修复10+个级联Bug |
| Task 6 | 成功定义一致性 | ✅ 确认设计合理 | 两种定义各有用途，非bug |
| Task 7 | 兑换池/资源池事件 | ❌ 未实现 | 需新增 `pool_types` 字段 + 4种事件推断 |
| Task 8 | `success_distribution` UI展示 | ❌ 未实现 | AB 分析中已计算但未展示 |

---

## Task 1：compact 新增保底名字段 ✅

**变更文件**：`service/gacha_service.py`

**已实现**：
- `draw_pity_names`：每次抽卡触发的保底机制名
- `draw_pity_counter_max`：每次抽卡时该池最接近触发的保底计数器值

**关键修复**：
1. 删除了重复的 `after_draw` 调用（原来在记录保底信息前后各调用一次，第一次会重置计数器导致读不到值）
2. `pdef.start_at` → `behavior.start_at`：`PityDefParsed` 没有 `start_at` 属性，必须通过 `_pity_engine.behaviors.get(pname)` 获取 `SoftPityBehavior` 对象
3. `pity_state.get(pname, 0)` → `pity_state.get(pname)`：`PityState.get()` 是自定义方法只接受1个参数

---

## Task 2：数据结构 + 轨迹推断 + 池子GDR ✅

**变更文件**：`core/process_trace.py`

**已实现**：
- `PoolEvent` dataclass：`pool_id`, `pool_type`, `event_type`, `pity_name`, `draws`, `counter_max`
- `SampleTrace` dataclass：`events`, `pool_success`, `is_success`, `gdr_value`, `pool_gdr_values`
- `infer_events(compact, target_ids)`：双路径推断
  - `_infer_from_draw_sequence`：使用 `draw_pool_ids` 逐抽推断（raw compact 路径）
  - `_infer_from_aggregate`：使用 `pool_draw_counts`/`pool_card_counts`/`pool_pity_counts` 推断（aggregate 路径）
- `compute_pool_gdr_cumulative`：方式一，使用累积快照
- `compute_pool_gdr_single_pool`：方式二，构建 pseudo_compact

**关键修复**：
- 原始 `infer_events` 只处理 raw compact（有 `draw_pool_ids`），但 `extract_aggregate` 不保留此字段，导致所有事件被识别为 `skip`。拆分为双路径解决。
- `_infer_from_aggregate` 新增 `pool_counter_max` 参数，`extract_aggregate` 新增 `pool_counter_max` 聚合字段

---

## Task 3：四种统计分析 + 模式转换 ✅

**变更文件**：`core/process_analysis.py`

### 3.1 四种分析函数

| 函数 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `compute_aa(traces, event_mode, constraints)` | 轨迹列表 | 概率表 | P(事件模式)，含零样本枚举 |
| `compute_bb(traces, success_mode, success_n, success_op)` | 轨迹列表 | 概率表 + 统计摘要 | P(成败模式)，含零样本枚举 |
| `compute_ab(traces, event_mode, success_mode, constraints, success_n, success_op)` | 轨迹列表 | 条件概率表 | P(成败\|事件) |
| `compute_ba(traces, event_mode, success_mode, constraints, success_op)` | 轨迹列表 | 条件概率表 | P(事件\|成败) |

### 3.2 事件模式转换（5种）

| 模式 | 函数 | 输出类型 | 说明 |
|------|------|---------|------|
| `raw` | `to_raw_trajectory` | `Tuple[str, ...]` | 原始轨迹，含保底名和抽卡数 |
| `sequence` | `to_event_type_sequence` | `Tuple[str, ...]` | 事件类型序列 |
| `set` | `to_event_type_set` | `Tuple[str, ...]` | 事件类型集合，无序 |
| `count_set` | `to_event_count_set` | `Tuple[int, ...]` | 5种事件类型的计数元组 |
| `custom` | `to_custom_pattern` | `Dict[str, str]` | 自定义约束分桶聚合 |

#### 自定义模式（custom）逻辑

每种事件类型可独立设置操作符（任意/=/≥/≤/>/<）和阈值 N：
- **任意**：该事件类型不参与模式键
- **非任意**：根据操作符分为两个桶（满足/不满足），如 `≥1` → `保底出≥1` 或 `保底出<1`
- 有约束时，模式键只包含非任意约束的事件类型字段
- `compute_aa` 枚举所有 2^k 种桶组合，零样本组合也显示（count=0）

5种事件类型：`pity_hit`(保底出), `early_hit`(提前出), `miss`(没出), `skip`(跳过), `ignore`(忽略)

### 3.3 成败模式转换（4种）

| 模式 | 函数 | 输出类型 | 说明 |
|------|------|---------|------|
| `sequence` | `to_success_sequence` | `Tuple[bool, ...]` | 成败序列 |
| `set` | `to_success_set` | `Tuple[int, int]` | (成功数, 失败数) |
| `count` | `to_success_count` | `int` | 成功池数 |
| `custom` | `to_success_custom` | `str` | 自定义操作符+N分桶 |

#### 成败自定义模式逻辑

操作符（=/≥/≤/>/<）+ 阈值 N，将成功池数分为两个桶：
- 如 `≥2` → `≥2` 或 `<2`
- `compute_bb` 枚举所有桶，零样本桶也显示

### 3.4 辅助函数

- `_hashable(obj)`：将 dict/list/set 转为可哈希类型用于 Counter
- `_unhashable(obj)`：还原为原始类型（含 dict 还原：识别 tuple-of-2-tuples → dict）
- `_enumerate_custom_combinations(constraints)`：枚举事件自定义模式的所有桶组合
- `_enumerate_success_custom_buckets(op, n)`：枚举成败自定义模式的所有桶

---

## Task 4：过程分析面板 UI ✅

**变更文件**：`gui/process_analysis_panel.py`, `gui/main_window.py`, `gui/gacha_panel.py`

### 4.1 配置区

| 配置项 | 控件 | 说明 |
|--------|------|------|
| GDR 指标 | ComboBox | 复用 `UNIFIED_GDR_REGISTRY` |
| 成功阈值 | DoubleSpinBox | -9999999.0~9999999.0（已修复，原上限1.0对部分GDR指标不够），步长0.05 |
| 池子GDR方式 | ComboBox | 累积 / 单池 |
| 事件组合模式 | ComboBox | 序列/集合/计数组合/原始/自定义 |
| 事件自定义约束（5项） | 操作符ComboBox + N SpinBox × 5 | 保底出/提前出/没出/跳过/忽略，选择"自定义模式"时显示 |
| 成败组合模式 | ComboBox | 计数/序列/集合/自定义 |
| 成败自定义约束 | 操作符ComboBox + N SpinBox | 选择"自定义模式"时显示 |

### 4.2 结果区（5个Tab）

| Tab | 名称 | 表格列 |
|-----|------|--------|
| Tab 1 | 事件统计 | 事件组合, 出现次数, 概率, 累计概率 |
| Tab 2 | 成败统计 | 成败模式, 出现次数, 概率, 累计概率 + 统计摘要（各池成功率等） |
| Tab 3 | 事件→成败 | 事件组合, P(成功\|组合), P(失败\|组合), 出现次数, 成功数, 失败数 |
| Tab 4 | 成败→事件 | 事件组合, P(组合\|成功), P(组合\|失败), 比值, 出现次数 |
| Tab 5 | 轨迹详情 | 池子ID, 事件类型, 保底名, 抽卡数, 计数器最大值, 池GDR值, 池成败 |

### 4.3 格式化函数

- `_format_event_pattern(pattern, event_mode)`：
  - custom 模式：过滤 `:*` 项，逗号分隔
  - count_set 模式：只显示计数>0的事件
  - set 模式：逗号分隔
  - sequence/raw 模式：箭头分隔
- `_format_success_pattern(pattern, success_mode)`：
  - sequence：✓/✗ 序列
  - set：N成功, M失败
  - count：成功N个池
  - custom：≥N/≤N/=N/≠N/>N/<N 个成功

---

## Task 5：Bug修复记录 ✅

### 5.1 级联Bug修复（3个导致100%模拟失败）

| Bug | 根因 | 修复 |
|-----|------|------|
| 双重 `after_draw` | `after_draw` 在记录保底信息前后各调用一次，第一次重置了计数器 | 删除第一次调用 |
| `PityDefParsed.start_at` | `PityDefParsed` 没有 `start_at` 属性 | 改用 `_pity_engine.behaviors.get(pname).start_at` |
| `PityState.get(pname, 0)` | `PityState.get()` 是自定义方法只接受1个参数 | 改为 `pity_state.get(pname)` |

### 5.2 显示/逻辑Bug修复

| Bug | 修复 |
|-----|------|
| 所有事件识别为 skip | 双路径 `infer_events`：raw compact 路径 + aggregate 路径 |
| `_key_to_display` ImportError | 本地构建 `_gdr_key_to_display` dict |
| `'dict' object is not callable` | `_gdr_key_to_display(key)` → `_gdr_key_to_display.get(key, '')` |
| 快速预览显示 NaN | 空 aggregate_data 列表守卫 |
| 除零错误 | `total > 0` 检查 |
| `.items()` on None | 6处 `and xxx[i]` None 守卫 |
| summary 模式表格空白 | `_unhashable` 不还原 dict → list 调用 `.items()` 崩溃；修复 `_unhashable` 识别 tuple-of-2-tuples 并还原为 dict |
| `QGridLayout` 未导入 | 添加到 import 列表 |
| set 模式显示箭头 | 改为逗号分隔 |
| BA 表多余列 | 用户明确拒绝"成功组次数/失败组次数"，恢复5列 |
| `early_hit(0)` 始终显示0 | `to_raw_trajectory` 改用 `ev.draws`（抽卡数）而非 `ev.counter_max` |
| SpinBox 宽度太窄 | `setMaximumWidth(60)` → `setMaximumWidth(80)` |
| 统计分析面板从不失败概率不一致 | 移除统计分析面板中的重复实现，过程分析面板使用池子级别语义 |
| "前出"标签 | 统一改为"提前出" |

### 5.3 重构记录

| 变更 | 说明 |
|------|------|
| `summary` → `custom` | 总结性模式改名为自定义模式 |
| `SUMMARY_OPS` → `CUSTOM_OPS` | 操作符顺序改为：任意/=/≥/≤/>/< |
| `exact_n/at_most_n/at_least_n` → `custom` | 三个成败模式合并为一个自定义模式，操作符+N |
| 自定义模式零样本枚举 | `compute_aa` 和 `compute_bb` 在自定义模式下枚举所有桶组合，零样本也显示 |
| 有约束时只包含约束字段 | `to_custom_pattern` 在有非任意约束时，模式键只包含约束字段 |
| `never_fail_prob` 语义 | 改回池子级别：`all(pool_success.values())` = 所有池子都成功 |

### 5.4 流式架构修复

| 文件 | 修复 |
|------|------|
| `core/streaming.py` | 6处 `.items()` None 守卫 + `_update_transition` 空字典守卫 + `pool_counter_max` 聚合 |
| `gui/gacha_panel.py` | 除零修复 + 空数据守卫 + n_results/n_requested 字段 |
| `gui/batch_simulator.py` | 失败计数 + `[WARNING]` 输出 |

---

## Task 6：成功定义一致性 ✅ 确认设计合理

### 结论

两种"成功"定义各有用途，混用是设计意图而非bug：

| 定义 | 使用位置 | 设计理由 |
|------|---------|---------|
| 整体成功 `is_success` | AB 的 `overall_success_prob`、BA 的条件概率分组 | 条件概率 P(事件\|成功) 中的"成功"应该是最终结果 |
| 池子成功 `pool_success` | BB 的模式表、BB 的从未失败/从未成功概率、AB 的 `success_distribution` | BB 关注池子级别成败分布；AB 的 `success_distribution` 提供池子级别细节 |

AB 分析中 `overall_success_prob`（整体级）和 `success_distribution`（池子级）互补：
- `overall_success_prob`：回答"给定事件模式，最终整体成功的概率？"
- `success_distribution`：回答"给定事件模式，池子级别成败模式的完整分布？"

---

## Task 7：兑换池/资源池事件 ❌ 未实现

### 前置条件

1. **compact 新增 `pool_types` 字段**：当前 compact 数据中没有池子类型信息，需要新增 `pool_types: Dict[str, str]`（`draw`/`exchange`/`resource`）
2. **兑换池识别**：`Pool.is_exchange = True`（`core/pool.py:142`），需在 `gacha_service.py` 中将此信息写入 compact
3. **资源池识别**：当前没有 `is_resource` 标记字段，需通过配置中的 `pool_type` 或新增标记

### 4种新事件类型

| 池子类型 | 事件类型 | 编码 | 判断逻辑 |
|---------|---------|------|---------|
| 兑换池 | 兑换 | `exchange` | 策略对该兑换池执行了 DrawAction |
| 兑换池 | 未兑换 | `no_exchange` | 策略未对该兑换池执行 DrawAction |
| 资源池 | 抽资源 | `resource_draw` | 策略对该资源池执行了 DrawAction |
| 资源池 | 资源忽略 | `resource_ignore` | 策略未对该资源池执行 DrawAction |

**注意**：`resource_ignore` 是独立事件类型，不与抽卡池的 `ignore` 合计。

### 实施步骤

1. `gacha_service.py`：在 compact 中新增 `pool_types` 字段
2. `process_trace.py`：`_infer_from_draw_sequence` 和 `_infer_from_aggregate` 根据 `pool_types` 推断兑换池/资源池事件
3. `process_analysis.py`：`EVENT_TYPE_ORDER` 扩展为9种，`EVENT_TYPE_LABELS` 新增4种标签
4. `process_analysis_panel.py`：自定义模式 UI 新增4种事件类型的约束控件
5. 更新测试

---

## Task 8：`success_distribution` UI展示 ❌ 未实现

### 现状

`compute_ab` 中已计算 `success_distribution`（给定事件模式，池子级别成败模式的概率分布），但 AB 表格只展示了 `overall_success_prob`，`success_distribution` 是死字段。

### 理论意义

- `overall_success_prob`：回答"给定事件模式，最终整体成功的概率？"
- `success_distribution`：回答"给定事件模式，池子级别成败模式的完整分布是什么？"

两者互补：前者是最终结果，后者是细节分布。

### 实施方案

在 AB 表格中新增一列"池成败分布"，展示 `success_distribution` 的摘要（如"2成功1失败: 60%, 1成功2失败: 30%, 3成功: 10%"）。

---

## 测试覆盖

**测试文件**：`tests/core/test_process_analysis.py`（36个测试用例）

| 测试类 | 用例数 | 覆盖内容 |
|--------|--------|---------|
| TestInferEvents | 5 | 5种事件类型推断（raw compact 路径） |
| TestInferEventsFromAggregate | 5 | 5种事件类型推断（aggregate 路径） |
| TestEventModeConversions | 10 | 5种事件模式 + 自定义约束 + 零样本枚举 + dict还原 + AA集成 |
| TestSuccessModeConversions | 8 | 4种成败模式（含 custom 5种操作符） |
| TestComputeAA | 3 | 基础/空数据/set模式 |
| TestComputeBB | 3 | 基础/自定义模式零样本/空数据 |
| TestComputeAB | 1 | 基础 |
| TestComputeBA | 1 | 基础 |

---

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `service/gacha_service.py` | 修改 | 新增 `draw_pity_names`/`draw_pity_counter_max`；修复3个级联Bug |
| `core/process_trace.py` | 新增 | 数据结构 + 双路径轨迹推断 + 池子级别GDR |
| `core/process_analysis.py` | 新增 | 4种分析 + 9种模式转换 + 自定义约束 + 零样本枚举 + hash/unhash |
| `core/streaming.py` | 修改 | None 守卫修复 + `pool_counter_max` 聚合 |
| `core/__init__.py` | 修改 | 导出 `to_custom_pattern`, `to_success_custom` |
| `gui/process_analysis_panel.py` | 新增 | 过程分析面板（5 Tab + 自定义约束控件） |
| `gui/analysis_panel.py` | 修改 | 移除过程分析分类和从未失败概率 |
| `gui/gacha_panel.py` | 修改 | 除零修复 + 空数据守卫 |
| `gui/batch_simulator.py` | 修改 | 失败计数 |
| `gui/main_window.py` | 修改 | Tab 顺序 + cumulative_snapshots 传递 |
| `tests/core/test_process_analysis.py` | 新增 | 36个测试用例 |

---

## 未实现功能

| 功能 | 优先级 | 说明 |
|------|--------|------|
| **兑换池/资源池事件** | 🔴 高 | 需新增 `pool_types` 字段 + 4种事件推断（`exchange`/`no_exchange`/`resource_draw`/`resource_ignore`） |
| **保底名区分** | 🟡 中 | 当前仅 `raw` 模式区分保底机制名（如 `pity_hit:ssr_soft` vs `pity_hit:ssr_hard`），其他模式不区分。需在 sequence/set/count_set/custom 模式中支持按保底类型细分 |
| **`success_distribution` UI展示** | 🟡 中 | AB 分析中已计算但未展示，需在 AB 表格新增"池成败分布"列 |
| **BB 可视化增强** | 🟢 低 | 柱状图（池成功率）、热力图（池间相关性）、条件概率矩阵 P(j\|k) |
| **`extract_process` 流式提取器** | 🟢 低 | 原计划 Task 2 内容，改为 UI 层直接调用，暂不需要 |
| **条件 GDR 分布** | 🟡 中 | 以事件组合为条件查看任意 GDR 指标的分布，详见 Task 9 |

---

## 与 v6 计划的差异

| 项目 | v6 计划 | v7 实际 | 原因 |
|------|---------|--------|------|
| 成功定义一致性 | ❌ 未实现，需统一 | ✅ 确认设计合理 | 两种定义各有用途，非bug |
| 兑换池/资源池事件 | 🟡 中优先级 | 🔴 高优先级 | 明确了前置条件（`pool_types` 字段）和实施步骤 |
| `success_distribution` | 未提及 | 🟡 中优先级 | 确认为已计算但未展示的死字段 |
| 保底名区分 | 未记录 | 已记录 | `raw` 模式区分保底名，其他模式不区分 |

---

## Task 9：条件 GDR 分布 ❌ 未实现

### 概述

条件 GDR 分布是 AB 分析的连续版：B 维度从离散的"成功/失败"扩展到连续的"GDR 值分布"。对于每个事件模式，计算在该事件发生条件下的**任意 GDR 指标**的分布。

### 数据可用性

所有 13 种 GDR 指标的数据都在 `aggregate_data` 中，`compute_gdr_from_compact` 可直接调用：

| GDR 指标 | 需要的数据 | `aggregate_data` 中是否有 | 可行？ |
|----------|----------|--------------------------|--------|
| `target_achievement` | `card_counts`, `target_specs` | ✅ | ✅ |
| `target_collection` | `card_counts`, `target_specs` | ✅ | ✅ |
| `all_targets` | `card_counts`, `target_specs` | ✅ | ✅ |
| `ssr_collection` | `card_counts`, `ssr_ids` | ✅ | ✅ |
| `resource_remaining` | `final_resources` | ✅ | ✅ |
| `extra_target` | `card_counts`, `target_specs` | ✅ | ✅ |
| `non_pity_draws` | `total_draws`, `pity_triggers` | ✅ | ✅ |
| `pity_draws` | `pity_triggers` | ✅ | ✅ |
| `resource_efficiency` | `card_counts`, `total_consumed`, `target_specs` | ✅ | ✅ |
| `per_pool_draw_rate` | `pool_card_counts`, `pool_draw_counts`, `target_specs` | ✅ | ✅ |
| `weapon_character_ratio` | `card_counts`, `weapon_character_map` | ✅ | ✅ |
| `weighted_satisfaction` | `card_counts`, `desire_weights`, `miss_cost_weights` | ✅ | ✅ |
| `total_card_value` | `card_counts`, `card_value_weights` | ✅ | ✅ |

**结论：13 种 GDR 指标全部可行** ✅

### 计算方法

**按需计算**：用户选择 GDR 指标后，对筛选后的子集实时调用 `compute_gdr_from_compact`。该函数是轻量操作（字典查找+简单算术），N=1万时计算 < 1 秒。

```
1. 用户选择事件模式（复用 AA 系统）
2. 用户选择 GDR 指标（复用 GDR 下拉框）
3. 从 N 条 aggregate_data 中筛选满足事件模式的子集
4. 对子集中每条数据调用 compute_gdr_from_compact(agg, target_specs, gdr_key, ...)
5. 得到一组 GDR 值 → 计算分布统计量 + 绘图
6. Bootstrap CI（可选，依赖 P3 Bootstrap 计划）
```

### 筛选条件设计

复用 AA 事件模式系统：

```
第1层：事件模式（复用 AA）
  ├── sequence / set / count_set / custom 模式

第2层：GDR 指标（复用 GDR 下拉框）
  └── 13 种 GDR 指标任选

第3层：成功/失败条件（可选）
  ├── 全部 / 仅成功 / 仅失败
```

### UI 设计

**集成位置**：AB Tab 内，可折叠的"条件分布视图"。

```
┌─ 条件分布视图（可折叠）─────────────────────────────┐
│ 点击 AB 表格某行 → 展示该事件模式下的 GDR 分布     │
│                                                    │
│  事件模式: (pity_hit, miss)                        │
│  GDR 指标: [资源剩余 ▼]  ← 复用 GDR 下拉框        │
│  条件: [全部 ▼] (全部/仅成功/仅失败)               │
│  样本数: 2345                                      │
│                                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │  密度曲线 + 分位数标注 + CI 阴影带            │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  统计量：                                          │
│   均值: 1234.56 [1100, 1300]                      │
│   中位数: 1200 [1000, 1400]                        │
│   5%: 500 [400, 600]                              │
│   95%: 2000 [1800, 2200]                           │
└────────────────────────────────────────────────────┘
```

**交互流程**：
1. 用户在 AB 表格中点击某一行（选择一个事件模式）
2. 下方展开"条件分布视图"，显示该事件模式下的 GDR 分布
3. 用户可切换 GDR 指标和成功/失败条件
4. 切换 GDR 指标时，实时重新计算分布
5. 点击"📊 计算稳定性"按钮，显示 CI 阴影带和统计量 CI（依赖 P3）

### 与现有分析的关系

| 现有分析 | A 维度 | B 维度 | 条件 GDR 分布 |
|---------|--------|--------|--------------|
| AA | 事件模式 | — | — |
| BB | — | 成功/失败 | — |
| AB | 事件模式 | 成功/失败（离散） | — |
| BA | 成功/失败 | 事件模式 | — |
| **条件 GDR 分布** | **事件模式** | — | **任意 GDR 指标（连续分布）** |

条件 GDR 分布本质上是 **AB 分析的连续扩展**：B 维度从"成功/失败"扩展到"任意 GDR 指标的分布"。

### 特殊情况处理

| GDR 指标 | 特殊处理 |
|----------|---------|
| `all_targets` | 取值只有 0 和 1，分布图应显示为柱状图而非密度曲线 |
| `weighted_satisfaction` | 可为负值，X 轴范围需自动适配 |
| 需要 `desire_weights` 等的指标 | 从 `_gdr_context` 获取，若无则提示用户先配置 |
| `target_achievement` / `target_collection` / `ssr_collection` | 取值 [0, 1]，边界效应需注意 |

### 样本量问题

- 样本量 < 30：显示警告"样本量不足（n=X），结果可能不可靠"
- 样本量 < 10：不显示分布图，仅显示样本数

### 实施步骤

1. 在 `process_analysis_panel.py` 的 AB Tab 中添加可折叠的"条件分布视图"
2. 添加 GDR 指标下拉框（复用 `UNIFIED_GDR_REGISTRY`）
3. 添加成功/失败条件筛选下拉框
4. 实现 AB 表格行点击 → 筛选 → 计算 GDR 分布 → 绘图
5. Bootstrap CI 支持依赖 P3（Bootstrap 计划）
