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
    background: #e9ecef; border-bottom: 2px solid #dee2e6; position: sticky; top: 0; z-index: 10;
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
(function() {{
  var config = {config_json};
  var charts = {charts_json};
  var keys = Object.keys(charts);
  var useTabs = {use_tabs};

  function renderChart(key, figureJson) {{
    var data = JSON.parse(figureJson);
    var el = document.getElementById('chart-' + key);
    if (el) {{
      Plotly.newPlot(el, data.data, data.layout, {{
        responsive: true,
        displaylogo: false,
        modeBarButtonsToRemove: ['sendDataToCloud', 'lasso2d', 'select2d'],
        displayModeBar: true,
      }});
    }}
  }}

  if (useTabs && keys.length > 1) {{
    // 标签切换模式
    var tabBar = document.getElementById('tab-bar');
    var root = document.getElementById('charts-root');
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
    // 折叠面板模式（单图或少量图无需标签）
    var tabBar = document.getElementById('tab-bar');
    tabBar.style.display = 'none';
    var root = document.getElementById('charts-root');
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

  // 渲染所有图表
  keys.forEach(function(key) {{ renderChart(key, charts[key]); }});
}})();
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
        self._apply_annotations(fig, spec.annotations)
        self._apply_layout(fig, spec)
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
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=d.samples, nbinsx=nbins, marker_color=color,
            hovertemplate="值: %{x:.2f}<br>频数: %{y}<extra></extra>",
        ))
        if d.mean_line:
            mean_val = np.mean(d.samples)
            fig.add_vline(
                x=mean_val, line_dash="dash", line_color="#ff4444",
                annotation_text=f"均值 {mean_val:.2f}",
            )
        if d.quantile_lines:
            for q in d.quantile_lines:
                qv = np.quantile(d.samples, q)
                fig.add_vline(
                    x=qv, line_dash="dot", line_color="#ff7f0e",
                    annotation_text=f"P{int(q * 100)} {qv:.2f}",
                )
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
        colors = s.layout_hints.get(
            "colors",
            ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
             "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"][:n],
        )

        fig = go.Figure()
        for i, label in enumerate(labels):
            samples = d.series[label]
            fig.add_trace(go.Violin(
                x=samples, name=label, side="positive", line_color=colors[i % len(colors)],
                spanmode="soft", orientation="h", width=2.5,
                hovertemplate=f"{label}<br>值: %{{x:.2f}}<extra></extra>",
            ))
        fig.update_traces(meanline_visible=True)
        fig.update_layout(violingap=0, violinmode="overlay", hovermode="y")
        # 反转 y 轴使第一个标签在最上面
        fig.update_yaxes(autorange="reversed")
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

    # ── 辅助方法 ──────────────────────────────────────────────────

    @staticmethod
    def _apply_annotations(fig: go.Figure, annotations: list[ChartAnnotation]) -> None:
        for ann in annotations:
            if ann.type == "vline":
                fig.add_vline(
                    x=ann.value, line_dash=ann.dash, line_color=ann.color,
                    annotation_text=ann.text or None,
                )
            elif ann.type == "hline":
                fig.add_hline(
                    y=ann.value, line_dash=ann.dash, line_color=ann.color,
                    annotation_text=ann.text or None,
                )

    @staticmethod
    def _apply_layout(fig: go.Figure, spec: ChartSpec) -> None:
        fig.update_layout(
            title=spec.title,
            xaxis_title=spec.xlabel,
            yaxis_title=spec.ylabel,
            template="plotly_white",
            font_family="Microsoft YaHei, PingFang SC, sans-serif",
            margin=dict(l=20, r=20, t=40, b=20),
            hoverlabel=dict(font_size=12),
        )
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
