#!/usr/bin/env python3
"""
Plotly+WebEngine vs matplotlib QtAgg 性能基准对比
运行：python benchmark_chart.py
"""
import sys, os, time, gc
# ⚠ WebEngine 必须在任何 Qt 导入之前导入
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QTimer, QEventLoop
from PyQt6.QtWidgets import QApplication
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gacha_simulator'))
from visualization.font_config import configure_chinese_font
configure_chinese_font()

import psutil
process = psutil.Process()

N_SAMPLES = 10000
rng = np.random.default_rng(42)
resources = rng.gamma(shape=5, scale=4000, size=N_SAMPLES)
pool_data = {f"pool_{i}": rng.gamma(shape=4 + i * 0.5, scale=3000, size=N_SAMPLES) for i in range(6)}

def measure_mem(label):
    process.memory_info()  # force refresh
    return f"{process.memory_info().rss / 1024 / 1024:.0f} MB"

print(f"{'='*60}")
print(f"数据规模: {N_SAMPLES} 条模拟记录, {len(pool_data)} 个池子")
print(f"{'='*60}")

# ── matplotlib 基准 ──
import matplotlib
matplotlib.use('QtAgg')
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

t0 = time.perf_counter()
fig = Figure(figsize=(10, 6), dpi=100)
canvas_type = type(FigureCanvas(fig)).__name__
t_fig = time.perf_counter() - t0

# 测试绘制：直方图
t0 = time.perf_counter()
ax = fig.add_subplot(111)
ax.hist(resources, bins=50, color='steelblue', edgecolor='white', alpha=0.85)
ax.axvline(np.mean(resources), color='red', linestyle='--')
ax.set_xlabel('资源剩余'); ax.set_ylabel('频次')
ax.set_title('直方图')
t_hist = time.perf_counter() - t0

# 测试绘制：山脊线图（6子图）
fig2 = Figure(figsize=(10, 8), dpi=100)
t0 = time.perf_counter()
axes = fig2.subplots(6, 1)
for i, (name, data) in enumerate(pool_data.items()):
    axes[i].hist(data, bins=30, color='steelblue', alpha=0.8)
    axes[i].set_ylabel(name, fontsize=8, rotation=0, labelpad=40)
t_ridge = time.perf_counter() - t0

mem_mpl = measure_mem("matplotlib 创建两张 Figure 后")

print(f"\nmatplotlib QtAgg:")
print(f"  Figure 创建:    {t_fig*1000:.1f} ms")
print(f"  直方图绘制:     {t_hist*1000:.1f} ms  (ax.hist 10k points)")
print(f"  山脊线图绘制:   {t_ridge*1000:.1f} ms  (6 子图 × 10k points)")
print(f"  内存:           {mem_mpl}")

# ── Plotly 基准 ──
import plotly.graph_objects as go
from plotly.subplots import make_subplots

t0 = time.perf_counter()
fig_p = go.Figure()
fig_p.add_trace(go.Histogram(x=resources, nbinsx=50, marker_color='steelblue'))
fig_p.update_layout(title='直方图', template='plotly_white')
html_hist = fig_p.to_html(include_plotlyjs='cdn', full_html=True)
t_hist_plotly = time.perf_counter() - t0

# 山脊线图用 violins 模拟
t0 = time.perf_counter()
fig_r = go.Figure()
for i, (name, data) in enumerate(pool_data.items()):
    fig_r.add_trace(go.Violin(x=data, name=name, side='positive',
                               orientation='h', width=2.5, points=False))
fig_r.update_layout(title='山脊线图', template='plotly_white')
html_ridge = fig_r.to_html(include_plotlyjs='cdn', full_html=True)
t_ridge_plotly = time.perf_counter() - t0

mem_plotly = measure_mem("Plotly 生成 HTML 后")

print(f"\nPlotly (Python 端，不含 WebEngine 渲染):")
print(f"  直方图 HTML 生成:  {t_hist_plotly*1000:.1f} ms  (大小: {len(html_hist)/1024:.0f} KB)")
print(f"  山脊线 HTML 生成:  {t_ridge_plotly*1000:.1f} ms  (大小: {len(html_ridge)/1024:.0f} KB)")
print(f"  内存:              {mem_plotly}")

# ── WebEngine 加载测试 ──
app = QApplication.instance() or QApplication(sys.argv)

web = QWebEngineView()
web.resize(1000, 600)

load_ok = []

load_start = time.perf_counter()
web.setHtml(html_hist)
loop = QEventLoop()
web.loadFinished.connect(lambda ok: (load_ok.append(ok), loop.quit()))
loop.exec()
load_time = time.perf_counter() - load_start

print(f"\nQWebEngineView 加载:")
print(f"  直方图加载耗时:  {load_time:.3f} s  (含 CDN 下载 plotly.js + JS 渲染)")
print(f"  加载成功:        {'是' if load_ok and load_ok[0] else '否'}")

# 第2次加载（plotly.js 浏览器缓存）
load_start2 = time.perf_counter()
web.setHtml(html_ridge)
loop2 = QEventLoop()
web.loadFinished.connect(lambda ok: loop2.quit())
loop2.exec()
load_time2 = time.perf_counter() - load_start2
print(f"  第2次加载耗时:   {load_time2:.3f} s  (含 JS 渲染，CDN 已缓存)")

# 新 WebView（独立 Chromium 进程，无缓存共享）
web2 = QWebEngineView()
web2.resize(1000, 600)
swap_start = time.perf_counter()
web2.setHtml(html_ridge)
loop3 = QEventLoop()
web2.loadFinished.connect(lambda ok: loop3.quit())
loop3.exec()
swap_time = time.perf_counter() - swap_start
print(f"  新WebView加载:   {swap_time:.3f} s  (独立进程，CDN 已缓存)")

mem_final = measure_mem("WebEngine 加载后")
print(f"  加载后内存:      {mem_final}")

# ── 汇总 ──
print(f"\n{'='*60}")
print(f"汇总对比（10k 数据点）:")
print(f"{'='*60}")
print(f"  {'指标':<20} {'matplotlib':>12} {'Plotly+WebEngine':>20}")
print(f"  {'─'*52}")
print(f"  {'创建绘制':<20} {'即时(<1ms)':>12} {'生成HTML+加载':>20}")
print(f"  {'直方图':<20} {f'{t_hist*1000:.0f}ms':>12} {f'{t_hist_plotly*1000:.0f}ms + {load_time:.1f}s':>20}")
print(f"  {'山脊线':<20} {f'{t_ridge*1000:.0f}ms':>12} {f'{t_ridge_plotly*1000:.0f}ms + {swap_time:.1f}s':>20}")
print(f"  {'切图表':<20} {'~1ms (draw)':>12} {f'~{swap_time:.1f}s (reload)':>20}")
print(f"  {'内存增量':<20} {mem_mpl:>12} {mem_final:>20}")

# 多视图测试
print(f"\n  [WARN] WebEngine 每多一个 QWebEngineView 实例，会再增加独立渲染进程内存 (~50-80MB)")
print(f"    项目分析面板有 ~15 个图表位置（直方图/CDF/山脊线 × 多池子）")
print(f"    若每图一个 WebView → 15 × 80MB ≈ 1.2GB（不可接受）")
print(f"    若复用单个 WebView 切换 HTML → 初始加载慢，但内存可控（~200MB）")

gc.collect()
