"""PlotlyRenderer —— ChartSpec → go.Figure 的唯一转换点。全项目唯一 import plotly 的模块。"""
from __future__ import annotations

import base64
import json
import textwrap

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .chart_spec import (
    BarData,
    BoxplotData,
    CDFData,
    ChartAnnotation,
    ChartSpec,
    HeatmapData,
    HistogramData,
    RidgeData,
    ScatterData,
    ScatterTrace,
    SubplotGridData,
    TableData,
    Waterfall3DData,
)

# ── HTML 模板 ───────────────────────────────────────────────────────────

_HTML_TEMPLATE = textwrap.dedent("""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<script src="{plotly_js_url}"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; background: #f8f9fa; }}
  .tab-bar {{
    display: flex; flex-wrap: wrap; gap: 2px; padding: 8px 10px 0 10px;
    background: #f8f9fa; border-bottom: 1px solid #dee2e6; position: sticky; top: 0; z-index: 10;
  }}
  .tab-btn {{
    padding: 8px 16px; border: none; border-radius: 6px 6px 0 0;
    background: #ced4da; color: #495057; cursor: pointer; font-size: 13px; transition: background .15s;
  }}
  .tab-btn:hover {{ background: #adb5bd; }}
  .tab-btn.active {{ background: #fff; color: #212529; font-weight: 600; }}
  .chart-panel {{ display: none; padding: 10px; }}
  .chart-panel.active {{ display: block; }}
  .chart-container {{ width: 100%; }}
  .collapsible {{
    margin: 10px 10px 0 10px; border: 1px solid #dee2e6; border-radius: 6px; overflow: hidden;
  }}
  .collapsible-header {{
    padding: 10px 16px; background: #e9ecef; cursor: pointer; font-size: 14px; font-weight: 600;
    user-select: none; display: flex; justify-content: space-between; align-items: center;
  }}
  .collapsible-header:hover {{ background: #dee2e6; }}
  .collapsible-body {{ display: none; padding: 10px; }}
  .collapsible.open .collapsible-body {{ display: block; }}
</style>
</head>
<body>
<div class="tab-bar" id="tab-bar"></div>
<div id="charts-root"></div>
<script>
  // 抑制 Plotly 的 Canvas2D getImageData 性能警告
  (function() {{
    var _getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, attrs) {{
      if (type === '2d') {{
        attrs = Object.assign({{}}, attrs, {{willReadFrequently: true}});
      }}
      return _getContext.call(this, type, attrs);
    }};
  }})();

  function renderChart(key, figureJson) {{
    var data = JSON.parse(figureJson);
    var el = document.getElementById('chart-' + key);
    if (el) {{
      Plotly.newPlot(el, data.data, data.layout, {{
        responsive: true,
        displaylogo: false,
        scrollZoom: false,
        modeBarButtonsToRemove: ['sendDataToCloud', 'lasso2d', 'select2d'],
        displayModeBar: true,
      }});
    }}
  }}

  function rebuildAll(config, charts, useTabs) {{
    var keys = Object.keys(charts);
    var tabBar = document.getElementById('tab-bar');
    var root = document.getElementById('charts-root');

    tabBar.innerHTML = '';
    root.innerHTML = '';

    if (useTabs && keys.length > 1) {{
      tabBar.style.display = 'flex';
      keys.forEach(function(key, i) {{
        var btn = document.createElement('button');
        btn.className = 'tab-btn' + (i === 0 ? ' active' : '');
        btn.textContent = config[key] || key;
        btn.onclick = function() {{
          document.querySelectorAll('.tab-btn').forEach(function(b) {{ b.classList.remove('active'); }});
          document.querySelectorAll('.chart-panel').forEach(function(p) {{ p.classList.remove('active'); }});
          btn.classList.add('active');
          document.getElementById('panel-' + key).classList.add('active');
        }};
        tabBar.appendChild(btn);

        var panel = document.createElement('div');
        panel.className = 'chart-panel' + (i === 0 ? ' active' : '');
        panel.id = 'panel-' + key;
        var div = document.createElement('div');
        div.className = 'chart-container';
        div.id = 'chart-' + key;
        panel.appendChild(div);
        root.appendChild(panel);
      }});
    }} else {{
      tabBar.style.display = 'none';
      keys.forEach(function(key) {{
        var section = document.createElement('div');
        section.className = 'collapsible open';
        var header = document.createElement('div');
        header.className = 'collapsible-header';
        header.textContent = config[key] || key;
        header.onclick = function() {{ section.classList.toggle('open'); }};
        var body = document.createElement('div');
        body.className = 'collapsible-body';
        var div = document.createElement('div');
        div.className = 'chart-container';
        div.id = 'chart-' + key;
        body.appendChild(div);
        section.appendChild(header);
        section.appendChild(body);
        root.appendChild(section);
      }});
    }}

    keys.forEach(function(key) {{ renderChart(key, charts[key]); }});
    window.scrollTo(0, 0);
  }}

  rebuildAll({config_json}, {charts_json}, {use_tabs});
</script>
</body>
</html>
""")


# ── PlotlyRenderer ──────────────────────────────────────────────────────

class PlotlyRenderer:
    """ChartSpec → go.Figure 的唯一转换点。"""

    # ── 公共接口 ──────────────────────────────────────────────────

    def to_figure(self, spec: ChartSpec) -> go.Figure:
        """单个 ChartSpec → go.Figure。"""
        method_name = f"_build_{spec.chart_type}"
        method = getattr(self, method_name, None)
        if method is None:
            raise ValueError(f"不支持的图表类型: {spec.chart_type}")
        fig = method(spec)
        self._apply_annotations(fig, spec)
        self._apply_layout(fig, spec)
        return fig

    def combine_vertical(
        self, top_spec: ChartSpec, bottom_spec: ChartSpec,
        top_height_ratio: float = 0.55,
    ) -> go.Figure:
        """将两个 ChartSpec 垂直堆叠为共享 x 轴的子图——上方直方图、下方曲线。"""
        top_fig = self.to_figure(top_spec)
        bottom_fig = self.to_figure(bottom_spec)

        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True,
            vertical_spacing=0.06,
            row_heights=[top_height_ratio, 1.0 - top_height_ratio],
        )

        for trace in top_fig.data:
            fig.add_trace(trace, row=1, col=1)
        for trace in bottom_fig.data:
            fig.add_trace(trace, row=2, col=1)

        # 将上方图的 vline/hline 复制到 row=1，下方图的复制到 row=2
        for shape in top_fig.layout.shapes or []:
            if getattr(shape, "type", "") == "line":
                fig.add_vline(
                    x=shape.x0, line_dash=getattr(shape.line, "dash", "solid"),
                    line_color=getattr(shape.line, "color", "#ff4444"),
                    line_width=getattr(shape.line, "width", 1),
                    row=1, col=1,
                )
        for shape in bottom_fig.layout.shapes or []:
            if getattr(shape, "type", "") == "line":
                fig.add_hline(
                    y=shape.y0, line_dash=getattr(shape.line, "dash", "solid"),
                    line_color=getattr(shape.line, "color", "#ff4444"),
                    line_width=getattr(shape.line, "width", 1),
                    row=2, col=1,
                )

        # 标题使用上方图表的标题
        fig.update_layout(
            title=top_spec.title,
            template="plotly_white",
            font_family="Microsoft YaHei, PingFang SC, sans-serif",
            margin=dict(l=50, r=20, t=50, b=20),
            hoverlabel=dict(font_size=12),
            dragmode="pan",
        )
        fig.update_yaxes(title_text=top_spec.ylabel, row=1, col=1, fixedrange=True)
        fig.update_yaxes(title_text=bottom_spec.ylabel, row=2, col=1, fixedrange=True)
        fig.update_xaxes(title_text=bottom_spec.xlabel, row=2, col=1)

        return fig

    def to_json(self, spec: ChartSpec) -> str:
        """单个 ChartSpec → JSON 字符串（用于 runJavaScript 增量更新）。"""
        return self.to_figure(spec).to_json()

    def to_html(
        self,
        charts: dict[str, ChartSpec],
        plotly_js_url: str,
        use_tabs: bool = True,
    ) -> str:
        """多个 ChartSpec → 完整 HTML 页面。

        Args:
            charts: {key: ChartSpec} 字典，key 用作标签名。
            plotly_js_url: plotly.min.js 的 file:// URL。
            use_tabs: 多图时使用标签切换模式，否则使用折叠面板。
        """
        figures_json = {}
        config_json = {}
        for key, spec in charts.items():
            figures_json[key] = self.to_figure(spec).to_json()
            config_json[key] = spec.title
        return _HTML_TEMPLATE.format(
            plotly_js_url=plotly_js_url,
            charts_json=json.dumps(figures_json),
            config_json=json.dumps(config_json, ensure_ascii=False),
            use_tabs="true" if use_tabs else "false",
        )

    # ── 各图表类型构建 ────────────────────────────────────────────

    def _build_histogram(self, s: ChartSpec) -> go.Figure:
        d: HistogramData = s.data
        nbins = s.layout_hints.get("nbins", None)
        color = s.layout_hints.get("color", "#1f77b4")
        bin_edges = s.layout_hints.get("bin_edges", None)
        fig = go.Figure()
        hist_kwargs = dict(
            x=d.samples, marker_color=color,
            hovertemplate="值: %{x:.2f}<br>频数: %{y}<extra></extra>",
        )
        if nbins is not None:
            hist_kwargs["nbinsx"] = nbins
        if bin_edges is not None:
            hist_kwargs["xbins"] = dict(
                start=bin_edges[0], end=bin_edges[-1] + (bin_edges[1] - bin_edges[0]) * 1.000001 if len(bin_edges) > 1 else bin_edges[-1],
                size=(bin_edges[1] - bin_edges[0]) if len(bin_edges) > 1 else None,
            )
        fig.add_trace(go.Histogram(**hist_kwargs))
        # 收集所有需要标注的竖线，按 x 坐标交错分配 y 偏移量以避免文字重叠
        line_anns = []
        if d.mean_line:
            mean_val = np.mean(d.samples)
            line_anns.append((mean_val, "#ff4444", "dash", f"均值 {mean_val:.2f}"))
        if d.quantile_lines:
            for q in d.quantile_lines:
                qv = np.quantile(d.samples, q)
                line_anns.append((qv, "#ff7f0e", "dot", f"P{int(q * 100)} {qv:.2f}"))
        line_anns.sort(key=lambda a: a[0])
        staggered = [1.0, 0.88, 0.76, 0.64, 0.52]
        for i, (xv, lc, ld, text) in enumerate(line_anns):
            fig.add_vline(x=xv, line_dash=ld, line_color=lc,
                          annotation_text=text,
                          annotation_position="top",
                          annotation=dict(font_size=10, y=staggered[i % len(staggered)]))
        # 为顶部标注留出空间
        all_y = [trace.y.max() for trace in fig.data if hasattr(trace, 'y') and trace.y is not None]
        if all_y:
            fig.update_yaxes(range=[0, max(all_y) * 1.25])
        fig.update_layout(bargap=0.05, hovermode="x")
        return fig

    def _build_cdf(self, s: ChartSpec) -> go.Figure:
        d: CDFData = s.data
        sorted_samples = np.sort(d.samples)
        n = len(sorted_samples)
        y = np.arange(1, n + 1) / n
        color = s.layout_hints.get("color", "#1f77b4")
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=sorted_samples, y=y, mode="lines", line_color=color,
            hovertemplate="x: %{x:.2f}<br>P: %{y:.3f}<extra></extra>",
        ))
        fig.update_layout(yaxis_range=[0, 1.02])
        return fig

    def _build_ridge(self, s: ChartSpec) -> go.Figure:
        d: RidgeData = s.data
        labels = list(d.series.keys())
        n = len(labels)
        nbins = s.layout_hints.get("nbins", 50)
        baselines = getattr(d, "baselines", {}) or {}

        # 渐变色：Viridis 色阶，从深紫到亮黄，池子间平滑过渡
        from plotly.colors import sample_colorscale
        if n > 1:
            colors = sample_colorscale("Viridis", [i / (n - 1) for i in range(n)])
        else:
            colors = [sample_colorscale("Viridis", [0.5])[0]]

        # 每个池子固定高度，总高度随池子数量线性增长，不再挤在一起
        row_height = s.layout_hints.get("row_height", 140)
        total_height = n * row_height + 80
        s.layout_hints["figsize"] = (None, total_height)

        # 计算共享分箱边界（优先使用 layout_hints 传入的预计算分箱）
        all_samples = np.concatenate(list(d.series.values()))
        precomputed_edges = s.layout_hints.get("bin_edges", None)
        if precomputed_edges is not None:
            bin_edges = np.asarray(precomputed_edges, dtype=np.float64)
        else:
            bin_edges = np.histogram_bin_edges(all_samples, bins=nbins)
        bin_size = bin_edges[1] - bin_edges[0]

        # 计算全局 y 轴上限，所有行统一缩放
        global_ymax = 0
        for label in labels:
            counts, _ = np.histogram(d.series[label], bins=bin_edges)
            global_ymax = max(global_ymax, counts.max())
        global_ymax = global_ymax * 1.18 if global_ymax > 0 else 1

        fig = make_subplots(
            rows=n, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.04,
        )

        for i, label in enumerate(labels):
            row = i + 1
            color = colors[i % len(colors)]
            mean_val = np.mean(d.series[label])

            fig.add_trace(
                go.Histogram(
                    x=d.series[label],
                    xbins=dict(start=bin_edges[0], end=bin_edges[-1] + bin_size + bin_size * 1e-6, size=bin_size),
                    marker_color=color,
                    name=label,
                    hovertemplate=f"{label}<br>值: %{{x:.2f}}<br>频数: %{{y}}<extra></extra>",
                ),
                row=row, col=1,
            )
            # 均值虚线（无文字标注，避免与柱顶重叠）
            fig.add_vline(
                x=mean_val, line_dash="dash", line_color="rgba(220,50,50,0.55)", line_width=1,
                row=row, col=1,
            )
            # 不抽卡基线
            if label in baselines:
                fig.add_vline(
                    x=baselines[label], line_dash="dot",
                    line_color="rgba(0,128,0,0.7)", line_width=1.4,
                    row=row, col=1,
                )
            # 统一 y 轴范围 + 左侧标签
            fig.update_yaxes(
                range=[0, global_ymax],
                title_text=label, title_font=dict(size=11, color="#333"),
                row=row, col=1, fixedrange=True,
            )

        s.layout_hints["margin"] = dict(l=120, r=20, t=50, b=20)
        fig.update_layout(
            showlegend=False, hovermode="x", bargap=0.02,
        )
        # x 轴标题设在最后一行（底部），不对 row=1 设置以避免标题出现在顶部
        fig.update_xaxes(title_text=s.xlabel, title_standoff=12, row=n, col=1)
        return fig

    def _build_boxplot(self, s: ChartSpec) -> go.Figure:
        d: BoxplotData = s.data
        color = s.layout_hints.get("color", "#1f77b4")
        fig = go.Figure()
        for label, samples in d.series.items():
            fig.add_trace(go.Box(
                x=samples, name=label, marker_color=color,
                orientation="h",
                hovertemplate=f"{label}<br>值: %{{x:.2f}}<extra></extra>",
            ))
        fig.update_layout(hovermode="y")
        fig.update_yaxes(autorange="reversed")
        return fig

    def _build_scatter(self, s: ChartSpec) -> go.Figure:
        d: ScatterData = s.data
        fig = go.Figure()

        if d.traces:
            for tr in d.traces:
                fig.add_trace(go.Scatter(
                    x=tr.x, y=tr.y, mode=tr.mode, name=tr.name,
                    marker=dict(
                        symbol=tr.marker_symbol, size=tr.marker_size,
                        color=tr.marker_color,
                    ),
                    line=dict(color=tr.line_color) if tr.line_color else None,
                    hovertemplate=f"{tr.name}<br>x: %{{x:.2f}}<br>y: %{{y:.2f}}<extra></extra>",
                ))
        elif d.color_values is not None:
            fig.add_trace(go.Scatter(
                x=d.x, y=d.y, mode=d.mode,
                marker=dict(
                    color=d.color_values, colorscale=d.colorscale,
                    colorbar=dict(title=d.colorbar_title) if d.colorbar_title else None,
                    showscale=True, size=10,
                    line=dict(width=0.5, color="black"),
                ),
                line=dict(color=d.line_color or "#333", width=d.line_width),
                hovertemplate="x: %{x:.2f}<br>y: %{y:.2f}<br>color: %{marker.color:.3f}<extra></extra>",
            ))
        else:
            color = s.layout_hints.get("color", "#1f77b4")
            fig.add_trace(go.Scatter(
                x=d.x, y=d.y, mode=d.mode, marker_color=color,
                hovertemplate="x: %{x:.2f}<br>y: %{y:.2f}<extra></extra>",
            ))
        return fig

    def _build_bar(self, s: ChartSpec) -> go.Figure:
        d: BarData = s.data
        color = s.layout_hints.get("color", "#1f77b4")
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=d.labels, y=d.values, marker_color=color,
            hovertemplate="%{x}: %{y:.2f}<extra></extra>",
        ))
        return fig

    def _build_heatmap(self, s: ChartSpec) -> go.Figure:
        d: HeatmapData = s.data
        z = d.matrix.astype(np.float64) if d.matrix.dtype != np.float64 else d.matrix
        fig = go.Figure()
        fig.add_trace(go.Heatmap(
            z=z, x=d.col_labels, y=d.row_labels,
            colorscale=d.colorscale,
            hovertemplate="行: %{y}<br>列: %{x}<br>值: %{z:.2f}<extra></extra>",
        ))
        fig.update_layout(xaxis_side="top")
        return fig

    def _build_waterfall_3d(self, s: ChartSpec) -> go.Figure:
        d: Waterfall3DData = s.data
        zlabel = s.layout_hints.get("zlabel", "Z")
        fig = go.Figure()
        fig.add_trace(go.Scatter3d(
            x=d.x, y=d.y, z=d.z, mode="lines+markers",
            marker=dict(size=4, color=d.z, colorscale="Viridis"),
            hovertemplate="池: %{x}<br>资源: %{y}<br>%{z}: %{z}<extra></extra>",
        ))
        fig.update_layout(
            scene=dict(xaxis_title=s.xlabel, yaxis_title=s.ylabel, zaxis_title=zlabel),
        )
        return fig

    def _build_subplot_grid(self, s: ChartSpec) -> go.Figure:
        d: SubplotGridData = s.data
        n = len(d.matrices)
        cols = d.cols
        rows = (n + cols - 1) // cols
        fig = make_subplots(
            rows=rows, cols=cols,
            horizontal_spacing=0.08,
            vertical_spacing=0.22,
        )
        for i, mat in enumerate(d.matrices):
            r = i // cols + 1
            c = i % cols + 1
            fig.add_trace(
                go.Heatmap(
                    z=mat.astype(np.float64),
                    x=d.col_labels,
                    y=d.row_labels,
                    colorscale=d.colorscale,
                    showscale=False,
                    hovertemplate="转移前: %{y}<br>转移后: %{x}<br>概率: %{z:.3f}<extra></extra>",
                ),
                row=r, col=c,
            )
            # 池名标注放在每个子图底部（domain 坐标，y=0 即子图底边）
            # Plotly 轴命名：首个子图为 x/y，后续为 x2/y2, x3/y3 ...
            if i < len(d.titles):
                axis_suffix = f"{i+1}" if i > 0 else ""
                fig.add_annotation(
                    text=d.titles[i],
                    xref=f"x{axis_suffix} domain", yref=f"y{axis_suffix} domain",
                    x=0.5, y=0, xanchor="center", yanchor="top",
                    showarrow=False, font=dict(size=10, color="#666"),
                    yshift=-8,
                )
        # 成功/失败标记放在顶部
        fig.update_xaxes(side="top")
        fig.update_layout(
            template="plotly_white",
            font_family="Microsoft YaHei, PingFang SC, sans-serif",
            margin=dict(l=20, r=20, t=60, b=40),
            hoverlabel=dict(font_size=12),
            dragmode="pan",
        )
        return fig

    def _build_table(self, s: ChartSpec) -> go.Figure:
        d: TableData = s.data
        header_fill = d.header_color
        n_rows = len(d.rows)
        n_cols = len(d.headers)
        # 根据行列数动态计算高度：表头 + 数据行 + 标题/边距
        cell_height = 28
        header_height = 38
        figure_height = header_height + n_rows * cell_height + 100
        # 根据列数和列宽估算所需宽度，避免水平滚动
        col_width_estimate = max(80, min(150, 900 // max(n_cols, 1)))
        figure_width = max(700, n_cols * col_width_estimate + 60)
        fig = go.Figure()
        fig.add_trace(go.Table(
            header=dict(
                values=d.headers,
                fill_color=header_fill,
                align="center",
                font=dict(size=12, color="#212529"),
                height=header_height,
            ),
            cells=dict(
                values=[[row[i] for row in d.rows] for i in range(n_cols)],
                fill_color=d.cell_colors or "white",
                align="center",
                font=dict(size=11),
                height=cell_height,
            ),
        ))
        fig.update_layout(
            title=s.title,
            template="plotly_white",
            font_family="Microsoft YaHei, PingFang SC, sans-serif",
            margin=dict(l=20, r=20, t=50, b=20),
            height=figure_height,
            width=figure_width,
        )
        return fig

    # ── 辅助方法 ──────────────────────────────────────────────────

    @staticmethod
    def _apply_annotations(fig: go.Figure, spec: ChartSpec) -> None:
        """将 ChartSpec 中的注解线和着色区间应用到图上。"""
        annotations = spec.annotations
        shaded_regions = spec.shaded_regions
        # 半透明着色区间
        for sr in shaded_regions:
            fig.add_vrect(
                x0=sr.lower, x1=sr.upper, fillcolor=sr.color,
                line_width=0, layer="below",
                annotation_text=sr.label or None,
                annotation_position="top left",
                annotation=dict(font_size=10, font_color="#666") if sr.label else None,
            )
        vlines = [a for a in annotations if a.type == "vline"]
        hlines = [a for a in annotations if a.type == "hline"]
        staggered = [1.0, 1.12, 0.88, 1.24, 0.76]
        vlines.sort(key=lambda a: a.value)
        for i, ann in enumerate(vlines):
            if ann.text:
                fig.add_vline(
                    x=ann.value, line_dash=ann.dash, line_color=ann.color,
                    annotation_text=ann.text,
                    annotation_position="top",
                    annotation=dict(font_size=10, y=staggered[i % len(staggered)]),
                )
            else:
                fig.add_vline(
                    x=ann.value, line_dash=ann.dash, line_color=ann.color,
                )
        hlines.sort(key=lambda a: a.value)
        for i, ann in enumerate(hlines):
            if ann.text:
                fig.add_hline(
                    y=ann.value, line_dash=ann.dash, line_color=ann.color,
                    annotation_text=ann.text,
                    annotation_position="right" if i % 2 == 0 else "left",
                    annotation=dict(font_size=10),
                )
            else:
                fig.add_hline(
                    y=ann.value, line_dash=ann.dash, line_color=ann.color,
                )

    @staticmethod
    def _apply_layout(fig: go.Figure, spec: ChartSpec) -> None:
        margin = spec.layout_hints.get("margin", dict(l=20, r=20, t=40, b=20))
        layout_updates = dict(
            title=spec.title,
            template="plotly_white",
            font_family="Microsoft YaHei, PingFang SC, sans-serif",
            margin=margin,
            hoverlabel=dict(font_size=12),
            dragmode="pan",
        )
        # ridge 图表自行管理 x/y 轴标题：_build_ridge 为每行设置独立 y 轴标签，
        # x 轴标题设在底部行，此处不覆盖
        if spec.chart_type != "ridge":
            layout_updates["xaxis_title"] = spec.xlabel
            layout_updates["yaxis_title"] = spec.ylabel
        fig.update_layout(**layout_updates)
        # 限制垂直拖动：y 轴固定范围，仅允许横向平移
        fig.update_yaxes(fixedrange=True)
        figsize = spec.layout_hints.get("figsize")
        if figsize:
            fig.update_layout(width=figsize[0], height=figsize[1])


# ── 热力图二进制编码工具 ───────────────────────────────────────────────

def encode_heatmap_binary(matrix: np.ndarray) -> str:
    """将大矩阵编码为 base64 二进制字符串，减少 HTML 嵌入体积。

    10,000×20 float64 矩阵：JSON ~3.2MB → base64 binary ~1.6MB。
    JS 侧解码: new Float64Array(Uint8Array.from(atob(data), ...).buffer)
    """
    buffer = matrix.astype(np.float64).tobytes()
    return base64.b64encode(buffer).decode("ascii")
