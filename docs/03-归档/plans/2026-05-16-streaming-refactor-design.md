# 流式模拟架构重构设计

## 1. 目标

将当前的"先模拟全部→再分析"模式重构为"边模拟→边提取→边丢弃"的流式架构，使内存占用与模拟次数 N 无关，支持 10w-100w 模拟量。同时保持"一次模拟、多面板共享"的统一模拟架构，并为自适应模拟次数（P3）提供基础。

核心思路：**compact 结果是内存瓶颈（~22 KB/样本），但各面板从中实际需要的数据很小。流式处理 = 每来一个 compact 结果就提取各面板需要的数据，然后丢弃 compact 本身。**

## 2. 当前问题

### 2.1 内存瓶颈

当前 `run_batch_parallel` 返回 `List[Dict]`，每个 compact 结果 ~22 KB（简单配置）到 ~100 KB（复杂配置）。

| 模拟量 | compact 结果总内存 | 提取的衍生数据内存 |
|--------|-------------------|-------------------|
| 10,000 | ~220 MB | ~0.6 MB（8池×1w×8B） |
| 100,000 | ~2.1 GB | ~6.4 MB |
| 1,000,000 | ~21 GB | ~64 MB |

compact 结果中，逐抽记录（`draw_card_ids`、`draw_pool_ids`、`draw_times`、`draw_pity`）占了 ~80% 的内存。而大多数分析只需要从中提取的少量浮点数或整数。

### 2.2 当前数据流

```
gacha_panel 跑模拟（默认 1000 次）
    ↓ simulation_finished(results: List[Dict])
    ↓ main_window.on_simulation_finished()
    ├→ analysis_panel.update_results(results)
    ├→ retreat_panel.set_simulation_results(results)
    └→ worst_impact_panel.set_simulation_results(results)
```

三个面板都持有 results 的引用，用户稍后点击"运行分析"时才遍历。

### 2.3 analysis_panel 对逐抽数据的实际需求

analysis_panel 通过 `_compact_to_iv_list()` 将 compact dict 反向还原为 `List[InfoVector]`，然后调用 `GDR_REGISTRY` 函数。但经过逐项审查，各分析实际需要的数据分为两类：

**只需要聚合数据的分析**（不需要逐抽记录）：

| 分析 | 需要的聚合数据 | 备注 |
|------|-------------|------|
| GDR分布（13个指标） | `card_counts`, `pity_triggers`, `final_resources`, `total_consumed/gained` | 全局聚合即可 |
| VaR/CVaR | 同上 | |
| 条件分布 | 同上 | |
| 每池抽卡数 | `pool_draw_counts` | 每池聚合 |
| 每池目标卡数 | `pool_card_counts` | ⚠️ 需要每池卡牌计数，非全局 |
| 每池保底数 | `pool_pity_counts` | ⚠️ 需要每池保底计数，非全局 |
| 截止每池GDR分布 | 累积 `card_counts` + `total_consumed` + `final_resources` | ⚠️ 需要累积快照，非仅5个预计算指标 |
| 汇总统计表 | 同 GDR 分布 | |

**需要逐抽序列的分析**（需要 `draw_card_ids` 等）：

| 分析 | 需要的逐抽字段 |
|------|-------------|
| 时间序列（样本路径） | `draw_card_ids` |
| 时间热力图 | `draw_card_ids` + `total_consumed/gained`（线性插值） |
| 3D/2D瀑布图 | `draw_card_ids` |
| 累积分析 | 可增量计算（见 §3.5） |
| 转变分析 | 可增量计算（见 §3.5） |
| 抽卡数-目标散点图 | `draw_card_ids` |

**关键发现**：这些逐抽分析不需要 InfoVector 的 `resources_consumed/gained` 字段——compact dict 已新增 `draw_resources_consumed` 和 `draw_resources_gained` 逐抽真实资源数据，可直接用于精确计算。它们真正需要的只是 4 个列表：`draw_card_ids`、`draw_pool_ids`、`draw_times`、`draw_pity`，加上 2 个资源列表：`draw_resources_consumed`、`draw_resources_gained`。

### 2.4 GDR 成功判断的重复问题（✅ 已由 P0 修复）

~~当前成功判断逻辑在多处重复实现~~ → 已通过 P0（GDR统一管理）修复：

| 位置 | 修复前 | 修复后 |
|------|--------|--------|
| `worst_impact.py:_build_success_checker` | 手动重写9种GDR判断（~70行） | ✅ 使用 `SuccessChecker` |
| `analysis_panel.py:_compute_statistics_unit` | 硬编码9个函数列表 | ✅ 遍历 `UNIFIED_GDR_REGISTRY` |
| `vulnerability.py:_is_success` | 调用 `compute_gdr_from_compact` | ✅ 保持不变 |
| `gdr.py:compute_success_probability` | 调用 `compute_gdr_from_compact` | ✅ 保持不变 |
| `per_pool_analysis.py:success_func` | 内联默认逻辑 | ⏳ 待流式重构后改为 compact 路径 |

P0 还修复了 `compute_gdr_from_compact` 中的 5 个数值不一致 bug（target_achievement/all_targets/ssr_collection/extra_target/resource_efficiency），统一了 `UNIFIED_GDR_REGISTRY` 和 `SuccessChecker`。

## 3. 设计方案：共享流式收集器

### 3.1 核心思路

一次模拟，用回调从每个 compact 中提取各面板需要的数据，然后丢弃 compact 本身。各面板拿到的是预提取的轻量数据。

```
gacha_panel 跑模拟（一次）
    ↓ on_result(compact)
    ↓ SharedResultCollector
    ├→ 聚合数据提取器：card_counts, pool_card_counts, pool_pity_counts, final_resources, ... → 存列表
    ├→ 逐抽序列提取器：draw_card_ids, draw_pool_ids, draw_times, draw_pity → 保留200条 + 增量计算
    ├→ 脆弱性提取器：pool_end_resources + success_flag + pity_states → 存列表
    ├→ 最差影响提取器：final_resources + card_counts + success_flag → 存列表
    └→ 过程分析提取器：pool_events + success → 存列表
    （compact 在回调结束后被 GC）
```

### 3.2 SharedResultCollector

```python
class SharedResultCollector:
    def __init__(self):
        self._extractors: Dict[str, Tuple[Callable, list]] = {}
        self.n_results = 0

    def add_extractor(self, name: str, extract_func: Callable[[Dict], Any]):
        self._extractors[name] = (extract_func, [])

    def on_result(self, compact: Dict[str, Any]):
        for name, (extract_func, acc) in self._extractors.items():
            acc.append(extract_func(compact))
        self.n_results += 1

    def get_extracted(self, name: str) -> list:
        if name in self._extractors:
            return self._extractors[name][1]
        return []
```

### 3.3 各面板的提取函数

#### extract_aggregate（修复致命问题1：增加每池级别数据）

```python
def extract_aggregate(compact):
    pool_ids_list = compact.get('draw_pool_ids', [])
    draw_res_consumed = compact.get('draw_resources_consumed', [])
    draw_res_gained = compact.get('draw_resources_gained', [])
    pool_resources_consumed = {}
    pool_resources_gained = {}
    for i, pid in enumerate(pool_ids_list):
        if pid not in pool_resources_consumed:
            pool_resources_consumed[pid] = {}
            pool_resources_gained[pid] = {}
        if i < len(draw_res_consumed):
            for k, v in draw_res_consumed[i].items():
                pool_resources_consumed[pid][k] = pool_resources_consumed[pid].get(k, 0) + v
        if i < len(draw_res_gained):
            for k, v in draw_res_gained[i].items():
                pool_resources_gained[pid][k] = pool_resources_gained[pid].get(k, 0) + v

    return {
        'card_counts': dict(compact.get('card_counts', {})),
        'pool_draw_counts': dict(compact.get('pool_draw_counts', {})),
        'pool_card_counts': dict(compact.get('pool_card_counts', {})),
        'pool_pity_counts': dict(compact.get('pool_pity_counts', {})),
        'total_draws': compact.get('total_draws', 0),
        'total_consumed': dict(compact.get('total_consumed', {})),
        'total_gained': dict(compact.get('total_gained', {})),
        'final_resources': dict(compact.get('final_resources', {})),
        'final_time': compact.get('final_time', 0),
        'pity_triggers': compact.get('pity_triggers', 0),
        'pool_end_resources': dict(compact.get('pool_end_resources', {})),
        'pool_end_pity_states': dict(compact.get('pool_end_pity_states', {})),
        'pool_resources_consumed': pool_resources_consumed,
        'pool_resources_gained': pool_resources_gained,
    }
```

**新增字段说明**：

| 字段 | 类型 | 来源 | 大小估算 |
|------|------|------|---------|
| `pool_card_counts` | `Dict[str, Dict[str, int]]` | compact dict（新增） | ~0.3 KB/样本 |
| `pool_pity_counts` | `Dict[str, int]` | compact dict（新增） | ~0.1 KB/样本 |
| `pool_resources_consumed` | `Dict[str, Dict[str, float]]` | 从 `draw_pool_ids` + `draw_resources_consumed` 按池聚合 | ~0.1 KB/样本 |
| `pool_resources_gained` | `Dict[str, Dict[str, float]]` | 从 `draw_pool_ids` + `draw_resources_gained` 按池聚合 | ~0.1 KB/样本 |

#### extract_vulnerability

```python
def extract_vulnerability(compact, target_specs, gdr_key, gdr_threshold,
                          desire_weights=None, miss_cost_weights=None,
                          card_value_weights=None, ssr_ids=None,
                          weapon_character_map=None):
    from .gdr import compute_gdr_from_compact
    val = compute_gdr_from_compact(
        compact, target_specs, gdr_key,
        desire_weights, miss_cost_weights, card_value_weights,
        ssr_ids, weapon_character_map,
    )
    return {
        'pool_end_resources': dict(compact.get('pool_end_resources', {})),
        'pool_end_pity_states': dict(compact.get('pool_end_pity_states', {})),
        'success': val >= gdr_threshold,
    }
```

#### extract_worst_impact

```python
def extract_worst_impact(compact, target_specs, gdr_key, gdr_threshold,
                         desire_weights=None, miss_cost_weights=None,
                         card_value_weights=None, ssr_ids=None,
                         weapon_character_map=None):
    from .gdr import compute_gdr_from_compact
    val = compute_gdr_from_compact(
        compact, target_specs, gdr_key,
        desire_weights, miss_cost_weights, card_value_weights,
        ssr_ids, weapon_character_map,
    )
    return {
        'final_resources': dict(compact.get('final_resources', {})),
        'card_counts': dict(compact.get('card_counts', {})),
        'success': val >= gdr_threshold,
    }
```

#### extract_process（修复致命问题3：预分类事件标签）

```python
def extract_process(compact, target_ids, ssr_ids, pity_defs,
                    target_specs, gdr_key, gdr_threshold,
                    desire_weights=None, miss_cost_weights=None,
                    card_value_weights=None, weapon_character_map=None):
    from .gdr import compute_gdr_from_compact
    val = compute_gdr_from_compact(
        compact, target_specs, gdr_key,
        desire_weights, miss_cost_weights, card_value_weights,
        ssr_ids, weapon_character_map,
    )
    success = val >= gdr_threshold

    pool_ids = compact.get('draw_pool_ids', [])
    card_ids = compact.get('draw_card_ids', [])
    pity_flags = compact.get('draw_pity', [])

    pool_events = {}
    for pool_id in set(pool_ids):
        pool_target_count = 0
        pool_pity_count = 0
        for i, pid in enumerate(pool_ids):
            if pid != pool_id:
                continue
            if card_ids[i] in target_ids:
                pool_target_count += 1
            if pity_flags[i]:
                pool_pity_count += 1

        if pool_target_count > 0 and pool_pity_count > 0:
            pool_events[pool_id] = 'pity_early_hit'
        elif pool_target_count > 0:
            pool_events[pool_id] = 'early_hit'
        elif pool_pity_count > 0:
            pool_events[pool_id] = 'pity_hit_miss'
        else:
            pool_events[pool_id] = 'miss'

    return {
        'pool_events': pool_events,
        'success': success,
    }
```

事件分类为：

| 事件标签 | 含义 | 判定条件 |
|---------|------|---------|
| `early_hit` | 保底前出目标卡 | 有目标卡 & 无保底触发 |
| `pity_early_hit` | 保底和目标卡都有 | 有目标卡 & 有保底触发 |
| `pity_hit_miss` | 保底出但非目标卡 | 无目标卡 & 有保底触发 |
| `miss` | 未出目标卡且无保底 | 无目标卡 & 无保底触发 |

加上池子级别的 `skip`（有目标卡但策略选择不抽）和 `ignore`（无目标卡且不抽），构成完整的 A 维度事件分类。

### 3.4 各提取数据的大小估算

| 提取器 | 每样本大小 | 10w 样本总内存 | 100w 样本总内存 |
|--------|----------|-------------|-------------|
| aggregate | ~0.9 KB | ~90 MB | ~900 MB |
| draw_sequence（保留200条） | ~15 KB | ~3 MB（固定） | ~3 MB（固定） |
| vulnerability | ~0.1 KB | ~10 MB | ~100 MB |
| worst_impact | ~0.05 KB | ~5 MB | ~50 MB |
| process | ~0.05 KB | ~5 MB | ~50 MB |

### 3.5 DrawSequenceExtractor

analysis_panel 中需要逐抽序列的分析（时间序列、热力图、瀑布图、累积分析、转变分析）有一个共同特点：**它们只需要少量样本就能画出有意义的图**。

- 时间序列：只画 20 条样本路径
- 热力图：需要全部样本的统计，但可以**增量构建**
- 瀑布图：同热力图
- 累积分析：在提取时直接计算每个池子结束时的累积统计
- 转变分析：同累积分析

**优化方案**：

1. **draw_sequence 只保留 N 条**（默认 200 条），供时间序列等需要原始路径的分析使用
2. **热力图/瀑布图/累积分析/转变分析**改为在提取时直接计算，不保留原始序列

```python
class DrawSequenceExtractor:
    def __init__(self, max_keep=200, pool_end_times=None, target_ids=None,
                 ssr_ids=None, target_specs=None, initial_resources=None,
                 resource_gain_per_day=None):
        self._max_keep = max_keep
        self._kept = []
        self._heatmap_data = {}
        self._cumulative_snapshots = {}
        self._transition_flags = []
        self._pool_end_times = pool_end_times
        self._target_ids = target_ids
        self._ssr_ids = ssr_ids
        self._target_specs = target_specs
        self._initial_resources = initial_resources or {}
        self._resource_gain_per_day = resource_gain_per_day or {}

    def __call__(self, compact):
        if len(self._kept) < self._max_keep:
            self._kept.append({
                'draw_card_ids': list(compact.get('draw_card_ids', [])),
                'draw_pool_ids': list(compact.get('draw_pool_ids', [])),
                'draw_times': list(compact.get('draw_times', [])),
                'draw_pity': list(compact.get('draw_pity', [])),
            })

        self._update_heatmap(compact)
        self._update_cumulative(compact)
        self._update_transition(compact)

        return None

    def get_kept_sequences(self): return self._kept
    def get_heatmap_data(self): return self._heatmap_data
    def get_cumulative_snapshots(self): return self._cumulative_snapshots
    def get_transition_flags(self): return self._transition_flags
```

#### _update_heatmap

热力图增量计算使用逐抽真实资源值，不再使用线性插值：

```python
def _update_heatmap(self, compact):
    card_ids = compact.get('draw_card_ids', [])
    draw_resources_consumed = compact.get('draw_resources_consumed', [])
    draw_resources_gained = compact.get('draw_resources_gained', [])
    target_count = sum(self._target_specs.values()) if self._target_specs else 1
    n_draws = len(card_ids)

    obtained = 0
    cumulative_consumed = {}
    cumulative_gained = {}

    for i, cid in enumerate(card_ids):
        if cid in self._target_ids:
            obtained += 1

        for k, v in draw_resources_consumed[i].items():
            cumulative_consumed[k] = cumulative_consumed.get(k, 0) + v
        for k, v in draw_resources_gained[i].items():
            cumulative_gained[k] = cumulative_gained.get(k, 0) + v

        achievement_val = obtained / target_count
        resource_val = (
            self._initial_resources.get('draw_resource', 0)
            + cumulative_gained.get('draw_resource', 0)
            - cumulative_consumed.get('draw_resource', 0)
        )

        if i not in self._heatmap_data:
            self._heatmap_data[i] = {'achievement': [], 'resource': []}
        self._heatmap_data[i]['achievement'].append(achievement_val)
        self._heatmap_data[i]['resource'].append(resource_val)
```

#### _update_cumulative（修复致命问题2：扩展累积快照支持任意GDR指标）

```python
def _update_cumulative(self, compact):
    if not self._pool_end_times:
        return

    card_ids = compact.get('draw_card_ids', [])
    pool_ids = compact.get('draw_pool_ids', [])
    pity_flags = compact.get('draw_pity', [])
    times = compact.get('draw_times', [])
    draw_resources_consumed = compact.get('draw_resources_consumed', [])
    draw_resources_gained = compact.get('draw_resources_gained', [])

    sorted_pools = sorted(self._pool_end_times.items(), key=lambda x: x[1])

    for pool_id, end_time in sorted_pools:
        cumulative_card_counts = {}
        cumulative_draws = 0
        cumulative_pity = 0
        cumulative_consumed = {}
        cumulative_gained = {}

        for i in range(len(card_ids)):
            if times[i] > end_time:
                break
            cid = card_ids[i]
            cumulative_draws += 1
            cumulative_card_counts[cid] = cumulative_card_counts.get(cid, 0) + 1
            if pity_flags[i]:
                cumulative_pity += 1
            for k, v in draw_resources_consumed[i].items():
                cumulative_consumed[k] = cumulative_consumed.get(k, 0) + v
            for k, v in draw_resources_gained[i].items():
                cumulative_gained[k] = cumulative_gained.get(k, 0) + v

        if pool_id not in self._cumulative_snapshots:
            self._cumulative_snapshots[pool_id] = []
        self._cumulative_snapshots[pool_id].append({
            'cumulative_card_counts': cumulative_card_counts,
            'cumulative_draws': cumulative_draws,
            'cumulative_pity_draws': cumulative_pity,
            'cumulative_consumed': cumulative_consumed,
            'cumulative_gained': cumulative_gained,
        })
```

**关键改进**：累积快照包含 `cumulative_card_counts`、`cumulative_consumed` 和 `cumulative_gained`，全部使用逐抽真实值累加，不再使用 `total_consumed × progress` 线性插值。使得后续可以用 `compute_gdr_from_compact` 计算任意 GDR 指标，不再限于预计算的 5 个指标。

#### _update_transition

```python
def _update_transition(self, compact):
    if not self._pool_end_times:
        return

    card_ids = compact.get('draw_card_ids', [])
    times = compact.get('draw_times', [])

    sorted_pools = sorted(self._pool_end_times.items(), key=lambda x: x[1])

    flags = []
    for pool_id, end_time in sorted_pools:
        obtained = 0
        total_needed = sum(self._target_specs.values())
        for i in range(len(card_ids)):
            if times[i] > end_time:
                break
            if card_ids[i] in self._target_ids:
                obtained += 1
        flags.append(obtained >= total_needed)

    self._transition_flags.append(flags)
```

**优化后内存**：

| 数据 | 每样本大小 | 保留量 | 总内存 |
|------|----------|--------|--------|
| 完整逐抽序列 | ~15 KB | 200 条 | ~3 MB |
| 热力图增量数据 | ~0.1 KB | 全部 | ~10 MB（10w） |
| 累积快照增量 | ~0.3 KB | 全部 | ~30 MB（10w） |
| 转变标记 | ~0.05 KB | 全部 | ~5 MB（10w） |

**100w 样本时总内存 ~50 MB**，vs 改造前 ~21 GB。

### 3.6 analysis_panel 的改造

analysis_panel 不再接收完整 compact 列表，改为接收预提取数据：

```python
def update_results(self, aggregate_data, draw_sequences,
                   heatmap_data, cumulative_snapshots, transition_flags,
                   target_ids=None, ssr_ids=None, gdr_context=None, pool_end_times=None):
```

**GDR 分布分析**：从 `aggregate_data` 列表计算，使用 `compute_gdr_from_compact`（已天然兼容 aggregate 数据）。

**时间序列**：从 `draw_sequences`（200 条）画样本路径。

**热力图/瀑布图**：从 `heatmap_data` 直接绘图。

**累积分析**：从 `cumulative_snapshots` + `compute_gdr_from_cumulative` 计算任意 GDR 指标。

**转变分析**：从 `transition_flags` 直接计算。

**每池分析**：从 `aggregate_data` 中的 `pool_draw_counts`、`pool_card_counts`、`pool_pity_counts` 计算。

**预设阈值**：改用 `compute_gdr_from_compact` 在 aggregate 数据上计算。

**GDR统计表**：已改为遍历 `UNIFIED_GDR_REGISTRY` + `compute_gdr_from_compact`（P0 已完成）。

### 3.7 compute_gdr_from_compact 兼容 aggregate 数据

`extract_aggregate` 提取的字段名与 compact dict 中的字段名完全相同，`compute_gdr_from_compact` 只使用 `.get()` 访问字段，因此**天然兼容 aggregate 数据**，无需新增函数。

对于**累积快照**中的 GDR 计算，需要一个新的入口：

```python
def compute_gdr_from_cumulative(cum_snapshot, target_specs, gdr_key,
                                 desire_weights=None, miss_cost_weights=None,
                                 card_value_weights=None, ssr_ids=None,
                                 weapon_character_map=None):
    pseudo_compact = {
        'card_counts': cum_snapshot['cumulative_card_counts'],
        'total_draws': cum_snapshot['cumulative_draws'],
        'pity_triggers': cum_snapshot['cumulative_pity_draws'],
        'total_consumed': cum_snapshot['cumulative_consumed'],
        'final_resources': {},
    }
    return compute_gdr_from_compact(
        pseudo_compact, target_specs, gdr_key,
        desire_weights, miss_cost_weights, card_value_weights,
        ssr_ids, weapon_character_map,
    )
```

### 3.8 完整数据流

```
gacha_panel._on_run_clicked():
    collector = SharedResultCollector()
    collector.add_extractor('aggregate', extract_aggregate)
    collector.add_extractor('vulnerability', extract_vulnerability)
    collector.add_extractor('worst_impact', extract_worst_impact)
    collector.add_extractor('process', extract_process)

    draw_seq_extractor = DrawSequenceExtractor(max_keep=200, ...)
    collector.add_extractor('draw_sequence', draw_seq_extractor)

    run_batch_parallel(..., on_result=collector.on_result)

    # 分发数据
    analysis_panel.update_results(
        aggregate_data=collector.get_extracted('aggregate'),
        draw_sequences=draw_seq_extractor.get_kept_sequences(),
        heatmap_data=draw_seq_extractor.get_heatmap_data(),
        cumulative_snapshots=draw_seq_extractor.get_cumulative_snapshots(),
        transition_flags=draw_seq_extractor.get_transition_flags(),
        ...
    )
    retreat_panel.set_extracted_data(collector.get_extracted('vulnerability'))
    worst_impact_panel.set_extracted_data(collector.get_extracted('worst_impact'))
```

### 3.9 run_batch_parallel 的 on_result 回调

```python
def run_batch_parallel(
    ...,
    on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Optional[Dict[str, Any]]]:
```

**行为**：
- 当 `on_result` 不为 None 时，每个模拟结果立即调用回调，**不累积到返回列表**，返回空列表
- 不传 `on_result` 时，行为与当前完全一致

### 3.10 流式分析器基类

```python
class StreamingAnalyzer(ABC):
    @abstractmethod
    def on_result(self, compact: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_result(self) -> Any: ...
```

### 3.11 StreamingSuccessCounter

`StreamingSuccessCounter` 内部持有一个 `SuccessChecker` 实例：

```python
class StreamingSuccessCounter(StreamingAnalyzer):
    def __init__(self, target_specs, gdr_key, gdr_threshold,
                 desire_weights=None, miss_cost_weights=None,
                 card_value_weights=None, ssr_ids=None,
                 weapon_character_map=None):
        self._checker = SuccessChecker(
            target_specs, gdr_key, gdr_threshold,
            desire_weights, miss_cost_weights, card_value_weights,
            ssr_ids, weapon_character_map,
        )
        self.total = 0
        self.success = 0

    def on_result(self, compact):
        self.total += 1
        if self._checker.is_success(compact):
            self.success += 1

    def get_probability(self) -> float:
        return self.success / self.total if self.total > 0 else 0.0

    def get_result(self):
        return self.get_probability()
```

### 3.12 过程分析的逐抽数据需求

过程分析需要判断"保底前第几抽出的"，需要保底计数器信息。在 `run_simulation_compact` 中新增：

```python
'draw_pity_names': List[Optional[str]]       # 每次抽卡触发的保底机制名
'draw_pity_counter_max': List[int]            # 每次抽卡时该池最接近触发的保底计数器值
```

`draw_pity_counter_max` 只是一个整数列表，100 抽 × 28 bytes = ~2.8 KB/样本。从中可以推断：
- 保底前第几抽：`pity_start_at - counter_value`
- 是否在保底区间：`counter_value >= start_at`

### 3.13 compact dict 新增字段

| 字段 | 类型 | 说明 | 大小估算 |
|------|------|------|---------|
| `pool_card_counts` | `Dict[str, Dict[str, int]]` | 每池每卡获得数量 | ~0.3 KB/样本 |
| `pool_pity_counts` | `Dict[str, int]` | 每池保底触发次数 | ~0.1 KB/样本 |
| `draw_pity_names` | `List[Optional[str]]` | 每次抽卡触发的保底机制名 | ~0.5 KB/样本 |
| `draw_pity_counter_max` | `List[int]` | 每次抽卡时该池最接近触发的保底计数器值 | ~0.3 KB/样本 |
| `draw_resources_consumed` | `List[Dict[str, float]]` | 每次抽卡的精确资源消耗 | ~2 KB/样本 |
| `draw_resources_gained` | `List[Dict[str, float]]` | 每次抽卡的精确资源收益（含卡片奖励+等待收益） | ~1 KB/样本 |

新增字段总增量：~4.2 KB/样本（vs 原 compact ~22 KB），对整体内存影响可忽略。

**`draw_resources_consumed/gained` 设计说明**：

- `draw_resources_consumed[i]`：第 i 次抽卡消耗的资源（即该池的单抽成本）
- `draw_resources_gained[i]`：第 i 次抽卡获得的资源，包含两部分：
  1. 卡片奖励的 `resources_gained`（如SSR兑换币）
  2. 自上次抽卡以来所有等待动作累积的资源收益（通过 `_pending_wait_gains` 归并）
- 等待收益归入下一次抽卡而非单独记录，保证 `draw_resources_gained` 与 `draw_card_ids` 等列表长度一致
- 从这两个列表可精确计算任意步骤的累积资源状态，无需线性插值

## 4. GDR 注册表与成功判断（✅ P0 已完成）

P0（GDR 与成功率判断统一管理）已完成以下工作：

- ✅ 合并两套注册表为 `UNIFIED_GDR_REGISTRY`（13 条，单一真相源）
- ✅ 创建 `SuccessChecker` 统一成功判断模块
- ✅ 修复 5 个数值不一致 bug
- ✅ 消除 worst_impact.py 70 行重复逻辑
- ✅ 消除 analysis_panel.py 4 处硬编码
- ✅ 5 个面板下拉列表统一使用 `populate_gdr_combo`
- ✅ `GDR_REGISTRY` 和 `COMPACT_GDR_REGISTRY` 从 `UNIFIED_GDR_REGISTRY` 动态生成（向后兼容）

流式重构中 GDR 相关的工作仅剩：
- 新增 `compute_gdr_from_cumulative` 函数
- `StreamingSuccessCounter` 内部使用 `SuccessChecker`
- 各提取函数调用 `compute_gdr_from_compact` 时传递 `ssr_ids` 和 `weapon_character_map`

## 5. 模拟量决策与数据流设计

### 5.1 设计原则

**gacha_panel 是统一模拟入口。** 它的职责是：

1. 提供模拟参数配置（模拟次数、线程数、种子等）
2. 发起模拟
3. 将模拟数据分发给各分析面板
4. 显示快速统计（`_calculate_quick_stats`，保留）

**模拟量由用户统一决定，所有面板共享同一次模拟的数据。** 不存在"各面板各自追加"的情况——如果用户跑了 1,000 次，所有面板都用这 1,000 次的数据；如果用户跑了 50,000 次，所有面板都用这 50,000 次的数据。

### 5.2 模拟量的选择指导

不同分析对模拟量有不同的精度要求。用户应根据自己的分析需求选择模拟量：

| 用户意图 | 推荐模拟量 | 原因 |
|---------|----------|------|
| 快速查看成功率 | ~1,000 | 成功率估计需要足够的成功/失败样本 |
| GDR 分布 + 分位数 | ~5,000-10,000 | 分位数估计需要足够的样本密度 |
| 脆弱性分析 / 最差影响 | ~10,000-50,000 | 核密度回归和下尾分位数需要更多数据 |
| 高精度 / 学术用途 | ~100,000+ | 更低的估计误差 |

**UI 建议**：在 gacha_panel 的模拟次数输入框旁提供"精度预设"下拉菜单，帮助用户选择合适的模拟量。具体精度数值取决于目标概率和配置参数，不在 UI 中硬编码。

### 5.3 追加模拟（可选功能）

虽然模拟量由用户统一决定，但流式架构天然支持"追加模拟"——如果用户觉得当前模拟量不够，可以在已有数据基础上追加，而不需要重新跑：

```python
class SharedResultCollector:
    def reset(self):
        """清空所有提取数据，但保留提取器配置。用于完全重新模拟。"""
        for name, (extract_func, acc) in self._extractors.items():
            acc.clear()
        self.n_results = 0
```

**追加模拟**是用户主动触发的操作（如 gacha_panel 的"追加模拟"按钮），不是各面板自动触发的。追加的数据通过同一个 `SharedResultCollector` 累积到已有数据中，所有面板共享。

### 5.4 数据需求分级

经过逐项审查，21 个分析方法的数据需求分为三个级别：

#### 级别 A：聚合级（14/21 个分析，可完全丢弃逐抽数据）

| 分析 | 需要的聚合字段 |
|------|-------------|
| GDR 分布 | `card_counts`, `final_resources`, `total_consumed`, `total_draws`, `pity_triggers` |
| VaR/CVaR 分析 | 同上 |
| 最差/最好情形分析 | 同上 |
| 从未失败概率 | 同上 |
| 条件分布 | 同上 |
| 预设阈值 | 同上 |
| 相关性分析 | 同上 |
| GDR 指标统计 | 同上 |
| 脆弱性分析 | `card_counts`, `pool_end_resources`, `pool_end_pity_states` |
| 最差影响分析 | `card_counts`, `final_resources` |
| 快速统计 | `card_counts`, `total_draws`, `pity_triggers`, `final_time` |
| 每池抽卡数 | `pool_draw_counts` |
| 每池目标卡数 | `pool_card_counts`（需新增） |
| 每池保底数 | `pool_pity_counts`（需新增） |

这些分析的核心逻辑是"对每个样本计算一个或多个 GDR 值，然后构建经验分布"，而所有 GDR 值均可通过 `compute_gdr_from_compact` 从聚合字段计算。

#### 级别 B：累积快照级（3/21 个分析，需要池边界处的累积状态）

| 分析 | 需要的额外字段 |
|------|-------------|
| 截止每池 GDR 分布 | `pool_end_card_counts`, `pool_end_cumulative_draws`, `pool_end_cumulative_pity`（需新增） |
| 转变分析（all_targets 模式） | `pool_end_card_counts`（需新增） |
| 转变分析（any_ssr/per_pool 模式） | `pool_end_target_obtained`, `pool_end_ssr_obtained`（需新增，布尔值） |

这些分析需要知道"截止每个池子结束时"的累积状态，而非仅最终状态。但数据量远小于逐抽数据——每个样本只需 O(池数 × 卡种数) 的额外空间。

#### 级别 C：逐抽级（4/21 个分析，需要抽卡序列的过程信息）

| 分析 | 需要的逐抽信息 |
|------|-------------|
| 时间序列 | "第 N 抽时已获得几张目标卡" |
| 时间-GDR 热力图 | "第 N 抽时的累积 GDR 值"（achievement + resource + ssr 维度） |
| 3D 瀑布图 | "第 N 抽时的目标卡累积获得数" |
| 2D 瀑布图 | 同 3D |

这些分析的核心是追踪 GDR 随抽卡步骤的演化，必须知道过程信息。聚合数据只有最终结果，丢失了过程。

### 5.5 逐抽数据的压缩表示

级别 C 的 4 个分析需要逐抽过程信息，但不需要完整的 `draw_card_ids`（~15 KB/样本）。可以用压缩表示替代：

**方案：目标卡获得位置序列**

```python
# 原始数据：draw_card_ids = ['SR_1', 'A', 'SR_2', 'B', 'A', 'SSR_1', ...]
# 压缩表示：
target_acquire_positions = [1, 4]    # 目标卡在第 1、4 抽获得
ssr_acquire_positions = [5]           # SSR 在第 5 抽首次获得
total_draws = 90                      # 总抽卡数
```

从压缩表示可以重建级别 C 分析需要的全部信息：

| 分析 | 重建方式 |
|------|----------|
| 时间序列 | `target_acquire_positions` → 逐步累积目标卡数 / 总需求 |
| 热力图 achievement 维度 | 同上 |
| 热力图 resource 维度 | `draw_resources_consumed` + `draw_resources_gained` → 逐步累加精确资源状态 |
| 热力图 ssr 维度 | `ssr_acquire_positions` → 逐步累积 SSR 种类数 |
| 瀑布图 | `target_acquire_positions` → 逐步累积目标卡数 |

**关于资源维度**：compact dict 已新增 `draw_resources_consumed` 和 `draw_resources_gained`，记录每次抽卡的精确资源消耗和收益（含卡片奖励和等待收益）。热力图和累积分析使用逐抽真实值累加，不再使用线性插值近似。

**压缩效果**：

| 表示 | 每样本大小 | 100w 样本总内存 |
|------|----------|-------------|
| 完整 `draw_card_ids` + `draw_pool_ids` + `draw_times` + `draw_pity` | ~15 KB | ~15 GB |
| 压缩 `target_acquire_positions` + `ssr_acquire_positions` | ~0.2 KB | ~200 MB |
| 压缩 + 只保留 200 条完整序列 | ~0.2 KB + 200×15KB | ~3.2 MB + ~200 MB |

**推荐方案**：保留 200 条完整逐抽序列（供时间序列画 20 条样本路径），其余样本只保留压缩表示。热力图和瀑布图从压缩表示增量计算。

### 5.6 完整数据流

```
gacha_panel._on_run_clicked():
    collector = SharedResultCollector()
    collector.add_extractor('aggregate', extract_aggregate)
    collector.add_extractor('vulnerability', extract_vulnerability)
    collector.add_extractor('worst_impact', extract_worst_impact)
    collector.add_extractor('process', extract_process)

    seq_extractor = DrawSequenceExtractor(
        max_keep=200,              # 保留 200 条完整逐抽序列
        target_ids=target_ids,     # 用于压缩表示
        ssr_ids=ssr_ids,           # 用于压缩表示
        pool_end_times=...,        # 用于累积快照
        ...
    )
    collector.add_extractor('draw_sequence', seq_extractor)

    run_batch_parallel(..., on_result=collector.on_result)

    # 分发数据
    gacha_panel.update_quick_stats(collector.get_extracted('aggregate'))
    analysis_panel.update_results(
        aggregate_data=collector.get_extracted('aggregate'),
        draw_sequences=seq_extractor.get_kept_sequences(),       # 200 条完整序列
        compressed_sequences=seq_extractor.get_compressed(),     # 全部样本的压缩表示
        heatmap_data=seq_extractor.get_heatmap_data(),           # 增量热力图
        cumulative_snapshots=seq_extractor.get_cumulative_snapshots(),
        transition_flags=seq_extractor.get_transition_flags(),
        ...
    )
    retreat_panel.set_extracted_data(collector.get_extracted('vulnerability'))
    worst_impact_panel.set_extracted_data(collector.get_extracted('worst_impact'))
```

### 5.7 如何保证不丢弃需要的数据

**原则：每个分析需要的数据都在提取阶段被提取并保留，compact 在回调结束后被 GC。**

| 分析级别 | 提取的数据 | 保留量 | 内存 |
|---------|----------|--------|------|
| A（聚合级） | `extract_aggregate` → 聚合字典 | 全部样本 | ~0.9 KB/样本 |
| B（累积快照级） | `DrawSequenceExtractor._update_cumulative` → 累积快照 | 全部样本 | ~0.3 KB/样本 |
| C（逐抽级） | 完整序列 200 条 + 压缩表示全部 | 200 条 + 全部压缩 | ~3 MB + ~0.2 KB/样本 |
| 脆弱性 | `extract_vulnerability` → 资源+成功标志 | 全部样本 | ~0.1 KB/样本 |
| 最差影响 | `extract_worst_impact` → 资源+卡计数+成功标志 | 全部样本 | ~0.05 KB/样本 |
| 过程分析 | `extract_process` → 事件标签+成功标志 | 全部样本 | ~0.05 KB/样本 |

**100w 样本时总内存 ~600 MB**，vs 改造前 ~21 GB。

### 5.8 如果某些分析保留了详细数据，如何压缩内存需求

流式架构的核心优势是**每个提取器只提取自己需要的数据**。如果某个分析需要详细数据，只有该分析对应的提取器会保留详细数据，其他提取器只保留聚合数据。

但更进一步的优化是：**即使是需要详细数据的分析，也可以用压缩表示替代完整数据**。

| 需要详细数据的分析 | 完整数据 | 压缩表示 | 压缩比 |
|-----------------|---------|---------|--------|
| 时间序列 | `draw_card_ids`（~15 KB） | `target_acquire_positions`（~0.1 KB） | ~150x |
| 热力图 | `draw_card_ids` + 逐抽资源 | `target_acquire_positions` + `ssr_acquire_positions` + `draw_resources_consumed/gained`（~0.4 KB） | ~37x |
| 瀑布图 | `draw_card_ids` | `target_acquire_positions`（~0.1 KB） | ~150x |
| 累积分析 | 完整 IV 列表 | `pool_end_card_counts` + `pool_end_cumulative_*`（~0.3 KB） | ~50x |

**压缩表示的局限性**：
- `target_acquire_positions` 只记录目标卡的获得位置，不记录非目标卡的 ID。如果未来需要"非目标卡的获得时序"，需要扩展压缩表示。
- 资源维度使用逐抽真实值（`draw_resources_consumed`/`draw_resources_gained`），精确无近似。

### 5.9 与自适应模拟（P3）的兼容

自适应模拟的核心是实时监控 RSE，达到目标精度自动停止。这与流式架构完美兼容：

```
用户选择"自适应精度模式" + 目标 RSE
    ↓
gacha_panel 发起模拟（初始量 = 用户设定值）
    ↓
run_batch_parallel(on_result=collector.on_result, stop_condition=rse_checker)
    ↓ 每来一个结果
    ├→ collector.on_result(compact) → 提取 + 丢弃
    └→ rse_checker → 如果 RSE 达标 → 返回 True → 停止模拟
    ↓
模拟完成 → 分发数据给各面板
```

`on_result` 回调是追加式的——自适应停止只是"不再追加"，不影响已有数据。`SharedResultCollector` 不关心模拟何时停止——它只负责提取和累积。

### 5.10 与对偶变量法的兼容

对偶变量法需要配对模拟（原始 + 对偶），每对一起产生然后取平均。在流式架构中：

```python
def on_result_pair(original_compact, antithetic_compact):
    collector.on_result(original_compact)
    collector.on_result(antithetic_compact)
```

对偶变量法的方差缩减在 `StreamingSuccessCounter` 中独立实现——它维护两个计数器（original_success 和 antithetic_success），最终成功率 = (original_success + antithetic_success) / (2 × n_pairs)。这不需要修改 `SharedResultCollector`。

### 5.11 gacha_panel 的改造要点

1. **保留 `_calculate_quick_stats`**：从聚合数据计算，不依赖逐抽数据
2. **新增"精度预设"下拉菜单**：帮助用户选择合适的模拟量（不硬编码精度数值）
3. **可选"追加模拟"按钮**：在已有数据基础上追加更多模拟
4. **可选"自适应精度"复选框**：启用 P3 的自适应停止

## 6. 文件变更清单

### Phase 1：流式基础设施

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `core/streaming.py` | 新增 | `StreamingAnalyzer`、`StreamingSuccessCounter`、`SharedResultCollector`、`DrawSequenceExtractor`、各提取函数 |
| `gui/batch_simulator.py` | 修改 | `run_batch_parallel` 新增 `on_result` 参数 |

### Phase 2：compact 新增字段

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `service/gacha_service.py` | 修改 | 新增 `pool_card_counts`、`pool_pity_counts`、`draw_pity_names`、`draw_pity_counter_max` |

### Phase 3：gacha_panel + main_window 改造

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `gui/gacha_panel.py` | 修改 | 使用 `on_result` + `SharedResultCollector`，支持追加模拟 |
| `gui/main_window.py` | 修改 | `on_simulation_finished` 改为分发预提取数据 |

### Phase 4：analysis_panel 改造

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `gui/analysis_panel.py` | 修改 | 接收预提取数据；删除 `_compact_to_iv_list`；GDR 分布改用 compact 路径；热力图/累积/转变改为增量计算 |
| `core/gdr.py` | 修改 | 新增 `compute_gdr_from_cumulative` |

### Phase 5：脆弱性分析 + 最差影响改造

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `gui/retreat_panel.py` | 修改 | `set_simulation_results` → `set_extracted_data` |
| `core/vulnerability.py` | 修改 | 新增入口接收预提取数据 |
| `gui/worst_impact_panel.py` | 修改 | 同 retreat_panel |
| `core/worst_impact.py` | 修改 | `ConditionalResourceDistribution` 改为接收预提取数据 |

## 7. 性能预期

| 场景 | 模拟量 | 改造前内存 | 改造后内存 |
|------|--------|----------|----------|
| 全部面板共享 | 1,000 | ~22 MB | ~22 MB |
| 全部面板共享 | 10,000 | ~220 MB | ~60 MB |
| 全部面板共享 | 100,000 | ~2.1 GB | ~120 MB |
| 全部面板共享 | 1,000,000 | ~21 GB | ~600 MB |

改造后内存主要来自：
- aggregate 提取数据：~0.9 KB/样本
- draw_sequence 保留 200 条：~3 MB（固定）
- 增量热力图/累积/转变数据：~0.4 KB/样本
- vulnerability/worst_impact/process 提取数据：~0.2 KB/样本

总计 ~1.5 KB/样本（vs 改造前 ~22 KB/样本），且 draw_sequence 部分与 N 无关。

## 8. 审查修复记录

### 8.1 致命问题修复

| 问题 | 根因 | 修复方案 | 涉及章节 |
|------|------|---------|---------|
| 每池卡牌/保底计数缺失 | `card_counts` 是全局的 | compact 新增 `pool_card_counts` + `pool_pity_counts` | §3.3, §3.13 |
| 累积GDR指标不全 | 只预计算5个指标 | 扩展为 `cumulative_card_counts` + `cumulative_consumed` | §3.5 |
| 过程分析事件分类不全 | 缺少 `draw_card_ids` | 改为预分类事件标签 `pool_events` | §3.3 |

### 8.2 显著问题修复

| 问题 | 修复方案 | 涉及章节 |
|------|---------|---------|
| 资源热力图缺少 total_consumed/gained | `_update_heatmap` 从 compact 读取逐抽真实资源值 | §3.5 |
| 预设阈值需要 InfoVector 列表 | 改用 `compute_gdr_from_compact` | §3.6 |
| GDR统计表硬编码函数列表 | ✅ P0 已修复：遍历 `UNIFIED_GDR_REGISTRY` | §4 |

### 8.4 资源维度 bug 与线性插值问题（✅ 已修复）

经全面排查，紧凑路径（`run_simulation_compact` + `_compact_to_iv_list`）存在以下 bug 和设计缺陷：

#### Bug 1：`total_gained` 丢失卡片奖励 resources_gained（✅ 已修复）

**根因**：`run_simulation_compact` 中，卡片抽中时获得的 `resources_gained`（如SSR兑换币）只加入了 `resources` 状态，**没有加入 `total_gained`**。`total_gained` 只累加了等待动作的资源收益。

**影响范围**：
- `resource_remaining`：`initial + gained - consumed`，gained 偏低 → 结果偏低
- `CumulativeResourceEfficiency`：`gained / consumed`，gained 偏低 → 效率偏低
- 每池资源收益：缺失卡片奖励收益
- 累积资源快照：gained 缺失卡片奖励

**修复**：在 `run_simulation_compact` 的 DrawAction 分支中，将卡片奖励 `resources_gained` 同时加入 `total_gained`。

#### Bug 2：`_compact_to_iv_list` 均摊资源值（✅ 已修复）

**根因**：`_compact_to_iv_list` 将 `total_consumed / total_draws` 和 `total_gained / total_draws` 均摊到每一步，导致：
1. 所有 InfoVector 的 `resources_consumed` 和 `resources_gained` 完全相同
2. 多池不同单抽成本时，每池消耗不正确
3. 等待收益被均摊到所有抽卡步骤，按时间截断时比例不正确

**影响范围**：所有经过 `_compact_to_iv_list` 转换后使用 `iv.resources_consumed`/`iv.resources_gained` 的分析：
- 热力图 resource 维度：均摊值 × progress = 双重近似
- `resource_remaining`：gained 缺失卡片奖励 + consumed 均摊失真
- 每池资源消耗/收益：各池成本不同时不正确
- 累积资源快照：consumed 近似 + gained 缺失卡片奖励
- `CumulativeResourceEfficiency`：gained 偏低

**修复**：
1. compact dict 新增 `draw_resources_consumed: List[Dict[str, float]]` 和 `draw_resources_gained: List[Dict[str, float]]`，记录每次抽卡的精确资源消耗和收益
2. 等待动作的资源收益累积到 `_pending_wait_gains`，归入下一次抽卡的 `draw_resources_gained`
3. `_compact_to_iv_list` 优先使用逐抽真实值，仅对旧格式 compact dict 回退到均摊

#### Bug 3：热力图线性插值近似（✅ 已修复）

**根因**：热力图 resource 维度使用 `total_consumed × progress` 和 `total_gained × progress` 线性插值估算中间时刻资源剩余。这在以下情况不准确：
1. 多池不同成本时，资源消耗不是线性的
2. 卡片奖励的 resources_gained 在特定抽卡步骤发生，不是均匀分布的
3. 等待收益在特定时间点发生，不是均匀分布的

**修复**：热力图改用逐抽真实资源值，通过 `draw_resources_consumed` 和 `draw_resources_gained` 计算精确的累积资源状态。

#### 紧凑格式 GDR 函数不受影响

紧凑格式的 GDR 函数（如 `_gdr_resource_remaining`、`_gdr_resource_efficiency`）直接读取 `final_resources` 和 `total_consumed`，不经过 `_compact_to_iv_list`，结果正确。

### 8.3 GDR 成功判断统一化（✅ P0 已完成）

| 修复前 | 修复后 |
|--------|--------|
| worst_impact.py 70 行重复逻辑 | ✅ 使用 `SuccessChecker` |
| analysis_panel.py 硬编码 9 个函数 | ✅ 遍历 `UNIFIED_GDR_REGISTRY` |
| 5 个数值不一致 bug | ✅ 已修复 |

### 8.5 广谱debug修复记录（✅ 已修复）

流式重构实施后进行广谱debug，发现并修复以下 9 项问题：

| # | 问题 | 严重度 | 修复方案 |
|---|------|--------|---------|
| 1 | `name == primary_name` 永远为False：`gdr_dists` 的 key 是英文，`primary_name` 是中文显示名 | P0 | 改为 `name == primary_key` |
| 2 | 表格/图例显示英文 key 而非中文：遍历 `gdr_dists.items()` 时直接用 `name`（英文 key）作标签 | P0 | 添加 `_key_to_display` 映射，所有显示位置使用 `_key_to_display.get(name, name)` |
| 3 | `_on_analysis_done` 中 `risk_worst_case_`/`risk_best_case_` chart key 后缀为英文 key，显示未翻译 | P0 | 提取后缀后通过 `_key_to_display` 翻译 |
| 4 | `compute_gdr_from_cumulative` 缺少 `initial_resources`：`pseudo_final_resources` 不含初始资源 | P0 | 添加 `initial_resources` 参数，`pseudo_final_resources = initial + gained - consumed` |
| 5 | 空 `draw_sequences` 生成空图表：time_series/waterfall 在无数据时仍创建空图 | P2 | 添加 `if self.draw_sequences:` 守卫 |
| 6 | `risk_never_fail` 未处理 `dist.n == 0`：空数据时 `probability_above(0.5)` 可能异常 | P2 | 添加 `if dist.n > 0:` 检查 |
| 7 | `time_heatmap` 无数据时生成空白图表 | P2 | 添加 `if self.heatmap_data or self.draw_sequences:` 守卫 + `has_content` 标志 |
| 8 | 热力图 SSR 识别使用字符串匹配启发式 `'ssr' in cid.lower()` | P2 | 改用 `cid in ssr_ids` 精确匹配 |
| 9 | `PoolSnapshot.resources_consumed` 永远为空：`extract_aggregate` 未提取 per-pool 资源数据 | P2 | `extract_aggregate` 新增 `pool_resources_consumed`/`pool_resources_gained` 字段 |

**附带清理**：
- 删除死代码 `_compact_to_iv_list` 函数（46 行）
- 冗余字典 `_gdr_key_by_name_cond` 和 `_gdr_key_by_name` 替换为已有的 `_display_to_key`
- 变量名 `n_histories` 改为 `n_sims`

### 8.6 全代码库审计结论（✅ 无遗留问题）

对全部 49 个 .py 文件进行线性插值/非精确数据审计，结论：

- **所有核心计算路径均使用逐抽真实资源数据**，无线性插值或均摊近似
- `streaming.py` 的 `_update_heatmap` 和 `_update_cumulative` 使用 `draw_resources_consumed[i]`/`draw_resources_gained[i]` 逐抽累加
- `gdr.py` 的 `compute_gdr_from_compact` 和 `compute_gdr_from_cumulative` 使用精确值
- `gacha_service.py` 的 `run_simulation_compact` 每抽精确记录
- `distribution.py` 的经验分位数线性插值是标准统计方法，非资源近似
- `resource_gain.py` 的 `LinearResourceGain` 是用户定义的资源获取模型
- `pity.py` 的软保底概率渐变是保底机制的设计公式
- `analysis_panel.py` 的 `imshow(interpolation='bilinear')` 是 matplotlib 渲染参数
