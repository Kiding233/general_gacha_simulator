# 过程分析功能实施计划（v9）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补全过程分析剩余功能——兑换池/资源池事件推断（Task 7）、success_distribution UI 展示（Task 8）、条件 GDR 分布（Task 9）。

**Architecture:** Task 7 在 `gacha_service.py` 写入 `pool_types` → `process_trace.py` 推断 4 种新事件类型 → `process_analysis.py` 扩展 EVENT_TYPE_ORDER。Task 8 在 AB Tab 表格新增「池成败分布」列。Task 9 在 AB Tab 添加可折叠「条件分布视图」，复用 GDR 下拉框和事件模式系统。

**Tech Stack:** Python 3.10+, numpy, pytest, PyQt6

> 日期：2026-05-15 | 修订：v9（Tasks 7-9 增强为 TDD + bite-sized 格式，2026-05-24）
> 状态：Tasks 1-6 ✅ 完成 | Tasks 7-9 ❌ 未实现

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

### 测试策略

扩展现有 `tests/core/test_process_analysis.py`，新增资源池/兑换池事件推断测试。

- [ ] **7.1: test_infer_exchange_events_from_draw_sequence()** (RED)

```python
def test_infer_exchange_events_from_draw_sequence():
    """兑换池：有抽卡行为→exchange，无抽卡行为→no_exchange"""
    pool_types = {'exchange_pool': '兑换', 'draw_pool': '角色'}
    pool_ids_list = ['draw_pool', 'draw_pool', 'exchange_pool']
    card_ids = ['card_a', 'no_card', 'exchange_card']
    pity_flags = [False, False, False]
    pity_names = ['', '', '']
    pity_counter_max = [0, 0, 0]
    pool_card_counts = {'draw_pool': {'card_a': 1}, 'exchange_pool': {}}
    pool_draw_counts = {'draw_pool': 2, 'exchange_pool': 1}
    target_ids = {'card_a'}

    events = _infer_from_draw_sequence(
        pool_ids_list, card_ids, pity_flags, pity_names,
        pity_counter_max, pool_card_counts, pool_draw_counts, target_ids,
        pool_types=pool_types,
    )
    assert 'exchange_pool' in events
    assert events['exchange_pool'].event_type == 'exchange'
```

- [ ] **7.2: test_infer_no_exchange_event()** (RED)

```python
def test_infer_no_exchange_event():
    """兑换池无抽卡行为→no_exchange"""
    pool_types = {'exchange_pool': '兑换'}
    pool_ids_list = []
    card_ids = []
    pity_flags = []
    pity_names = []
    pity_counter_max = []
    pool_card_counts = {'exchange_pool': {}}
    pool_draw_counts = {'exchange_pool': 0}
    target_ids = set()

    events = _infer_from_draw_sequence(
        pool_ids_list, card_ids, pity_flags, pity_names,
        pity_counter_max, pool_card_counts, pool_draw_counts, target_ids,
        pool_types=pool_types,
    )
    assert events['exchange_pool'].event_type == 'no_exchange'
```

- [ ] **7.3: test_infer_resource_draw_event()** (RED)

```python
def test_infer_resource_draw_event():
    """资源池有抽卡行为→resource_draw"""
    pool_types = {'resource_pool': '资源'}
    pool_ids_list = ['resource_pool']
    card_ids = ['no_card']
    pity_flags = [False]
    pity_names = ['']
    pity_counter_max = [0]
    pool_card_counts = {'resource_pool': {}}
    pool_draw_counts = {'resource_pool': 1}
    target_ids = set()

    events = _infer_from_draw_sequence(
        pool_ids_list, card_ids, pity_flags, pity_names,
        pity_counter_max, pool_card_counts, pool_draw_counts, target_ids,
        pool_types=pool_types,
    )
    assert 'resource_pool' in events
    assert events['resource_pool'].event_type == 'resource_draw'
```

- [ ] **7.4: test_infer_resource_ignore_event()** (RED)

```python
def test_infer_resource_ignore_event():
    """资源池无抽卡行为→resource_ignore"""
    pool_types = {'resource_pool': '资源'}
    events = _infer_from_aggregate(
        {'resource_pool': 0}, {'resource_pool': {}}, {'resource_pool': 0},
        set(), pool_types=pool_types,
    )
    assert events['resource_pool'].event_type == 'resource_ignore'
```

- [ ] **7.5: 运行测试确认 4 个新测试 RED**

```bash
pytest tests/core/test_process_analysis.py -k "exchange or resource" -v
# 预期: 4 failed（资源池被 skip，未生成事件）
```

- [ ] **7.6: `gacha_service.py`——在 compact 中写入 `pool_types`**

在 `GachaService.run_simulation_compact()` 中，初始化 compact 时新增：

```python
compact['pool_types'] = {
    pool.pool_id: ('兑换' if pool.is_exchange else
                   '资源' if getattr(pool, 'is_resource', False) else
                   '角色')
    for pool in self._pools
}
```

- [ ] **7.7: `process_trace.py`——资源池不再 skip，改为推断 resource_draw/resource_ignore**

修改 `_infer_from_draw_sequence`（line 87-89）和 `_infer_from_aggregate`（line 166-168）：

```python
# 旧：跳过资源池
if pool_type == '资源':
    continue

# 新：推断资源池事件
if pool_type == '资源':
    result[pool_id] = PoolEvent(
        pool_id=pool_id,
        pool_type='resource',
        event_type='resource_draw' if pdc > 0 else 'resource_ignore',
    )
    continue
```

- [ ] **7.8: `process_analysis.py`——EVENT_TYPE_ORDER 扩展为 9 种**

```python
EVENT_TYPE_ORDER = [
    'pity_hit', 'early_hit', 'miss', 'skip', 'ignore',
    'exchange', 'no_exchange', 'resource_draw', 'resource_ignore',
]
```

- [ ] **7.9: `process_analysis.py`——EVENT_TYPE_LABELS 补全 2 种新标签**

```python
EVENT_TYPE_LABELS = {
    # ... 现有 7 种 ...
    'resource_draw': '抽资源',
    'resource_ignore': '资源忽略',
}
```

- [ ] **7.10: `process_analysis_panel.py`——自定义模式 UI 新增 4 种事件类型约束控件**

在 `_build_custom_constraint_row()` 中扩展事件类型列表，新增：兑换、未兑换、抽资源、资源忽略。

注意：9 种事件类型全部显示会导致 UI 过高。考虑使用 `QScrollArea` 包裹约束控件区，或将不常用类型折叠。

- [ ] **7.11: 运行全部测试确认 GREEN**

```bash
pytest tests/core/test_process_analysis.py -v
# 预期: 40 passed（原 36 + 新增 4）
```

- [ ] **7.12: 提交**

```bash
git add gacha_simulator/service/gacha_service.py \
        gacha_simulator/core/process_trace.py \
        gacha_simulator/core/process_analysis.py \
        gacha_simulator/gui/process_analysis_panel.py \
        tests/core/test_process_analysis.py
git commit -m "feat: 兑换池/资源池事件推断——新增 exchange/no_exchange/resource_draw/resource_ignore 4种事件类型"
```

---

## Task 8：`success_distribution` UI展示 ❌ 未实现

### 现状

`compute_ab` 中已计算 `success_distribution`（给定事件模式，池子级别成败模式的概率分布），但 AB 表格只展示了 `overall_success_prob`，`success_distribution` 是死字段。

### 理论意义

- `overall_success_prob`：回答"给定事件模式，最终整体成功的概率？"
- `success_distribution`：回答"给定事件模式，池子级别成败模式的完整分布是什么？"

两者互补：前者是最终结果，后者是细节分布。

### 实施步骤

- [ ] **8.1: AB 表格新增「池成败分布」列**

在 `process_analysis_panel.py` 的 `_build_ab_table()` 中：

```python
# 表头新增第6列
headers = ['事件组合', 'P(成功|组合)', 'P(失败|组合)', '出现次数', '成功数', '池成败分布']
table.setColumnCount(6)
```

- [ ] **8.2: 实现 `_format_success_distribution()` 格式化函数**

```python
def _format_success_distribution(success_dist: Dict[str, float]) -> str:
    """将 success_distribution 格式化为可读字符串
    
    success_dist 示例: {('success', 'success', 'fail'): 0.6, ('success',): 0.4}
    → "2成功1失败: 60%, 1成功: 40%"
    """
    if not success_dist:
        return "-"
    total = sum(success_dist.values())
    parts = []
    for pattern, prob in sorted(success_dist.items(), key=lambda x: -x[1]):
        n_success = sum(1 for s in pattern if s == 'success')
        n_fail = len(pattern) - n_success
        pct = prob / total * 100 if total > 0 else 0
        
        if n_fail == 0:
            label = f"{n_success}成功"
        elif n_success == 0:
            label = f"{n_fail}失败"
        else:
            label = f"{n_success}成功{n_fail}失败"
        parts.append(f"{label}: {pct:.0f}%")
    return ', '.join(parts)
```

- [ ] **8.3: 在 AB 表格数据填充中写入第 6 列**

在 `_populate_ab_table()` 的数据循环中：

```python
for row_idx, (event_pattern, row_data) in enumerate(ab_data.items()):
    # ... 现有 5 列填充 ...
    
    # 第 6 列：池成败分布
    success_dist = row_data.get('success_distribution', {})
    dist_text = _format_success_distribution(success_dist)
    dist_item = QTableWidgetItem(dist_text)
    dist_item.setFlags(dist_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    table.setItem(row_idx, 5, dist_item)
```

- [ ] **8.4: 第 6 列显示优化**

- 当分布条目 > 3 时，`dist_text` 只显示 top 3，其余折叠为 `...等N种`
- 完整分布通过 tooltip 展示：`dist_item.setToolTip(full_text)`
- 列宽 200px，允许 `setWordWrap(True)` 自动换行

- [ ] **8.5: 手动目视验证 + 提交**

启动 GUI → 过程分析 → AB Tab → 执行分析 → 确认「池成败分布」列显示合理。

```bash
git add gacha_simulator/gui/process_analysis_panel.py
git commit -m "feat: AB 表格新增「池成败分布」列——展示 success_distribution 摘要"
```

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

所有 13 种 GDR 指标的数据都在 `aggregate_data` 中，`compute_gdr_from_compact` 可直接调用。**结论：13 种 GDR 指标全部可行** ✅

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

### 实施步骤

- [ ] **9.1: AB Tab 添加可折叠的「条件分布视图」**

在 AB 表格下方新增 `QGroupBox`（可折叠），包含：

```
┌─ 条件分布视图 [展开/折叠] ─────────────────────────┐
│  事件模式: [从 AB 表格点击选取]                     │
│  GDR 指标: [资源剩余 ▼]  条件: [全部 ▼]            │
│  样本数: N/A                                        │
│                                                     │
│  [密度曲线图 + 分位数标注]                          │
│                                                     │
│  统计量表格:                                        │
│   均值 | 中位数 | 5%分位数 | 95%分位数 | 标准差      │
└─────────────────────────────────────────────────────┘
```

- [ ] **9.2: 实现 AB 表格行点击→筛选逻辑**

```python
def _on_ab_row_selected(self, row_idx):
    """AB 表格行点击→获取该事件模式→筛选 aggregate_data 子集"""
    event_pattern = self._ab_data[row_idx]['event_pattern']
    
    # 从所有轨迹中筛选匹配此事件模式的子集
    filtered_aggs = []
    for i, trace in enumerate(self._traces):
        if _event_pattern_matches(trace, event_pattern, self._event_mode):
            filtered_aggs.append(self._aggregate_data[i])
    
    self._conditional_aggs = filtered_aggs
    self._update_conditional_view()
```

- [ ] **9.3: 实现筛选逻辑 `_event_pattern_matches()`**

```python
def _event_pattern_matches(trace, target_pattern, event_mode) -> bool:
    """判断一条轨迹的事件模式是否匹配目标模式"""
    if event_mode == 'sequence':
        return to_event_type_sequence(trace.events) == target_pattern
    elif event_mode == 'set':
        return to_event_type_set(trace.events) == target_pattern
    elif event_mode == 'count_set':
        return to_event_count_set(trace.events) == target_pattern
    elif event_mode == 'custom':
        return to_custom_pattern(trace.events, self._constraints) == target_pattern
    return False
```

- [ ] **9.4: 实现 `_update_conditional_view()`——计算 GDR 分布 + 绘图**

```python
def _update_conditional_view(self):
    aggs = self._conditional_aggs
    n = len(aggs)
    self._cond_sample_label.setText(f"样本数: {n}")
    
    if n < 10:
        self._cond_chart_label.setText("样本量不足 (n<10)，无法显示分布")
        return
    if n < 30:
        self._cond_warning_label.show()  # "样本量较少，结果可能不稳定"
    
    gdr_key = self._cond_gdr_combo.currentData()
    values = []
    for agg in aggs:
        v = compute_gdr_from_compact(agg, self._target_specs, gdr_key,
                                      gdr_context=self._gdr_context)
        if v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            values.append(v)
    
    # 分布统计
    self._cond_stats = {
        'mean': np.mean(values), 'median': np.median(values),
        'std': np.std(values), 'q05': np.percentile(values, 5),
        'q95': np.percentile(values, 95), 'n': len(values),
    }
    
    # 绘图
    self._plot_conditional_distribution(values, gdr_key)
    self._update_cond_stats_table()
```

- [ ] **9.5: 特殊情况处理**

| GDR 指标 | 特殊处理 |
|----------|---------|
| `all_targets` | 取值只有 0 和 1，分布图显示为柱状图而非密度曲线 |
| `weighted_satisfaction` | 可为负值，X 轴范围需自动适配 |
| 需要 `desire_weights` 等的指标 | 从 `_gdr_context` 获取，若无则提示用户先配置 |
| `target_achievement` / `target_collection` / `ssr_collection` | 取值 [0, 1]，边界效应需注意 |

- [ ] **9.6: GDR 下拉框与成功/失败条件联动**

```python
# GDR 指标切换 → 重新计算分布
self._cond_gdr_combo.currentIndexChanged.connect(self._update_conditional_view)

# 成功/失败条件切换
self._cond_filter_combo.addItems(['全部', '仅成功', '仅失败'])
self._cond_filter_combo.currentIndexChanged.connect(self._on_cond_filter_changed)

def _on_cond_filter_changed(self):
    filter_mode = self._cond_filter_combo.currentText()
    if filter_mode == '全部':
        self._conditional_aggs = self._all_matching_aggs
    elif filter_mode == '仅成功':
        self._conditional_aggs = [a for a, t in zip(self._all_matching_aggs, self._matching_traces) if t.is_success]
    else:
        self._conditional_aggs = [a for a, t in zip(self._all_matching_aggs, self._matching_traces) if not t.is_success]
    self._update_conditional_view()
```

- [ ] **9.7: Bootstrap CI 集成（依赖 P3）**

P3 Bootstrap 计划完成后，添加：

```python
# 「计算稳定性」按钮
def _on_compute_stability(self):
    from gacha_simulator.core.bootstrap import BootstrapEngine
    engine = BootstrapEngine(B=1000, random_seed=42)
    values = self._cond_values
    result = engine.bootstrap_distribution(values, quantiles=[0.05, 0.5, 0.95])
    # 更新统计量表格显示 CI: "均值: 1234 [1100, 1300]"
    # 图表添加阴影带
```

- [ ] **9.8: 手动目视验证 + 提交**

启动 GUI → 过程分析 → AB Tab → 点击某行 → 展开条件分布视图 → 切换 GDR 指标 → 确认分布图和统计量正确。

```bash
git add gacha_simulator/gui/process_analysis_panel.py
git commit -m "feat: 条件 GDR 分布——AB Tab 可折叠分布视图，事件模式筛选 + 任意 GDR 指标分布"
```
