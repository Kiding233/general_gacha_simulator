# GDR 分箱与绘图策略实施计划

> 创建日期：2026-05-27 | 来源：`docs/reports/GDR分箱与绘图策略报告.md`
> 状态：设计中

---

## 背景

`docs/reports/GDR分箱与绘图策略报告.md` 对全部 17 种 GDR 逐一评估了当前 `analysis_panel.py` 中 `_is_discrete` + `_hist_params` 绑图逻辑的正确性，发现 7 项需要改进的问题。本计划将其转化为可执行的实施步骤。

**已完成部分**：
- P15 问题H（脆弱性分箱策略对齐报告）已在 2026-05-27 实施完成——`vulnerability.py` 中的 `_detect_step_size()` + `_compute_aligned_bins()` 可复用到 `analysis_panel.py`

---

## 一、高优先级：当前做法有实质性错误（4 项）

### H1. A 类 GDR 有限格点检测

**影响 GDR**：`target_achievement`(#2)、`target_collection`(#3)、`ssr_collection`(#4)

**问题**：当前 `_is_discrete` 仅检测「值是否接近整数」，这三个 GDR 的取值是 1/T 的倍数（如 0, 0.333, 0.667, 1.0），不是整数，走 FD 分箱，在 3~10 个格点上做连续直方图。

**方案**：在 `_is_discrete` 之外新增 `_is_finite_grid(samples)` 检测：
- 条件：`len(unique(samples)) ≤ 20`
- 且所有值可表示为 `k / T`（T = 目标卡总数，从 `_gdr_context.target_specs` 获取）
- 满足时返回条形图模式：`bins = sorted(unique_values)`，`density=False`

**涉及文件**：`gacha_simulator/gui/analysis_panel.py`

**预估**：<2h

---

### H2. `resource_consumed` 步长检测

**影响 GDR**：`resource_consumed`(#9)

**问题**：当前 `_is_discrete` 返回 True（160 是整数），走 `range(0, max+1)` 逐整数分箱，在 0~16000 之间创建 ~16001 个 bin，绝大多数为空。

**方案**：复用 `vulnerability.py` 的 `_detect_step_size()` 逻辑（或将其提取到 `core/distribution.py` 作为公共函数）。
- 检测步长 = cost_per_draw（典型 160）
- 若 `std(values % step) / step < 0.3`，确认格点结构
- 按 step 分箱，边界对齐到 0（消耗从 0 开始）

**涉及文件**：`gacha_simulator/gui/analysis_panel.py`、`gacha_simulator/core/distribution.py`（可选：提取公共步长检测函数）

**预估**：<1h

---

### H3. `resource_remaining` 格点结构

**影响 GDR**：`resource_remaining`(#10)

**问题**：当前 `_is_discrete` 返回 False（浮点数），走 FD 分箱，忽略 cost_per_draw 的自然格点结构。

**方案**：同 H2，检测 cost_per_draw 步长。
- `use_draw_units` 模式下值域转为整数（除以 cost），退化为 Δ=1 的 B₁，走整数分箱
- 非 `use_draw_units` 模式：检测步长 = cost_per_draw，若通过则格点分箱，否则回退 FD

**涉及文件**：`gacha_simulator/gui/analysis_panel.py`

**预估**：<1h（与 H2 共享步长检测逻辑）

---

### H4. `resource_per_card` inf 处理

**影响 GDR**：`resource_per_card`(#12)

**问题**：obtained=0 时 GDR 值为 `inf`，当前未处理，传给 matplotlib 会导致静默丢弃或报错。Plotly 迁移后同样需要处理。

**方案**：
- 分箱前分离有限值和 inf 值
- 统计 inf 占比，在图表标题或注释中标注（如「inf: 3.2% (32/1000)」）
- 直方图仅基于有限值绑图
- ECDF 在 inf 处不连续（可选标注）

**涉及文件**：`gacha_simulator/gui/analysis_panel.py`、`gacha_simulator/visualization/plotly_charts.py`

**预估**：<1h

---

## 二、中优先级：改善但不紧急（2 项）

### M1. C 类 GDR 叠加 KDE

**影响 GDR**：`resource_efficiency`(#11)、`weapon_character_ratio`(#13)、`draw_conversion_efficiency`(#14)

**问题**：C 类 GDR 格点间距可忽略，适合 KDE 平滑。当前缺少 KDE 叠加。

**方案**：
- 在 `ChartSpec` 中为直方图类型新增 `kde_x`/`kde_y` 可选字段
- `PlotlyRenderer` 渲染时若有 KDE 数据则叠加曲线
- KDE 带宽选择 Scott 规则（`n**(-1/5)`）

**涉及文件**：`gacha_simulator/visualization/chart_spec.py`、`gacha_simulator/visualization/plotly_charts.py`、`gacha_simulator/gui/analysis_panel.py`

**预估**：<2h

---

### M2. B₁ 类分箱起点偏移

**影响 GDR**：`resource_remaining`(#10)、`resource_consumed`(#9)

**问题**：日收入产生多种偏移量时，从 0 起步的分箱边界可能切割梳齿。应检测 `R₀ = median(r mod Δ)`，bin 边界对齐到 `R₀ + k·Δ`。

**方案**：复用 `vulnerability.py` 的 `_compute_aligned_bins()` 逻辑。
- H2/H3 中使用 `_compute_aligned_bins()` 替代简单的从 0 起步
- 注：`resource_consumed` 从 0 起步天然对齐（无日收入偏移），此修复主要对 `resource_remaining` 有意义

**涉及文件**：`gacha_simulator/gui/analysis_panel.py`

**预估**：<1h

---

## 三、低优先级：锦上添花（1 项）

### L1. `all_targets` 专用展示

**影响 GDR**：`all_targets`(#1)

**问题**：二元 {0, 1} GDR 用直方图展示意义不大，更适合成功率数值 + 饼图/条形图。

**方案**：
- 检测到二元 GDR 时，UI 切换为成功率数值卡片 + 饼图（或 0/1 条形图）
- 可选：在单 GDR 分布面板中根据 GDR 类型自动选择图表形式

**涉及文件**：`gacha_simulator/gui/analysis_panel.py`、`gacha_simulator/visualization/plotly_charts.py`

**预估**：<1h

---

## 四、依赖关系

```
H1（A 类检测）── 独立
H2（consumed 步长）── 独立 ─┐
H3（remaining 格点）── 独立 ─┤ 共享步长检测逻辑
H4（inf 处理）── 独立        │
M1（KDE 叠加）── 独立        │
M2（分箱起点偏移）── 依赖 H2/H3 ─┘
L1（all_targets 专用）── 独立
```

H1~H4 全部独立可并行。M2 依赖 H2/H3 的步长检测（需要先有步长才能算偏移）。其余无依赖。

---

## 五、实施策略

### 阶段一：核心修复（H1~H4，<1 天）

```
Step 1: 提取公共步长检测函数到 core/distribution.py（从 vulnerability.py 提取 _detect_step_size + _compute_aligned_bins）
Step 2: 改造 _is_discrete → 新增 _is_finite_grid（H1）
Step 3: 改造 _hist_params → 对 B₁ 类注入步长检测（H2, H3）
Step 4: 在 _hist_params 或绑图入口处处理 inf（H4）
```

### 阶段二：增强（M1~M2，<1 天）

```
Step 5: ChartSpec + PlotlyRenderer 支持 KDE 叠加（M1）
Step 6: B₁ 类分箱起点偏移对齐（M2）
```

### 阶段三：优化（L1，<1h）

```
Step 7: all_targets 专用展示（L1）
```

### 阶段四：验证

```
Step 8: 在 GUI 中验证每种 GDR 的绑图效果
Step 9: 运行全部测试确保无回归
```

---

## 六、需要注意的边界条件

| 边界 | 处理 |
|------|------|
| 样本数 < 5 | 步长检测不可靠，回退 FD |
| 唯一样本 ≤ 2 | 现有单 bin 路径已处理 |
| `use_draw_units=True` | `resource_remaining` 除以 cost 后变为 Δ=1 整数，走现有 `_is_discrete` 路径 |
| 步长检测失败 | 回退 FD（原逻辑不动） |
| inf 占比 = 0% | 不显示 inf 标注 |
| inf 占比 = 100% | 显示警告，不绑直方图 |
| Plotly 渲染端 | inf 值在 JSON 序列化时需替换为 `None` 或字符串标注 |

---

## 七、与已有代码的关系

- `vulnerability.py` 的 `_detect_step_size()` 和 `_compute_aligned_bins()` 已验证可用，计划提取到 `core/distribution.py` 作为公共函数，避免代码重复
- `analysis_panel.py` 的 `_hist_params` 已有三个分支：单值 → 整数分箱 → FD。改造后扩展为：单值 → 有限格点（H1）→ 格点步长（H2/H3）→ 整数分箱（现有）→ FD（现有）
- GDR 分布的山脊线图（`_build_ridge_chart`）同样调用 `_hist_params`，修复自动生效
