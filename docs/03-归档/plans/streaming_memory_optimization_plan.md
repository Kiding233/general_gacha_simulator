# 流式分析内存优化方案

## 背景

当前 `SharedResultCollector` + `StreamingAnalyzer` 在 10 万次模拟下内存占用约 3.8 GB，主要来自两个瓶颈：

| 数据结构 | 单次大小 | 10万次 | 位置 |
|----------|---------|--------|------|
| `aggregate_data` (14 字段 × N) | ~19 KB | ~1.9 GB | `SharedResultCollector._extractors` |
| `_heatmap_data` (400 步 × N) | ~19.2 KB | ~1.92 GB | `DrawSequenceExtractor._heatmap_data` |
| `_cumulative_snapshots` | ~5 KB | ~500 MB | `DrawSequenceExtractor._cumulative_snapshots` |
| `_kept_sequences` (max 200) | ~176 KB | ~35 MB | `DrawSequenceExtractor._kept_sequences` |

## 方案 A：heatmap 流式预分箱（最高优先级）

### 原理

`DrawSequenceExtractor._update_heatmap()` 当前为每次模拟的每个抽卡步存储一个 float 值，共 400 步 × N 个 float。改为在提取时直接累加到预分配的直方图箱中，内存从 O(N) 降为 O(1)。

### 改动

`streaming.py` — `DrawSequenceExtractor`：
- `__init__` 中预分配 `self._bins = np.linspace(0, 1, 51)`（50 个箱）
- `_update_heatmap()` 改为将 achievement/resource 值累加到 `self._heatmap_hist[draw_idx][bin_idx]` 而非 append 到列表
- `get_heatmap_data()` 返回 `(bin_edges, histograms)` 元组

`analysis_panel.py` — 热力图绑图代码（约 787-896 行）：
- 当前从 `heatmap_data[draw_idx]['achievement']` 取原始值列表再分箱 → 改为直接使用预分箱直方图
- 改动约 30 行

### 效果

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 内存 (10万次) | ~1.92 GB | ~128 KB |
| CPU（提取阶段） | 无额外开销 | 每步一次 `np.digitize` + 累加 |
| CPU（绑图阶段） | 分箱 + 绑图 | 直接绑图（省去分箱） |

### 风险

低。`np.digitize` 是 O(log bins) 的二分查找，50 个箱约 6 次比较/步，400 步 × 10 万 ≈ 4000 万次比较，总计 < 0.1 秒。

---

## 方案 B：移除 aggregate 派生字段

### 涉及字段

`extract_aggregate()` 中三个从逐抽序列计算而来的字段：

| 字段 | 类型 | 单次大小（估算） |
|------|------|-----------------|
| `pool_resources_consumed` | `Dict[str, Dict[str, float]]` | ~1.6 KB |
| `pool_resources_gained` | `Dict[str, Dict[str, float]]` | ~1.6 KB |
| `pool_counter_max` | `Dict[str, int]` | ~0.7 KB |
| **合计** | | **~3.9 KB/sim → ~390 MB/10万** |

### 消费者分析

| 消费者 | 使用字段 | 用途 |
|--------|---------|------|
| `process_trace.py:173-174` | `pool_res_consumed`, `pool_res_gained` | `compute_pool_gdr_single_pool()` 构造 `pseudo_compact` 计算每池 GDR |
| `process_trace.py:33` | `pool_counter_max` | `infer_events()` 判断事件类型（保底命中/提前命中/跳过） |
| `analysis_panel.py:1006` | `pool_res_consumed` | 每池分析 `PoolSnapshot.resources_consumed` |

### 可行性评估：不可直接移除

这三个字段并非从其他 aggregate 字段派生——它们依赖的原始数据（`draw_pool_ids`、`draw_resources_consumed`、`draw_resources_gained`、`draw_pity_counter_max` 逐抽序列）在提取后已被丢弃。移除字段意味着**永久丢失每池粒度的资源/保底信息**，三个消费者功能将损坏。

### 替代方案

**B1：最小化存储**
- `pool_counter_max`：当前 `Dict[str, int]`（~700 B）已经是最小形式，无法再压缩
- `pool_resources_consumed`/`pool_resources_gained`：当前 `Dict[str, Dict[str, float]]`，通常每个池只有 1 种资源类型。可改为 `Dict[str, float]`（池ID → 单一资源值），节省内层 dict 开销，降至 ~0.4 KB/字段

**B2：延迟计算（不可行）**
- 逐抽序列已丢弃，无法重新遍历

### 结论

B 的实际可行节省约 **200 MB**（B1 方案），且不需要改消费者代码（内层 dict 只有 1 个 key，直接 `.get('draw_resource', 0)` 效果相同）。

---

## 方案 C：小字段 Dict → List 打包

### 原理

aggregate 中 9 个字段使用 `Dict[str, int/float]`，每份 aggregate 独立存储字符串键。对于 24 张卡 × 8 个池的典型配置，10 万份 aggregate 意味着：

- 字符串 `"card_001"` 在内存中出现 10 万次
- 每个 dict 有独立的哈希表开销（~72 bytes 基础 + 每条目 ~50 bytes）

改为 `List[float]` + 全局索引映射：

```python
# 全局（一次性）
CARD_INDEX = {"card_001": 0, "card_002": 1, ...}  # 24 条
POOL_INDEX = {"pool_a": 0, "pool_b": 1, ...}       # 8 条

# 每份 aggregate
card_counts: List[int]     # [3, 0, 1, ...]  长度 24，~200 bytes
# 对比 Dict[str, int]                         ~2 KB
```

### 涉及字段

| 字段 | 条目数 | Dict 大小 | List 大小 | 节省/份 | 10万次节省 |
|------|--------|----------|----------|---------|-----------|
| `card_counts` | 24 cards | ~2 KB | ~200 B | ~1.8 KB | ~180 MB |
| `pool_draw_counts` | 8 pools | ~700 B | ~72 B | ~0.6 KB | ~60 MB |
| `pool_pity_counts` | 8 pools | ~700 B | ~72 B | ~0.6 KB | ~60 MB |
| `total_consumed` | ~3 resources | ~300 B | ~32 B | ~0.27 KB | ~27 MB |
| `total_gained` | ~3 resources | ~300 B | ~32 B | ~0.27 KB | ~27 MB |
| `final_resources` | ~3 resources | ~300 B | ~32 B | ~0.27 KB | ~27 MB |
| `pool_card_counts` | 8×24 nested | ~6 KB | ~400 B | ~5.6 KB | ~560 MB |
| `pool_end_resources` | 8×1 nested | ~1.5 KB | ~72 B | ~1.4 KB | ~140 MB |
| `pool_end_pity_states` | 8 pools | ~1 KB | ~200 B | ~0.8 KB | ~80 MB |
| **合计** | | **~12.8 KB** | **~1.1 KB** | **~11.7 KB** | **~1.17 GB** |

### 计算成本

- Dict 查找：O(1)，含哈希计算 → ~50-100 ns
- List 索引 + 映射查找：两次 O(1) → `card_counts[CARD_INDEX[card_id]]` → ~30-60 ns
- **CPU 影响：可忽略**（纳秒级差异，10 万次遍历总量 < 1ms）

### 代码影响面

需要修改约 13 处 `agg['card_counts'][card_id]` 模式（分布在 `gdr.py` 的 10 个 `_gdr_*` 函数 + `process_trace.py` + `analysis_panel.py`），约 200 行改动。

全局索引映射需要在 `ConfigStore` 或 `SimulationEnv` 中维护，所有消费者通过参数接收。

### 风险

- **维护成本**：新增 GDR 指标或分析面板时必须使用 List 索引模式，容易写出 bug
- **调试困难**：`List[int]` 不如 `Dict[str, int]` 直观，排查数据问题需要对照索引表
- **序列化兼容**：如果 aggregate 需要持久化，List 格式需要额外元数据记录索引顺序

---

## 实施状态（2026-05-23）

| 优先级 | 方案 | 节省 | 风险 | 状态 |
|--------|------|------|------|------|
| **P0** | A：heatmap 流式预分箱 | ~1.92 GB | 低 | **已实施** |
| ~~P1~~ | ~~B：pool 资源字段扁平化~~ | ~~~200 MB~~ | — | **已放弃** |
| ~~P2~~ | ~~C：Dict → List 打包~~ | ~~~1.17 GB~~ | — | **搁置** |

方案 B 已完全放弃。方案 C 标记为搁置，不实施。

方案 A 实施后，10 万次模拟内存从 ~3.8 GB 降至 ~1.9 GB。

---

## 验证

1. 运行 `python -m gacha_simulator.main`，执行批量模拟
2. 热力图绑图正确显示（与原图一致）
3. 每池分析、过程分析面板功能正常
4. `pytest tests/ -x -q` 通过