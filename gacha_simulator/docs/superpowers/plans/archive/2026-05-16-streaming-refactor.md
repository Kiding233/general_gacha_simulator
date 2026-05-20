# 流式模拟架构重构实施计划

## 前置依赖

- 设计文档：`/workspace/docs/superpowers/specs/2026-05-16-streaming-refactor-design.md`
- P0（GDR 统一管理）已完成：`UNIFIED_GDR_REGISTRY`、`SuccessChecker`、5 个数值 bug 修复、6 处硬编码消除
- 本计划应在过程分析功能实施之前完成

## 设计逻辑

### 核心思路

当前架构是"先模拟全部→再分析"：跑 N 次模拟 → 生成 N 个 compact dict（每个 ~22 KB）→ 存入列表 → 分发给各面板。100w 次模拟需要 ~21 GB 内存。

核心矛盾：compact dict 中逐抽记录（`draw_card_ids` 等）占 ~80% 内存，但绝大多数分析根本不需要逐抽记录——它们只需要聚合数据（`card_counts`、`final_resources` 等）。

新架构改为"边模拟→边提取→边丢弃"：每跑完一次模拟 → 从 compact 中提取各分析需要的数据 → 丢弃 compact → 只保留提取出的轻量数据。

### 数据需求分级

经过逐项审查 21 个分析方法，数据需求分为三级：

**级别 A：聚合级（14/21 个分析）**

核心逻辑是"对每个样本算一个 GDR 值，然后构建经验分布"。GDR 值可通过 `compute_gdr_from_compact` 从聚合字段直接计算。

包括：GDR 分布、VaR/CVaR、最差/最好情形、从未失败、条件分布、预设阈值、相关性、GDR 统计、脆弱性分析、最差影响分析、快速统计、每池抽卡数、每池目标卡数、每池保底数。

每个样本只需保留 ~0.9 KB 的聚合字典。

**级别 B：累积快照级（3/21 个分析）**

需要知道"截止每个池子结束时"的累积状态（如已抽到几张目标卡、消耗了多少资源），而非仅最终状态。

包括：截止每池 GDR 分布、转变分析（all_targets 模式）、转变分析（any_ssr/per_pool 模式）。

每个样本额外保留 ~0.3 KB 的累积快照。

**级别 C：逐抽级（4/21 个分析）**

需要追踪 GDR 随抽卡步骤的演化——"第 N 抽时已获得几张目标卡"。必须知道过程信息。

包括：时间序列、时间-GDR 热力图、3D 瀑布图、2D 瀑布图。

完整逐抽序列 ~15 KB/样本，但可以用压缩表示替代（~0.2 KB/样本）。

### 逐抽数据的压缩表示

级别 C 的分析不需要完整 `draw_card_ids`，只需要"目标卡在第几抽获得"：

```
原始数据：draw_card_ids = ['SR_1', 'A', 'SR_2', 'B', 'A', 'SSR_1', ...]  （~15 KB）
压缩表示：target_acquire_positions = [1, 4]    （目标卡在第1、4抽获得，~0.1 KB）
          ssr_acquire_positions = [5]           （SSR在第5抽首次获得，~0.05 KB）
          total_draws = 90                      （总抽卡数，8 B）
```

从压缩表示可重建级别 C 分析需要的全部信息：
- 时间序列：扫描 `target_acquire_positions`，逐步累积目标卡数
- 热力图 achievement 维度：同上
- 热力图 resource 维度：`draw_resources_consumed` + `draw_resources_gained` → 逐步累加精确资源状态（不再使用线性插值）
- 热力图 ssr 维度：扫描 `ssr_acquire_positions`，逐步累积 SSR 种类数
- 瀑布图：扫描 `target_acquire_positions`，逐步累积目标卡数

**关于资源维度**：compact dict 已新增 `draw_resources_consumed` 和 `draw_resources_gained`，记录每次抽卡的精确资源消耗和收益（含卡片奖励和等待收益）。所有资源维度分析使用逐抽真实值累加，不再使用线性插值近似。

**已修复的 bug**：
1. `total_gained` 丢失卡片奖励 resources_gained：卡片抽中时的资源收益只加入了 `resources` 状态，没有加入 `total_gained`。已修复。
2. `_compact_to_iv_list` 均摊资源值：将 `total_consumed/total_draws` 和 `total_gained/total_draws` 均摊到每一步，多池不同成本时不正确。已修复：新增逐抽真实值字段，删除 `_compact_to_iv_list` 死代码。
3. 热力图线性插值近似：使用 `total_consumed × progress` 估算中间资源状态，多池不同成本和卡片奖励收益时不准确。已修复：改用逐抽真实值累加。
4. `name == primary_name` 永远为False：`gdr_dists` 的 key 是英文，`primary_name` 是中文显示名。已修复：改为 `name == primary_key`。
5. 表格/图例显示英文 key 而非中文：遍历 `gdr_dists.items()` 时直接用英文 key 作标签。已修复：添加 `_key_to_display` 映射。
6. `compute_gdr_from_cumulative` 缺少 `initial_resources`。已修复：添加参数。
7. 空 `draw_sequences` 生成空图表。已修复：添加守卫检查。
8. `risk_never_fail` 未处理 `dist.n == 0`。已修复：添加空数据检查。
9. `time_heatmap` 无数据时生成空白图表。已修复：添加守卫 + `has_content` 标志。
10. 热力图 SSR 识别使用字符串匹配启发式。已修复：改用 `ssr_ids` 集合精确匹配。
11. `PoolSnapshot.resources_consumed` 永远为空。已修复：`extract_aggregate` 新增 `pool_resources_consumed`/`pool_resources_gained` 字段。

### 完整数据流

```
用户点击"运行模拟"（如 10,000 次）
    ↓
gacha_panel 创建 SharedResultCollector，注册 5 个提取器：
    ├→ 'aggregate'        → extract_aggregate
    ├→ 'vulnerability'    → extract_vulnerability
    ├→ 'worst_impact'     → extract_worst_impact
    ├→ 'process'          → extract_process
    └→ 'draw_sequence'    → DrawSequenceExtractor
    ↓
run_batch_parallel(on_result=collector.on_result)
    ↓ 每跑完一次模拟，产生一个 compact dict（~22 KB）
    ↓
    collector.on_result(compact)
        ├→ extract_aggregate(compact)       → 聚合字典（~0.9 KB）→ 追加到列表
        ├→ extract_vulnerability(compact)    → {pool_end_resources, success}（~0.1 KB）→ 追加到列表
        ├→ extract_worst_impact(compact)     → {final_resources, card_counts, success}（~0.05 KB）→ 追加到列表
        ├→ extract_process(compact)          → {pool_events, success}（~0.05 KB）→ 追加到列表
        └→ DrawSequenceExtractor(compact)
            ├→ 如果 < 200 条：保留完整逐抽序列（~15 KB）
            ├→ 否则：只保留压缩表示（~0.2 KB）
            ├→ _update_heatmap：增量更新热力图矩阵
            ├→ _update_cumulative：增量更新累积快照
            └→ _update_transition：增量更新转变标记
    ↓
    compact dict 被 GC 回收
    ↓
    10,000 次模拟完成
    ↓
gacha_panel 从 collector 中提取数据，分发给各面板：
    ├→ gacha_panel._calculate_quick_stats(aggregate_data)     → 快速统计表
    ├→ analysis_panel.update_results(
    │       aggregate_data,                                   → 级别 A 的 14 个分析
    │       draw_sequences=200条完整序列,                      → 时间序列画 20 条路径
    │       compressed_sequences=全部压缩表示,                  → 热力图/瀑布图
    │       heatmap_data,                                     → 增量热力图
    │       cumulative_snapshots,                             → 级别 B 的累积分析
    │       transition_flags)                                 → 转变分析
    ├→ retreat_panel.set_extracted_data(vulnerability_data)    → 脆弱性分析
    └→ worst_impact_panel.set_extracted_data(worst_impact_data) → 最差影响分析
```

### 如何保证不丢弃需要的数据

**原则：每个分析需要的数据都在提取阶段被提取并保留，compact 在回调结束后被 GC。**

1. **级别 A**：`extract_aggregate` 提取了全部聚合字段，所有 13 个 GDR 指标都可计算
2. **级别 B**：`DrawSequenceExtractor._update_cumulative` 在每个池子结束时计算累积快照，包含 `cumulative_card_counts`、`cumulative_consumed`、`cumulative_draws`、`cumulative_pity_draws`
3. **级别 C**：保留 200 条完整逐抽序列 + 全部样本的压缩表示
4. **脆弱性**：`extract_vulnerability` 提取了 `pool_end_resources`、`pool_end_pity_states`、`success`
5. **最差影响**：`extract_worst_impact` 提取了 `final_resources`、`card_counts`、`success`

如果某个分析需要的数据没有被任何提取器提取，该分析就会失败。因此每个提取器提取的字段必须恰好覆盖对应分析的全部需求。

### 模拟量决策

**模拟量由用户统一决定，所有面板共享同一次模拟的数据。** gacha_panel 是统一模拟入口，保留 `_calculate_quick_stats`。

可选功能：
- "精度预设"下拉菜单：帮助用户选择合适的模拟量（不硬编码精度数值）
- "追加模拟"按钮：在已有数据基础上追加更多模拟（用户主动触发，非面板自动触发）
- "自适应精度"复选框：启用 P3 的自适应停止

## Task 1：流式基础设施 — streaming.py + on_result 回调

**目标**：创建流式分析工具模块 + 修改 run_batch_parallel 支持回调

**内容**：

1. 新建 `core/streaming.py`：
   - `StreamingAnalyzer` 抽象基类（`on_result` + `get_result`）
   - `StreamingSuccessCounter`（内部持有 `SuccessChecker`）
   - `SharedResultCollector`（共享流式收集器，管理多个提取器，支持 `reset` 和追加模拟）
   - `DrawSequenceExtractor`（逐抽序列提取器，保留 200 条完整序列 + 全部样本压缩表示 + 增量计算热力图/累积/转变数据）
   - 各面板的提取函数：`extract_aggregate`（含 `pool_card_counts` + `pool_pity_counts`）、`extract_vulnerability`、`extract_worst_impact`、`extract_process`（预分类事件标签）

2. 修改 `gui/batch_simulator.py`：
   - `run_batch_parallel` 新增 `on_result: Optional[Callable[[Dict], None]]` 参数
   - 单线程模式：每个结果立即回调，不累积
   - 多线程模式：`imap_unordered` 消费端立即回调，不累积
   - 不传 `on_result` 时行为不变

**验证**：
- 使用 on_result 回调时，回调次数 = num_simulations
- 不使用 on_result 时，行为与当前完全一致
- StreamingSuccessCounter 结果与 compute_success_probability 一致

**产出文件**：新建 `core/streaming.py`，修改 `gui/batch_simulator.py`

## Task 2：compact 新增字段

**目标**：`run_simulation_compact` 新增每池级别数据和过程分析字段

**内容**：

1. 修改 `service/gacha_service.py`：
   - 新增 `pool_card_counts: Dict[str, Dict[str, int]]`（每池每卡获得数量）
   - 新增 `pool_pity_counts: Dict[str, int]`（每池保底触发次数）
   - 新增 `draw_pity_names: List[Optional[str]]`（每次抽卡触发的保底机制名）
   - 新增 `draw_pity_counter_max: List[int]`（每次抽卡时该池最接近触发的保底计数器值）
   - ✅ 已完成：新增 `draw_resources_consumed: List[Dict[str, float]]`（每次抽卡的精确资源消耗）
   - ✅ 已完成：新增 `draw_resources_gained: List[Dict[str, float]]`（每次抽卡的精确资源收益，含卡片奖励+等待收益）
   - ✅ 已完成：修复 `total_gained` 丢失卡片奖励 resources_gained 的 bug

**验证**：
- 新增字段的值与保底逻辑一致
- compact 结果大小增加 ~1.2 KB/样本（可接受）
- 每池目标卡数分析可从 `pool_card_counts` 正确计算

**产出文件**：修改 `service/gacha_service.py`

## Task 3：gacha_panel + main_window 改造

**目标**：gacha_panel 使用 SharedResultCollector，main_window 分发预提取数据

**内容**：

1. 修改 `gui/gacha_panel.py`：
   - 创建 SharedResultCollector，注册各提取器
   - `run_batch_parallel` 传入 `on_result=collector.on_result`
   - 模拟完成后通过 signal 传递 collector（而非 results 列表）
   - `_calculate_quick_stats` 从 aggregate 数据计算（保留此功能）
   - 支持追加模拟（`append_simulation`）

2. 修改 `gui/main_window.py`：
   - `on_simulation_finished` 接收 collector
   - 从 collector 提取各面板需要的数据并分发：
     - analysis_panel: aggregate_data + draw_sequences + compressed_sequences + heatmap_data + cumulative_snapshots + transition_flags
     - retreat_panel: vulnerability 提取数据
     - worst_impact_panel: worst_impact 提取数据

**验证**：
- 模拟后各面板正确接收到数据
- gacha_panel 的快速统计与改造前一致
- 追加模拟后数据正确累积

**产出文件**：修改 `gui/gacha_panel.py`、`gui/main_window.py`

## Task 4：analysis_panel 改造

**目标**：analysis_panel 使用预提取数据，不再依赖完整 compact 或 InfoVector

**内容**：

1. 修改 `gui/analysis_panel.py`：
   - `update_results` 接收预提取数据（aggregate_data, draw_sequences, compressed_sequences, heatmap_data, cumulative_snapshots, transition_flags）
   - GDR 分布分析：改用 `compute_gdr_from_compact`（从聚合数据计算），不再通过 `_compact_to_iv_list` + `GDR_REGISTRY`
   - 时间序列：从 draw_sequences（200 条）画样本路径
   - 热力图/瀑布图：从压缩表示重建，资源维度使用 `draw_resources_consumed`/`draw_resources_gained` 逐抽真实值累加（不再使用线性插值）
   - 累积分析：从增量累积快照 + `compute_gdr_from_cumulative` 计算任意 GDR 指标，资源数据使用逐抽真实值累加
   - 转变分析：从增量转变标记直接计算
   - 每池分析：从 aggregate_data 中的 `pool_draw_counts`、`pool_card_counts`、`pool_pity_counts` 计算
   - 预设阈值：改用 `compute_gdr_from_compact` 在 aggregate 数据上计算
   - ✅ 已完成：`_compact_to_iv_list` 已删除（死代码，流式重构后不再被调用）

2. 修改 `core/gdr.py`：
   - 新增 `compute_gdr_from_cumulative` 函数

**验证**：
- 所有分析图表与改造前视觉一致
- GDR 分布数值与改造前一致
- 不再依赖 InfoVector 列表
- 累积分析支持所有 UNIFIED_GDR_REGISTRY 中的 GDR 指标

**产出文件**：修改 `gui/analysis_panel.py`、`core/gdr.py`

## Task 5：脆弱性分析 + 最差影响改造

**目标**：retreat_panel 和 worst_impact_panel 使用预提取数据

**内容**：

1. 修改 `gui/retreat_panel.py`：
   - `set_simulation_results` → `set_extracted_data`，接收预提取的 vulnerability 数据
   - RetreatWorker 接收预提取数据而非完整 compact 列表

2. 修改 `core/vulnerability.py`：
   - `compute_vulnerability_analysis` 新增入口，接收预提取数据
   - 内部计算逻辑不变

3. 修改 `gui/worst_impact_panel.py`：
   - `set_simulation_results` → `set_extracted_data`，接收预提取的 worst_impact 数据

4. 修改 `core/worst_impact.py`：
   - `ConditionalResourceDistribution` 改为接收预提取数据

**验证**：
- 脆弱性分析图表与改造前一致
- 最差影响分析结果与改造前一致
- 10w 模拟量时内存 <120 MB

**产出文件**：修改 `gui/retreat_panel.py`、`core/vulnerability.py`、`gui/worst_impact_panel.py`、`core/worst_impact.py`

## 执行顺序

```
Task 1 (streaming.py + on_result)  Task 2 (compact新增字段)
    ↓                                  ↓
Task 3 (gacha_panel + main_window)
    ↓
Task 4 (analysis_panel)    Task 5 (脆弱性+最差影响)
    ↓                           ↓
                              过程分析功能实施
```

Task 1/2 可并行。Task 3 依赖 Task 1。Task 4/5 依赖 Task 3，可并行。

## 预期收益

| 场景 | 改造前内存 | 改造后内存 | 改善 |
|------|----------|----------|------|
| 1,000 次模拟 | ~22 MB | ~22 MB | 1x |
| 10,000 次模拟 | ~220 MB | ~60 MB | 3.7x |
| 100,000 次模拟 | ~2.1 GB | ~120 MB | 17.5x |
| 1,000,000 次模拟 | ~21 GB | ~600 MB | 35x |

## 实施状态

**✅ 全部完成（2026-05-17）**

| Task | 状态 | 说明 |
|------|------|------|
| Task 1：流式基础设施 | ✅ 完成 | `streaming.py` 新建，`batch_simulator.py` 新增 `on_result` 回调 |
| Task 2：compact 新增字段 | ✅ 完成 | `draw_resources_consumed`/`draw_resources_gained`/`pool_card_counts`/`pool_pity_counts`；`total_gained` 修复 |
| Task 3：gacha_panel + main_window | ✅ 完成 | `SharedResultCollector` + `DrawSequenceExtractor`，`result_bundle` 分发 |
| Task 4：analysis_panel 改造 | ✅ 完成 | 预提取数据替代 InfoVector；`compute_gdr_from_cumulative` 新增；`_compact_to_iv_list` 删除 |
| Task 5：脆弱性 + 最差影响 | ⏳ 延后 | 当前仍使用完整 compact 列表，待过程分析功能实施时一并改造 |

**广谱debug修复（11 项）**：详见设计文档 §8.5

**全代码库审计**：确认所有资源数据路径使用逐抽精确值，无线性插值或均摊近似遗留。详见设计文档 §8.6
