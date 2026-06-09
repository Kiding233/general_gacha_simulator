# 目标卡/资源搜索可视化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为"最多目标卡"和"最少资源"两个一级面板添加图示，展示成功率随目标卡数量/资源量变化的趋势。

**Architecture:** 在现有面板的结果展示区新增 matplotlib 图表区域。最多目标卡面板：折线图 X=目标卡数量 Y=成功率，标注阈值线。最少资源面板：折线图 X=资源量（抽数）Y=成功率，标注阈值线和搜索区间收敛过程。

**Tech Stack:** PyQt6 + matplotlib（项目已有依赖，`analysis_panel.py` 已使用 Agg 后端 + savefig 模式）

---

## 现有数据结构分析

### 最多目标卡（strategy_panel.py）

**前进法** `ForwardResult`：
- `steps: List[ForwardStep]`，每步有 `added_card_id`、`target_set`（当前集合）、`success_probability`
- X 轴：步骤序号（1, 2, 3...）或目标卡数量
- Y 轴：`success_probability`

**后退法** `BackwardResult`：
- `steps: List[BackwardStep]`，每步有 `removed_card_id`、`target_set`、`success_probability`
- X 轴：步骤序号或剩余目标卡数量
- Y 轴：`success_probability`

### 最少资源（resource_search_panel.py）

**`ResourceSearchResult`**：
- `steps: List[ResourceSearchStep]`，每步有 `iteration`、`resource_value`、`success_probability`、`phase`、`lo_bound`、`hi_bound`
- X 轴：`resource_value`（可换算为抽数）
- Y 轴：`success_probability`
- 额外信息：`lo_bound`/`hi_bound` 显示搜索区间收敛

---

## 文件变更

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `gui/strategy_panel.py` | 修改 | 添加 matplotlib 图表到结果区 |
| `gui/resource_search_panel.py` | 修改 | 添加 matplotlib 图表到结果区 |

---

### Task 1: 最多目标卡面板 — 添加成功率趋势图

**Files:**
- Modify: `gui/strategy_panel.py`

- [ ] **Step 1: 在 `_setup_ui` 的右侧结果区添加图表占位**

在 `steps_group` 之后、`splitter.addWidget` 之前，添加一个 `QGroupBox("成功率趋势")` 包含 `QLabel` 用于显示图表图片。

在 `_setup_ui` 中添加：
```python
self.chart_group = QGroupBox("成功率趋势")
chart_layout = QVBoxLayout(self.chart_group)
self.chart_label = QLabel("运行分析后显示图表")
self.chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
self.chart_label.setMinimumHeight(300)
chart_layout.addWidget(self.chart_label)
right_layout.addWidget(self.chart_group)
```

- [ ] **Step 2: 添加 `_draw_strategy_chart` 方法**

```python
def _draw_strategy_chart(self, result, method):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import tempfile, os

    if not result or not result.steps:
        self.chart_label.setText("无数据")
        return

    steps = result.steps
    if method == 'forward':
        x_labels = [f"+{s.added_card_id}" for s in steps]
        x_title = "步骤（添加目标卡）"
    else:
        x_labels = [f"-{s.removed_card_id}" for s in steps]
        x_title = "步骤（移除目标卡）"

    x = list(range(1, len(steps) + 1))
    y = [s.success_probability for s in steps]
    target_counts = [len(s.target_set) for s in steps]

    fig, ax = plt.subplots(figsize=(8, 4))

    ax.plot(x, y, 'o-', color='#2196F3', linewidth=2, markersize=8, label='成功率')

    for i, (xi, yi, tc) in enumerate(zip(x, y, target_counts)):
        ax.annotate(f'{tc}张\n{yi:.1%}', (xi, yi),
                    textcoords="offset points", xytext=(0, 12),
                    ha='center', fontsize=8)

    threshold = self.success_threshold_spin.value()
    ax.axhline(y=threshold, color='#F44336', linestyle='--', linewidth=1.5,
               label=f'阈值 {threshold:.0%}')

    final_idx = None
    for i, s in enumerate(steps):
        if s.success_probability >= threshold:
            final_idx = i
    if final_idx is not None:
        ax.plot(x[final_idx], y[final_idx], 's', color='#4CAF50', markersize=14,
                markerfacecolor='none', markeredgewidth=2.5, label='最终集合')

    ax.set_xlabel(x_title, fontsize=11)
    ax.set_ylabel('成功率', fontsize=11)
    ax.set_title('成功率随目标卡变化趋势', fontsize=13)
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, rotation=30, ha='right', fontsize=8)
    ax.set_ylim(-0.05, 1.05)
    ax.legend(loc='best', fontsize=9)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    tmp = tempfile.mktemp(suffix='.png')
    plt.savefig(tmp, dpi=150, bbox_inches='tight')
    plt.close()

    from PyQt6.QtGui import QPixmap
    pixmap = QPixmap(tmp)
    self.chart_label.setPixmap(pixmap.scaled(
        self.chart_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation))
    os.unlink(tmp)
```

- [ ] **Step 3: 在 `_display_forward_result` 和 `_display_backward_result` 中调用图表**

在 `_display_forward_result` 末尾添加：
```python
self._draw_strategy_chart(result, 'forward')
```

在 `_display_backward_result` 末尾添加：
```python
self._draw_strategy_chart(result, 'backward')
```

- [ ] **Step 4: 运行项目验证导入无误**

Run: `cd /workspace && python -c "from gacha_simulator.gui.strategy_panel import StrategyPanel; print('OK')"`
Expected: OK

---

### Task 2: 最少资源面板 — 添加成功率趋势图

**Files:**
- Modify: `gui/resource_search_panel.py`

- [ ] **Step 1: 在 `_setup_ui` 的右侧结果区添加图表占位**

在 `steps_group` 之后、`splitter.addWidget` 之前，添加图表区域：

```python
self.chart_group = QGroupBox("成功率-资源趋势")
chart_layout = QVBoxLayout(self.chart_group)
self.chart_label = QLabel("运行搜索后显示图表")
self.chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
self.chart_label.setMinimumHeight(300)
chart_layout.addWidget(self.chart_label)
right_layout.addWidget(self.chart_group)
```

- [ ] **Step 2: 添加 `_draw_resource_chart` 方法**

```python
def _draw_resource_chart(self, result):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import tempfile, os

    if not result or not result.steps:
        self.chart_label.setText("无数据")
        return

    steps = result.steps
    cost = result.cost_per_draw if result.cost_per_draw > 0 else 160

    resources = [s.resource_value / cost for s in steps]
    probs = [s.success_probability for s in steps]
    phases = [s.phase for s in steps]

    fig, ax = plt.subplots(figsize=(8, 4))

    search_mask = [p.startswith('搜索') for p in phases]
    binary_mask = [p.startswith('二分') for p in phases]
    final_mask = [p == '最终验证' for p in phases]

    sr = [r for r, m in zip(resources, search_mask) if m]
    sp = [p for p, m in zip(probs, search_mask) if m]
    br = [r for r, m in zip(resources, binary_mask) if m]
    bp = [p for p, m in zip(probs, binary_mask) if m]
    fr = [r for r, m in zip(resources, final_mask) if m]
    fp = [p for p, m in zip(probs, final_mask) if m]

    if sr:
        ax.plot(sr, sp, 's', color='#FF9800', markersize=7, label='搜索上界', zorder=3)
    if br:
        ax.plot(br, bp, 'o', color='#2196F3', markersize=5, label='二分搜索', zorder=3)
    if fr:
        ax.plot(fr, fp, 'D', color='#4CAF50', markersize=9, label='最终验证', zorder=4)

    threshold = self.success_threshold_spin.value()
    ax.axhline(y=threshold, color='#F44336', linestyle='--', linewidth=1.5,
               label=f'阈值 {threshold:.0%}')

    min_r = result.min_resource / cost
    ax.axvline(x=min_r, color='#4CAF50', linestyle=':', linewidth=1.5,
               label=f'最少资源 ≈{min_r:.1f}抽')

    if len(steps) > 1:
        last_step = steps[-1]
        ax.fill_betweenx([0, 1.05], last_step.lo_bound / cost, last_step.hi_bound / cost,
                         alpha=0.1, color='#2196F3', label='最终搜索区间')

    ax.set_xlabel('资源量（抽数）', fontsize=11)
    ax.set_ylabel('成功率', fontsize=11)
    ax.set_title('成功率随资源量变化趋势', fontsize=13)
    ax.set_ylim(-0.05, 1.05)
    ax.legend(loc='best', fontsize=8)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    tmp = tempfile.mktemp(suffix='.png')
    plt.savefig(tmp, dpi=150, bbox_inches='tight')
    plt.close()

    from PyQt6.QtGui import QPixmap
    pixmap = QPixmap(tmp)
    self.chart_label.setPixmap(pixmap.scaled(
        self.chart_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation))
    os.unlink(tmp)
```

- [ ] **Step 3: 在 `_on_finished` 中调用图表**

在 `_on_finished` 方法中，`self.status_update.emit("资源搜索完成")` 之前添加：
```python
self._draw_resource_chart(result)
```

- [ ] **Step 4: 运行项目验证导入无误**

Run: `cd /workspace && python -c "from gacha_simulator.gui.resource_search_panel import ResourceSearchPanel; print('OK')"`
Expected: OK

---

## 图表设计说明

### 最多目标卡面板图表

**X 轴**：步骤序号，刻度标签为添加/移除的卡ID
**Y 轴**：成功率（0-1）
**元素**：
- 蓝色折线 + 圆点：每步的成功率
- 每点标注：目标卡数量 + 成功率百分比
- 红色虚线：成功率阈值
- 绿色空心方块：最终选中的目标集合（最后一个≥阈值的点）

**理论意义**：直观展示"每多追求一张目标卡，成功率下降多少"，帮助用户在目标数量和成功率之间做权衡。

### 最少资源面板图表

**X 轴**：资源量（换算为抽数）
**Y 轴**：成功率（0-1）
**元素**：
- 橙色方块：搜索上界阶段的采样点
- 蓝色圆点：二分搜索阶段的采样点
- 绿色菱形：最终验证点
- 红色虚线：成功率阈值
- 绿色竖虚线：最少所需资源
- 浅蓝色区域：最终搜索区间

**理论意义**：直观展示"成功率如何随资源量递增"，以及二分搜索的收敛过程。用户可以看到资源量从不足到充足的完整变化曲线。
