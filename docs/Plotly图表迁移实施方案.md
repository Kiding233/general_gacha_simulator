# Plotly 图表迁移实施方案

> 日期：2026-05-25 | 状态：计划完成，未实施
> 依赖：无（独立计划）
> 被依赖：`docs/项目条目实施计划与调查报告.md` P6-P8（图表变更在 Plotly 体系下会更简洁）

---

## 一、目标与动机

用 **Plotly + QWebEngineView** 替换当前 **matplotlib Agg → 临时 PNG → QPixmap → QLabel** 图表管线，获得：

- **HiDPI 原生支持**（Chromium 渲染，无需手动适配 DPI）
- **交互式图表**（悬停数据提示、框选缩放、双击重置、工具栏保存）
- **矢量级清晰度**（不随窗口缩放而模糊）
- **消除临时文件管理**（不再需要 savefig/cleanup 逻辑）

代价：
- **额外依赖**：PyQt6-WebEngine（~132MB 安装包）/ plotly（~15MB）
- **内存增量**：每面板一个 QWebEngineView ≈ 50-80MB（Chromium 渲染进程），约 7 个图表面板 × 80MB ≈ 560MB 峰值 → 采用懒加载可控制在 200-300MB
- **绘图代码需全部用 plotly API 重写**（~1110 行 matplotlib 代码）

---

## 二、架构设计

### 2.1 总体架构

```
用户配置 → 模拟运行 → 聚合数据
                           ↓
              ┌────────────┼────────────┐
              ↓            ↓            ↓
         analysis     retreat      strategy
         _panel       _panel       _panel
              ↓            ↓            ↓
         构造 ChartSpec (纯数据，无绑图库依赖)
              ↓
         PlotlyRenderer (唯一依赖 plotly 的模块)
              ↓
         chart_webview.py (统一 WebView 容器)
              ↓
         QWebEngineView → 单 HTML 承载全部图表
                           (JS 标签/折叠切换，无需重载)
```

### 2.2 三层统一模块

| 模块 | 位置 | 职责 |
|------|------|------|
| `chart_spec.py` | `gacha_simulator/visualization/` | 定义 `ChartSpec` dataclass——面板与渲染层之间的中间表示，纯 numpy 数据，不依赖任何绑图库 |
| `plotly_charts.py` | `gacha_simulator/visualization/` | `PlotlyRenderer` 类，`ChartSpec → go.Figure` 的唯一转换点，全项目唯一依赖 plotly 的模块 |
| `chart_webview.py` | `gacha_simulator/gui/` | 封装 QWebEngineView 的创建、HTML 加载、临时文件管理、plotly.js 本地路径解析 |

**核心设计原则**：面板 Worker 只构造 `ChartSpec`（不 import plotly），`PlotlyRenderer` 负责转换为 `go.Figure`，`ChartWebView` 负责 HTML 渲染。面板和单元测试完全不依赖 plotly。

### 2.3 chart_webview.py 设计

```python
from .visualization.chart_spec import ChartSpec
from .visualization.plotly_charts import PlotlyRenderer

class ChartWebView(QWebEngineView):
    """封装 Plotly 图表的 WebEngineView，内嵌标签切换逻辑"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._renderer = PlotlyRenderer()
        self._html_path: str | None = None
        self._chart_keys: set[str] = set()  # 已加载的图表 key（支持增量更新）
        self.setMinimumHeight(300)
    
    def set_chart(self, spec: ChartSpec) -> None:
        """显示单张图表（ChartSpec → go.Figure → HTML）"""
        self.set_charts({spec.title: spec})
    
    def set_charts(self, charts: dict[str, ChartSpec]) -> None:
        """显示多张图表（dict key = 标签名），JS 标签切换。整批替换，用于首次加载。"""
        self._chart_keys = set(charts.keys())
        html = self._renderer.to_html(charts, self._get_plotly_js_url())
        self._write_and_load(html)
    
    def update_chart(self, key: str, spec: ChartSpec) -> None:
        """增量更新单张图表——不重建整个 HTML，通过 runJavaScript() 更新指定 div。
        
        用于增量分析场景：参数不变时跳过计算，参数变化的图表单独更新。
        """
        self._chart_keys.add(key)
        fig_json = self._renderer.to_json(spec)
        safe_json = fig_json.replace('\\', '\\\\').replace("'", "\\'")
        js_code = f"""
        (function() {{
            var plotData = JSON.parse('{safe_json}');
            var el = document.getElementById('chart-{key}');
            if (el) {{
                Plotly.react(el, plotData.data, plotData.layout);
            }} else {{
                console.warn('Chart div not found: chart-{key}');
            }}
        }})();
        """
        self.page().runJavaScript(js_code)
    
    def remove_chart(self, key: str) -> None:
        """移除单张图表（通过 JS 删除对应 DOM 元素）"""
        self._chart_keys.discard(key)
        self.page().runJavaScript(
            f"var el = document.getElementById('chart-{key}'); if (el) el.remove();"
        )
    
    def has_chart(self, key: str) -> bool:
        return key in self._chart_keys
    
    def _get_plotly_js_url(self) -> str:
        import plotly
        path = os.path.join(os.path.dirname(plotly.__file__), 'package_data', 'plotly.min.js')
        return QUrl.fromLocalFile(path).toString()
    
    def _write_and_load(self, html: str) -> None:
        """写入临时文件 → load(QUrl.fromLocalFile) → 记录路径供清理"""
        ...
    
    def closeEvent(self, event):
        """清理临时 HTML 文件"""
        ...
```

**关键设计决策：**

1. **单 HTML 多图表**：每个面板的所有图表共用一个 HTML 文件 + 一个 WebView。图表间切换用 JS `display: block/none`，瞬时无延迟。每个图表包裹在 `<div id="chart-{key}">` 中，以支持 `runJavaScript()` 增量更新单个图表。
2. **plotly.js 本地引用**：`<script src="file:///path/to/plotly.min.js">`，不内嵌（避免 4.6MB 字符串导致内存爆炸），不依赖 CDN。
3. **plotly.js 路径**：通过 `import plotly; os.path.join(os.path.dirname(plotly.__file__), 'package_data', 'plotly.min.js')` 获取，跟随 pip 安装位置。
4. **临时文件管理**：每次 `set_charts()` 写入新临时文件并加载，删除旧文件。面板销毁时清理。

### 2.4 chart_spec.py + plotly_charts.py 设计

#### 2.4.1 ChartSpec 中间表示（`visualization/chart_spec.py`）

```python
from dataclasses import dataclass, field
import numpy as np

@dataclass
class ChartSpec:
    """面板与渲染层之间的中间表示，纯数据，不依赖任何绑图库。"""
    chart_type: str          # 'histogram' | 'cdf' | 'ridge' | 'boxplot' | 'scatter' | 'bar' | 'heatmap' | 'waterfall_3d'
    data: dict               # 数据载荷，按图表类型不同：
                             #   histogram: {'samples': np.ndarray, 'mean_line': bool, 'quantile_lines': list[float] | None}
                             #   cdf:       {'samples': np.ndarray}
                             #   ridge:     {'series': dict[str, np.ndarray]}  {标签: 样本数组}
                             #   boxplot:   {'series': dict[str, np.ndarray]}
                             #   scatter:   {'x': np.ndarray, 'y': np.ndarray, 'mode': str}
                             #   bar:       {'labels': list[str], 'values': np.ndarray}
                             #   heatmap:   {'matrix': np.ndarray, 'row_labels': list[str], 'col_labels': list[str], 'colorscale': str}
                             #   waterfall_3d: {...}
    title: str
    xlabel: str = ""
    ylabel: str = ""
    annotations: list[dict] = field(default_factory=list)
    # annotations: [{'type': 'vline', 'x': float, 'color': str, 'dash': str, 'text': str}, ...]
    layout_hints: dict = field(default_factory=dict)
    # layout_hints: {'figsize': (w, h), 'nbins': int, 'color': str, ...}
```

#### 2.4.2 PlotlyRenderer（`visualization/plotly_charts.py`）

```python
import plotly.graph_objects as go

class PlotlyRenderer:
    """ChartSpec → go.Figure 的唯一转换点。全项目唯一 import plotly 的模块。"""
    
    def to_figure(self, spec: ChartSpec) -> go.Figure:
        """单个 ChartSpec → go.Figure"""
        method = getattr(self, f'_build_{spec.chart_type}', None)
        if method is None:
            raise ValueError(f"不支持的图表类型: {spec.chart_type}")
        return method(spec)
    
    def to_json(self, spec: ChartSpec) -> str:
        """单个 ChartSpec → JSON 字符串（用于 runJavaScript 增量更新）"""
        return self.to_figure(spec).to_json()
    
    def to_html(self, charts: dict[str, ChartSpec], plotly_js_url: str) -> str:
        """多个 ChartSpec → 完整 HTML 页面（含 JS 标签切换/折叠面板）"""
        figures = {k: self.to_figure(v).to_json() for k, v in charts.items()}
        return _HTML_TEMPLATE.format(
            plotly_js_url=plotly_js_url,
            charts_json=json.dumps(figures),
            config_json=json.dumps({k: v.title for k, v in charts.items()}),
        )
    
    def _build_histogram(self, s: ChartSpec) -> go.Figure: ...
    def _build_cdf(self, s: ChartSpec) -> go.Figure: ...
    def _build_ridge(self, s: ChartSpec) -> go.Figure: ...
    def _build_boxplot(self, s: ChartSpec) -> go.Figure: ...
    def _build_scatter(self, s: ChartSpec) -> go.Figure: ...
    def _build_bar(self, s: ChartSpec) -> go.Figure: ...
    def _build_heatmap(self, s: ChartSpec) -> go.Figure: ...
    def _build_waterfall_3d(self, s: ChartSpec) -> go.Figure: ...
```

**关键设计点：**
- 面板 Worker 只构造 `ChartSpec(dict)`，不 import plotly——单元测试只需验证 `ChartSpec` 的数据内容
- `PlotlyRenderer._build_*` 方法是 plotly 依赖的唯一集中点（~180 行），未来换绑图库只需替换这一个类
- `ChartSpec` 的数据字段按图表类型有明确 schema，非法组合在 `to_figure()` 时抛出明确错误
- `annotations` 统一处理参考线/标注，不再需要单独的 `add_vline`/`add_hline` 函数

### 2.5 面板集成模式

#### 模式 A：单图面板（5 个面板）

适用于 `resource_search_panel`、`strategy_panel`、`retreat_search_panel`、`worst_impact_panel`、`process_analysis_panel`。

```
原有: QLabel in QGroupBox → setPixmap(QPixmap(tmp_path))
改为: ChartWebView in QGroupBox → set_chart(fig)
```

变更量：~15 行/面板。

#### 模式 B：多图标签页面板（retreat_panel）

```
原有: QTabWidget → 每个 Tab 一个 QScrollArea → QLabel.setPixmap()
改为: 单个 ChartWebView → set_charts({"总览": fig_ridge, "池子1": fig1, ...})
      JS 标签切换在 HTML 内部完成
```

**关键变更**：删除 Python 侧的 `QTabWidget` + 多个 `QScrollArea` + 多个 `QLabel`，替换为单个 `ChartWebView`。HTML 内部的 JS 标签切换替代 Qt 标签页。

#### 模式 C：多图滚动面板（analysis_panel）

原有逻辑最复杂：用户勾选分析项 → Worker 生成相应图表 → 每个图表一个 `ResultUnit`（QFrame 含标题+QLabel）→ 垂直堆叠在 `QScrollArea` 中。

```
原有: QScrollArea → QVBoxLayout → [ResultUnit(title+QLabel), ResultUnit(title+QLabel), ...]
改为: QScrollArea → ChartWebView → set_charts({"直方图": fig1, "CDF": fig2, ...})
      HTML 内部用 collapsible sections + 垂直滚动
```

**关键变更**：
- 删除 `ResultUnit` 类（约 70 行）
- Worker 收集所有 fig → 传入 `set_charts()`
- 图表间的组织和导航由 HTML/CSS 处理（折叠面板/锚点导航）

### 2.6 图表类型汇总

| 图表类型 | ChartSpec chart_type | data schema | 使用面板 |
|---------|---------------------|-------------|---------|
| 直方图 | `histogram` | `samples` + `mean_line` + `quantile_lines` | analysis(5), vulnerability(2), process(1) |
| CDF | `cdf` | `samples` | analysis(3) |
| 山脊线图 | `ridge` | `series: dict[str, np.ndarray]` | analysis, vulnerability |
| 箱线图 | `boxplot` | `series: dict[str, np.ndarray]` | analysis |
| 条形图 | `bar` | `labels` + `values` | analysis(3), worst_impact(1) |
| 散点图 | `scatter` | `x` + `y` + `mode` | analysis, retreat_search |
| 折线图 | `scatter` (mode='lines') | `x` + `y` + `mode='lines'` | analysis(3), strategy, resource_search |
| 热力图 | `heatmap` | `matrix` + `row_labels` + `col_labels` | analysis(3) |
| 3D 瀑布图 | `waterfall_3d` | （待定义） | analysis |
| 参考线 | `annotations` 字段 | `{'type': 'vline'/'hline', 'x'/'y': float, ...}` | 全部 |

---

## 三、与现有 UI 布局的兼容方案

### 3.1 布局替换对照

| 面板 | 当前图表容器 | 替换为 | QTabWidget 变化 |
|------|------------|--------|----------------|
| analysis_panel | `ResultUnit` × N 在 `QScrollArea` 中 | `ChartWebView` 在 `QScrollArea` 中（单 HTML 内部滚动） | 无 |
| retreat_panel | `QTabWidget`（每池一个 tab）| `ChartWebView`（JS 标签） | **删除** `self.result_tabs` |
| resource_search_panel | `QLabel` in `QGroupBox` | `ChartWebView` in `QGroupBox` | 无 |
| strategy_panel | `QLabel` in `QGroupBox` | `ChartWebView` in `QGroupBox` | 无 |
| retreat_search_panel | `QLabel` in `QGroupBox` | `ChartWebView` in `QGroupBox` | 无 |
| worst_impact_panel | `QLabel` in `QGroupBox` | `ChartWebView` in `QGroupBox` | 无 |
| process_analysis_panel | `QLabel` in layout | `ChartWebView` in layout | 无 |

### 3.2 关键兼容性考虑

1. **QScrollArea 兼容**：对于 analysis_panel，保留外层 `QScrollArea`，内部的 `ResultUnit` 堆叠改为单 HTML 内的 JS 滚动。HTML `body { overflow-y: auto; }` 处理内部滚动，外层 `QScrollArea` 处理 WebView 尺寸超出窗口的情况。或者更好的做法：WebView 撑满窗口剩余高度，HTML 内部用 `overflow-y: scroll` + 折叠面板。

2. **QTabWidget 替换**：retreat_panel 当前每个池一个 Tab。改为单 HTML 内 JS 标签后，HTML 内的 CSS 标签栏替代 Qt 的 QTabBar。视觉效果可做到一致（自定义 CSS）。

3. **QGroupBox 保留**：单图面板的 `QGroupBox`（带标题边框）保留，其内部的 `QLabel` 替换为 `ChartWebView`。

4. **Worker 线程不变**：计算逻辑保持在 QThread Worker 中，Worker 的 `finished` 信号携带 `dict[str, ChartSpec]`（纯数据，无 plotly 依赖）。主线程接收后传给 `ChartWebView.set_charts()` 渲染。

5. **导出功能兼容**：Plotly 图表自带「下载为 PNG」工具栏按钮，替代原有的 `output_dir/` 文件导出。如需保留 `output_dir/` 导出，可在 Python 端调用 `fig.write_image(path)`（需 `pip install kaleido`，~50KB）。

### 3.3 表格+图表混合

analysis_panel 中部分 ResultUnit 是表格（`gdr_statistics`、`risk_worst_case`、`risk_best_case`、`conditional_dist`），不是图表。这些保持用 `QTableWidget` 不变，不归入 ChartWebView。

对于"表格+图表"配对出现的情况（如 `risk_worst_case` 表格 + `risk_worst_case_chart` 图表），表格保留在 QScrollArea 中，图表合并入 ChartWebView。两者在布局中可同时出现：上面是表格 QTableWidget，下面是 ChartWebView。

---

## 四、实施步骤

### 阶段 1：基础设施（TDD）

- [ ] **S1.1** 新建 `gacha_simulator/visualization/chart_spec.py`

  定义 `ChartSpec` dataclass（`chart_type`、`data`、`title`、`xlabel`、`ylabel`、`annotations`、`layout_hints`）。纯数据，零外部依赖。

- [ ] **S1.2** 新建 `tests/visualization/test_chart_spec.py`

  为 `ChartSpec` 写单元测试——验证各图表类型的 data schema 在构造时正确，不含无效字段。纯 numpy 断言，无 plotly 依赖。

- [ ] **S1.3** 新建 `gacha_simulator/visualization/plotly_charts.py`

  实现 `PlotlyRenderer` 类（`to_figure` / `to_json` / `to_html`），内部 `_build_histogram` / `_build_cdf` 等方法。全项目唯一 import plotly 的模块。

- [ ] **S1.4** 新建 `tests/visualization/test_plotly_charts.py`

  为 `PlotlyRenderer` 写单元测试（给定 ChartSpec → to_figure() → 验证 go.Figure 不为空、data 非空、layout 含 title 等）。

- [ ] **S1.5** 新建 `gacha_simulator/gui/chart_webview.py`

  实现 `ChartWebView` 类（`set_chart` / `set_charts` / `update_chart` / `remove_chart` / `has_chart` / HTML 模板 / 临时文件管理）。

- [ ] **S1.6** 提交

  ```bash
  git add gacha_simulator/visualization/chart_spec.py \
          tests/visualization/test_chart_spec.py \
          gacha_simulator/visualization/plotly_charts.py \
          tests/visualization/test_plotly_charts.py \
          gacha_simulator/gui/chart_webview.py
  git commit -m "feat: 新建 Plotly 图表基础设施——ChartSpec + PlotlyRenderer + ChartWebView"
  ```

### 阶段 2：迁移简单面板（单图模式，每个面板独立提交）

- [ ] **S2.1** 迁移 `worst_impact_panel.py`
  - 替换 `_plot_distribution()` 中的 matplotlib 代码为构造 `ChartSpec(chart_type="bar", ...)`
  - 替换 `QLabel(chart_label_dist)` 为 `ChartWebView`
  - 修复临时文件泄漏
  - 验证：GUI → 最差影响 → 执行分析 → 图表可交互

- [ ] **S2.2** 迁移 `process_analysis_panel.py`
  - 替换 `_plot_cond_dist()` 为构造 `ChartSpec(chart_type="histogram", ...)`
  - 替换 `QLabel(cond_chart_label)` 为 `ChartWebView`

- [ ] **S2.3** 迁移 `resource_search_panel.py`
  - 替换 `_draw_resource_chart()` 为构造 `ChartSpec(chart_type="scatter", mode="lines+markers", ...)`
  - 替换 `QLabel(chart_label)` 为 `ChartWebView`

- [ ] **S2.4** 迁移 `strategy_panel.py`
  - 替换 `_draw_strategy_chart()` 为构造 `ChartSpec(chart_type="scatter", mode="lines", ...)`
  - 替换 `QLabel(chart_label)` 为 `ChartWebView`

- [ ] **S2.5** 迁移 `retreat_search_panel.py`
  - 替换 `_plot_pareto_chart()` 为构造 `ChartSpec(chart_type="scatter", ...)`
  - 替换 `QLabel(chart_label)` 为 `ChartWebView`

### 阶段 3：迁移复杂面板

- [ ] **S3.1** 迁移 `core/vulnerability.py` 的绘图函数
  - `plot_vulnerability_ridge()` → 构造 `ChartSpec(chart_type="ridge", ...)`
  - `plot_vulnerability()` → 构造两个 `ChartSpec`（histogram + cdf）
  - 返回 `dict[str, ChartSpec]` 而非文件路径

- [ ] **S3.2** 迁移 `retreat_panel.py`
  - 替换 `QTabWidget(result_tabs)` + 每池 `QLabel` → 单个 `ChartWebView`
  - Worker 返回 `dict[str, ChartSpec]`（"总览": ridge, "池子1": ..., ...）
  - 删除 ~40 行的 QTabWidget 多标签页创建逻辑
  - 验证：GUI → 退路分析 → 执行 → 标签切换瞬时

- [ ] **S3.3** 迁移 `analysis_panel.py`
  - 删除 `ResultUnit` 类（约 70 行）
  - Worker 的 `ChartAnalysisWorker.run()` 将所有图表收集为 `dict[str, ChartSpec]`
  - 替换 `QScrollArea` 内堆叠的 `ResultUnit` → `ChartWebView` + 单 HTML 折叠面板
  - 表格型结果（`gdr_statistics` 等）保留为 `QTableWidget`，放在 ChartWebView 上方
  - 这是最复杂的迁移，预计变更 ~400 行
  - **⚠ 增量分析兼容**（见下方 3.3.1 节）

#### 3.3.1 增量分析兼容方案

**现有增量分析机制**（`analysis_panel.py:1883-1909`）：

```python
# _run_analysis() 中只计算条件已变化的图表
to_compute = [k for k in selected if self._needs_computation(k)]

# _needs_computation() 对比当前参数与上次计算时的参数快照
def _needs_computation(self, key):
    if key not in self._computed_conditions:
        return True
    return self._get_conditions_for_key(key) != self._computed_conditions[key]

# _on_analysis_done() 中复用已有的 ResultUnit
if key in self._result_units:
    unit = self._result_units[key]  # 复用
else:
    unit = ResultUnit(key, title)   # 新建
unit.set_chart(data)
```

**问题**：原方案 `ChartWebView.set_charts(dict)` 整批替换整个 HTML，无法支持增量更新——即使只有一个图表需要更新，也要重建全部 HTML，导致：
- 已有图表闪烁重绘
- 滚动位置丢失
- 与「参数不变则不重新生成」的设计理念冲突

**解决方案**：`ChartWebView.update_chart(key, spec)` 通过 `runJavaScript()` 更新单个图表，已在 2.3 节定义。

**analysis_panel 集成方式**：
```python
# _on_analysis_done(self, charts: dict[str, ChartSpec])
for key, spec in charts.items():
    if self._chart_view.has_chart(key):
        self._chart_view.update_chart(key, spec)   # 增量更新
    else:
        self._chart_view.set_charts({key: spec})   # 新增图表
    self._computed_conditions[key] = self._get_conditions_for_key(key)
```

**注意**：首次加载仍需 `set_charts()` 写入临时 HTML 文件并 `load()`，因为 plotly.js 库的初始化必须通过 `<script>` 标签加载。后续增量更新通过 `runJavaScript()` 完成，不再写文件。

**边界情况**：
- 切换数据集（`update_results()` 加载新一批模拟结果）→ 调用 `set_charts()` 全量替换，同时清空 `_computed_conditions`
- 用户修改全局参数（如 α 值）→ `_needs_computation()` 检测到条件变化，触发 Worker 重算，`update_chart()` 增量更新
- 取消勾选某个分析项 → `remove_chart()` 隐藏对应 div，保留 `_computed_conditions` 条目（重新勾选时直接从缓存恢复）

### 阶段 4：清理

- [ ] **S4.1** 删除不再使用的 matplotlib 后端设置代码（8 处 `matplotlib.use('Agg')`）
- [ ] **S4.2** 验证所有临时文件泄漏已消除
- [ ] **S4.3** 更新 `tests/visualization/test_plots.py`（从 matplotlib 测试改为 plotly 测试）

### 阶段 5：后续增强（P6-P8 依赖项）

- [ ] **S5.1** P6（抽数换算）：`plotly_charts` 的 cost_per_draw 参数 + 轴标签后缀 "(抽)"
- [ ] **S5.2** P7（不抽卡参考线）：`add_vline()` 传入 no_draw 资源值
- [ ] **S5.3** P8（多资源类型）：`plotly_charts` 的 resource_label 参数

---

## 五、影响范围汇总

| 阶段 | 涉及文件 | 新增 | 修改 | 删除 |
|------|---------|------|------|------|
| S1 基础设施 | 3 新 + 2 测试 | +480 | 0 | 0 |
| S2 简单面板 | 5 文件 | 0 | ~80/面板 | ~30/面板 |
| S3 复杂面板 | 3 文件 | 0 | ~400 | ~200 |
| S4 清理 | ~8 文件 | 0 | ~20 | ~30 |
| **合计** | ~17 文件 | +480 | ~900 | ~350 |

### 风险评估

| 风险 | 等级 | 缓解 |
|------|------|------|
| plotly.min.js 路径变更（pip 更新） | 低 | `import plotly` 动态获取路径，不硬编码 |
| 多 WebView 内存过高 | 中 | 懒加载 + 单面板单 WebView 策略，约 200-300MB |
| 离线环境无 plotly.js | 低 | 使用 pip 安装的 `plotly/package_data/plotly.min.js`，完全离线 |
| analysis_panel 迁移复杂度高 | 高 | 该面板 S3.3 单独成步，充分验证后再合并 |
| JS 标签切换在复杂布局下与 Qt 交互问题 | 中 | 测试脚本已验证基础可行，个别问题可在实施中调整 |

---

## 六、回滚策略

每个面板独立提交，单个面板迁移出问题可独立回滚（`git revert`），不影响其他面板。

出问题时：
1. 回滚该面板的提交
2. 对比迁移前后的 HTML 输出
3. 修复后重新提交该面板

---

## 七、实施后效果预估

| 指标 | 迁移前 | 迁移后 |
|------|--------|--------|
| HiDPI 支持 | 手动适配 DPI | Chromium 原生 |
| 图表交互 | 静态 PNG | 悬停/缩放/保存 |
| 临时文件管理 | 7 处，3 处泄漏 | 1 处统一管理，0 泄漏 |
| 绘图代码分布 | ~1110 行散落 10 文件 | ~120 行 chart_spec.py + ~180 行 PlotlyRenderer + ~700 行面板调用 |
| 新增图表 | 需修改多处 | 仅修改 ChartSpec 或 PlotlyRenderer |
| 内存（图表部分） | ~50MB（PNG 位图） | ~200-300MB（Chromium 进程） |
| 额外依赖 | 0 | PyQt6-WebEngine + plotly（~147MB 安装包） |
