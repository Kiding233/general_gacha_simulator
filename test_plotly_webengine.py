#!/usr/bin/env python3
"""
Plotly + QWebEngineView 交互式图表测试（改进版 v2）
- 使用本地 plotly.js 文件引用（非内嵌，避免内存爆炸）
- 单 HTML 承载全部图表，JS 标签切换（瞬时）
- 紧凑控制栏
运行：python test_plotly_webengine.py
"""
import sys, os, json, gc, tempfile
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gacha_simulator'))
from visualization.font_config import configure_chinese_font
configure_chinese_font()

import plotly
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ⚠ 必须在创建 QApplication 前导入
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStatusBar, QSpinBox
)

# plotly.min.js 文件路径
PLOTLY_JS_PATH = os.path.join(os.path.dirname(plotly.__file__), 'package_data', 'plotly.min.js')


def generate_sample_data(n=1000, seed=42):
    rng = np.random.default_rng(seed)
    resources = rng.gamma(shape=5, scale=4000, size=n)
    pool_data = {}
    for i in range(5):
        pool_data[f"池子_{i+1}"] = rng.gamma(shape=4 + i * 0.5, scale=3000, size=n)
    return resources, pool_data


def build_html_file(resources, pool_data):
    """生成 HTML 文件（plotly.js 通过 file:// 引用），返回文件路径"""

    base_layout = dict(
        template='plotly_white', height=550,
        margin=dict(l=60, r=20, t=40, b=50), font=dict(size=12),
    )

    mean_val = float(np.mean(resources))
    sorted_data = np.sort(resources)
    cdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
    colors = ['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6']

    # 5 张图表
    fig1 = go.Figure()
    fig1.add_trace(go.Histogram(
        x=resources, nbinsx=40, marker_color='steelblue',
        marker_line_color='white', marker_line_width=0.5, opacity=0.85,
        hovertemplate='区间: %{x:.0f}<br>频次: %{y}<extra></extra>',
    ))
    fig1.add_vline(x=mean_val, line_dash='dash', line_color='red', line_width=2,
                   annotation_text=f'均值: {mean_val:.0f}')
    fig1.update_layout(**base_layout, title='直方图', xaxis_title='资源剩余', yaxis_title='频次')

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(
        x=sorted_data, y=cdf, mode='lines', line_color='steelblue', line_width=2,
        fill='tozeroy', fillcolor='rgba(70,130,180,0.15)',
        hovertemplate='资源: %{x:.0f}<br>累计概率: %{y:.2%}<extra></extra>',
    ))
    fig2.update_layout(**base_layout, title='CDF', xaxis_title='资源剩余',
                        yaxis_title='累计概率', yaxis_range=[0, 1.05])

    fig3 = go.Figure()
    for i, (name, data) in enumerate(pool_data.items()):
        fig3.add_trace(go.Violin(
            x=data, name=name, line_color=colors[i],
            fillcolor=colors[i], opacity=0.6, side='positive',
            orientation='h', width=2.5, meanline_visible=True,
            hovertemplate='%{x:.0f}<extra>%{data.name}</extra>',
        ))
    fig3.update_traces(points=False)
    fig3.update_layout(**base_layout, title='山脊线图', xaxis_title='资源剩余')

    fig4 = make_subplots(rows=1, cols=2, subplot_titles=('直方图', 'CDF'))
    fig4.add_trace(go.Histogram(
        x=resources, nbinsx=40, marker_color='steelblue',
        marker_line_color='white', marker_line_width=0.5, opacity=0.85,
        showlegend=False,
    ), row=1, col=1)
    fig4.add_vline(x=mean_val, line_dash='dash', line_color='red', line_width=2, row=1, col=1)
    fig4.add_trace(go.Scatter(
        x=sorted_data, y=cdf, mode='lines', line_color='#e74c3c',
        line_width=2, fill='tozeroy', fillcolor='rgba(231,76,60,0.1)',
        showlegend=False,
    ), row=1, col=2)
    fig4.update_layout(**base_layout, title='双图对比')
    for col, title in [(1, '资源剩余'), (2, '资源剩余')]:
        fig4.update_xaxes(title_text=title, row=1, col=col)
    fig4.update_yaxes(title_text='频次', row=1, col=1)
    fig4.update_yaxes(title_text='累计概率', row=1, col=2)

    fig5 = go.Figure()
    for (name, data), color in zip(pool_data.items(), colors):
        fig5.add_trace(go.Box(y=data, name=name, marker_color=color,
                               fillcolor=color, opacity=0.7, boxmean=True))
    fig5.update_layout(**base_layout, title='箱线图', yaxis_title='资源剩余')

    config = {
        'displayModeBar': True, 'displaylogo': False, 'scrollZoom': True,
        'toImageButtonOptions': {'format': 'png', 'filename': 'chart'},
        'locale': 'zh-CN',
    }
    charts_json = json.dumps([fig.to_dict() for fig in [fig1, fig2, fig3, fig4, fig5]])
    config_json = json.dumps(config)

    # plotly.js 用 file:// URL 引用（Windows 路径需处理）
    js_url = QUrl.fromLocalFile(PLOTLY_JS_PATH).toString()

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
.tab-bar {{
    display:flex; background:#f0f0f0; border-bottom:2px solid #ccc;
    padding:0 8px; gap:2px;
}}
.tab-btn {{
    padding:6px 14px; border:none; background:transparent;
    cursor:pointer; font-size:13px; color:#555;
    border-bottom:2px solid transparent; margin-bottom:-2px; outline:none;
}}
.tab-btn:hover {{ color:#333; background:#e8e8e8; }}
.tab-btn.active {{ color:#2c3e50; border-bottom-color:#3498db; font-weight:bold; }}
.chart-panel {{ display:none; padding:4px; height:calc(100vh - 70px); }}
.chart-panel.active {{ display:block; }}
.status {{ padding:2px 12px; font-size:11px; color:#999; }}
</style></head>
<body>
<div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab(0)">直方图</button>
    <button class="tab-btn" onclick="switchTab(1)">CDF</button>
    <button class="tab-btn" onclick="switchTab(2)">山脊线图</button>
    <button class="tab-btn" onclick="switchTab(3)">双图对比</button>
    <button class="tab-btn" onclick="switchTab(4)">箱线图</button>
    <span class="status" id="status">加载中...</span>
</div>
<div id="chart0" class="chart-panel active"></div>
<div id="chart1" class="chart-panel"></div>
<div id="chart2" class="chart-panel"></div>
<div id="chart3" class="chart-panel"></div>
<div id="chart4" class="chart-panel"></div>

<script src="{js_url}"></script>
<script>
const config = {config_json};
const chartsData = {charts_json};

chartsData.forEach(function(figData, i) {{
    Plotly.newPlot('chart' + i, figData.data, figData.layout, config);
}});
document.getElementById('status').textContent = '就绪';

function switchTab(idx) {{
    document.querySelectorAll('.tab-btn').forEach(function(b, i) {{
        b.classList.toggle('active', i === idx);
    }});
    document.querySelectorAll('.chart-panel').forEach(function(p, i) {{
        p.classList.toggle('active', i === idx);
    }});
}}
</script>
</body></html>'''

    # 写入临时文件
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8')
    tmp.write(html)
    tmp.close()
    return tmp.name


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Plotly + WebEngine — 单页多图表 (file://)")
        self.setGeometry(100, 100, 1400, 900)

        self._data = generate_sample_data()
        self.resources, self.pool_data = self._data
        self._html_path = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 控制栏：固定高度，不参与伸缩
        control_widget = QWidget()
        control_widget.setFixedHeight(32)
        control_widget.setStyleSheet("background: #f5f5f5; border-bottom: 1px solid #ddd;")
        control = QHBoxLayout(control_widget)
        control.setContentsMargins(8, 2, 8, 2)
        control.setSpacing(6)
        control.addWidget(QLabel("样本数:"))
        self.n_spin = QSpinBox()
        self.n_spin.setRange(100, 50000)
        self.n_spin.setValue(1000)
        self.n_spin.setSingleStep(500)
        self.n_spin.setFixedWidth(80)
        control.addWidget(self.n_spin)
        control.addWidget(QPushButton("重新生成", clicked=self._regenerate))
        control.addStretch()
        self.mem_label = QLabel("")
        self.mem_label.setStyleSheet("color: #888; padding-right: 4px;")
        control.addWidget(self.mem_label)
        layout.addWidget(control_widget)

        # 图表区域：占据全部剩余空间
        self.webview = QWebEngineView()
        layout.addWidget(self.webview, stretch=1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        QTimer.singleShot(200, self._render_all)

    def _render_all(self):
        import psutil
        gc.collect()
        mem_before = psutil.Process().memory_info().rss / 1024 / 1024

        # 清理旧文件
        if self._html_path and os.path.exists(self._html_path):
            try: os.unlink(self._html_path)
            except: pass

        self._html_path = build_html_file(self.resources, self.pool_data)

        gc.collect()
        mem_after = psutil.Process().memory_info().rss / 1024 / 1024
        html_kb = os.path.getsize(self._html_path) / 1024
        self.mem_label.setText(f"HTML: {html_kb:.0f}KB | 内存: {mem_after:.0f}MB (增量: {mem_after-mem_before:+.0f}MB)")

        self.webview.load(QUrl.fromLocalFile(self._html_path))
        self.status_bar.showMessage(
            "单WebView 5图表 | 标签切换瞬时 | 悬停=数据 | 框选=缩放 | 双击=重置"
        )

    def _regenerate(self):
        self._data = generate_sample_data(n=self.n_spin.value())
        self.resources, self.pool_data = self._data
        self._render_all()

    def closeEvent(self, event):
        if self._html_path and os.path.exists(self._html_path):
            try: os.unlink(self._html_path)
            except: pass
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName("Plotly WebEngine 测试")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
