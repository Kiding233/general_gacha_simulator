#!/usr/bin/env python3
"""
最小测试：matplotlib Qt 后端交互式图表表现验证
运行方式：python test_matplotlib_qt.py

验证要点：
1. 图表清晰度（矢量渲染 vs 位图 PNG）
2. 缩放/平移/保存交互
3. 多子图布局
4. 中文字体
5. 工具栏功能
"""

import sys
import os
import numpy as np

# 确保能找到项目的字体配置
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gacha_simulator'))
from visualization.font_config import configure_chinese_font
configure_chinese_font()

import matplotlib
matplotlib.use('QtAgg')  # 必须在 import pyplot 之前设置

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QComboBox, QGroupBox,
    QSplitter, QStatusBar
)
from PyQt6.QtCore import Qt


def generate_sample_data(n=1000, seed=42):
    """生成模拟抽卡数据"""
    rng = np.random.default_rng(seed)
    # 模拟每次模拟的最终资源剩余（均值 20000，标准差 5000，偏态分布）
    resources = rng.gamma(shape=5, scale=4000, size=n)
    # 模拟抽数（资源 / 160）
    draws = resources / 160
    # 模拟 5 个池子的资源分布
    pool_data = {}
    for i in range(5):
        pool_data[f"池子_{i+1}"] = rng.gamma(shape=4 + i * 0.5, scale=3000, size=n)
    return resources, draws, pool_data


class TestCanvas(FigureCanvas):
    """封装 matplotlib Figure 的 Qt Canvas"""

    def __init__(self, parent=None):
        # 跟随系统 DPI 缩放，高 DPI 屏幕下渲染清晰
        ratio = QApplication.primaryScreen().devicePixelRatio() if QApplication.instance() else 1.0
        dpi = int(100 * ratio)
        self.fig = Figure(figsize=(10, 6), dpi=dpi)
        self.fig.subplots_adjust(left=0.08, right=0.95, top=0.93, bottom=0.08)
        super().__init__(self.fig)
        self.setParent(parent)
        self.setMinimumHeight(400)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("交互式图表测试 — matplotlib QtAgg")
        self.setGeometry(100, 100, 1400, 900)

        self._data = generate_sample_data()
        self.resources, self.draws, self.pool_data = self._data

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # 控制栏
        control = QHBoxLayout()
        control.addWidget(QLabel("图表类型:"))
        self.chart_combo = QComboBox()
        self.chart_combo.addItems([
            "直方图（资源剩余分布）",
            "CDF（累计分布函数）",
            "山脊线图（多池分布）",
            "双图对比（直方图+CDF）",
            "箱线图（多池比较）",
        ])
        self.chart_combo.currentIndexChanged.connect(self._on_chart_changed)
        control.addWidget(self.chart_combo)

        self.redraw_btn = QPushButton("重新生成数据")
        self.redraw_btn.clicked.connect(self._regenerate)
        control.addWidget(self.redraw_btn)

        control.addStretch()
        info_label = QLabel("拖拽=平移 | 滚轮=缩放 | 右键=上下文菜单 | 工具栏=保存/重置")
        info_label.setStyleSheet("color: #888;")
        control.addWidget(info_label)
        layout.addLayout(control)

        # Canvas + 工具栏
        chart_container = QWidget()
        chart_layout = QVBoxLayout(chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)

        self.canvas = TestCanvas()
        self.toolbar = NavigationToolbar(self.canvas, self)
        chart_layout.addWidget(self.toolbar)
        chart_layout.addWidget(self.canvas)

        layout.addWidget(chart_container)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪 — 尝试缩放/平移图表，感受交互流畅度")

        # 首次绘制
        self._draw_histogram()

    def _regenerate(self):
        self._data = generate_sample_data(seed=np.random.randint(0, 99999))
        self.resources, self.draws, self.pool_data = self._data
        self._on_chart_changed()

    def _on_chart_changed(self):
        idx = self.chart_combo.currentIndex()
        if idx == 0:
            self._draw_histogram()
        elif idx == 1:
            self._draw_cdf()
        elif idx == 2:
            self._draw_ridge()
        elif idx == 3:
            self._draw_dual()
        elif idx == 4:
            self._draw_boxplot()

    def _clear_and_get_axes(self, rows=1, cols=1):
        self.canvas.fig.clear()
        if rows == 1 and cols == 1:
            return self.canvas.fig.add_subplot(111)
        axes = self.canvas.fig.subplots(rows, cols)
        return axes

    def _draw_histogram(self):
        """直方图 + 均值/分位数竖线"""
        ax = self._clear_and_get_axes()
        ax.hist(self.resources, bins=40, color='steelblue', edgecolor='white',
                alpha=0.85, label='模拟次数')
        mean_val = np.mean(self.resources)
        p05 = np.percentile(self.resources, 5)
        p95 = np.percentile(self.resources, 95)
        ax.axvline(mean_val, color='red', linestyle='--', linewidth=2,
                   label=f'均值: {mean_val:.0f}')
        ax.axvline(p05, color='orange', linestyle=':', linewidth=1.5,
                   label=f'5%分位: {p05:.0f}')
        ax.axvline(p95, color='orange', linestyle=':', linewidth=1.5,
                   label=f'95%分位: {p95:.0f}')
        ax.set_xlabel('资源剩余')
        ax.set_ylabel('频次')
        ax.set_title('资源剩余分布直方图')
        ax.legend(loc='upper right', fontsize=8)
        ax.grid(axis='y', alpha=0.3)
        self.canvas.draw()

    def _draw_cdf(self):
        """累计分布函数"""
        ax = self._clear_and_get_axes()
        sorted_data = np.sort(self.resources)
        cdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
        ax.plot(sorted_data, cdf, color='steelblue', linewidth=2)
        ax.fill_between(sorted_data, cdf, alpha=0.15, color='steelblue')
        ax.set_xlabel('资源剩余')
        ax.set_ylabel('累计概率')
        ax.set_title('资源剩余累计分布函数 (CDF)')
        ax.grid(alpha=0.3)
        ax.set_ylim(0, 1.05)
        # 添加 y=0.5 参考线
        ax.axhline(0.5, color='gray', linestyle='--', alpha=0.5, linewidth=0.8)
        self.canvas.draw()

    def _draw_ridge(self):
        """山脊线图 — 多池分布"""
        n_pools = len(self.pool_data)
        axes = self._clear_and_get_axes(n_pools, 1)
        pool_names = list(self.pool_data.keys())
        colors = ['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6']

        for i, (name, data) in enumerate(self.pool_data.items()):
            ax = axes[i] if n_pools > 1 else axes
            ax.hist(data, bins=30, color=colors[i], edgecolor='white',
                    alpha=0.8)
            mean_val = np.mean(data)
            ax.axvline(mean_val, color='#c0392b', linestyle='--', linewidth=1.5)
            ax.set_ylabel(name, fontsize=9, rotation=0, labelpad=40,
                          verticalalignment='center')
            ax.set_xlim(np.percentile(self.resources, 1),
                        np.percentile(self.resources, 99))
            ax.grid(axis='y', alpha=0.2)
            if i < n_pools - 1:
                ax.set_xticklabels([])
        axes[-1].set_xlabel('资源剩余')
        self.canvas.fig.suptitle('各池资源剩余分布（山脊线图）', fontsize=13, y=0.97)
        self.canvas.fig.subplots_adjust(hspace=0.15)
        self.canvas.draw()

    def _draw_dual(self):
        """双图：直方图 + CDF"""
        axes = self._clear_and_get_axes(1, 2)

        # 左：直方图
        ax = axes[0]
        ax.hist(self.resources, bins=40, color='steelblue', edgecolor='white',
                alpha=0.85)
        ax.axvline(np.mean(self.resources), color='red', linestyle='--', linewidth=2)
        ax.set_xlabel('资源剩余')
        ax.set_ylabel('频次')
        ax.set_title('直方图')
        ax.grid(axis='y', alpha=0.3)

        # 右：CDF
        ax = axes[1]
        sorted_data = np.sort(self.resources)
        cdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
        ax.plot(sorted_data, cdf, color='#e74c3c', linewidth=2)
        ax.fill_between(sorted_data, cdf, alpha=0.1, color='#e74c3c')
        ax.set_xlabel('资源剩余')
        ax.set_ylabel('累计概率')
        ax.set_title('CDF')
        ax.grid(alpha=0.3)
        ax.set_ylim(0, 1.05)

        self.canvas.fig.suptitle('双图对比', fontsize=13)
        self.canvas.draw()

    def _draw_boxplot(self):
        """多池箱线图"""
        ax = self._clear_and_get_axes()
        data_list = list(self.pool_data.values())
        labels = list(self.pool_data.keys())
        bp = ax.boxplot(data_list, labels=labels, patch_artist=True)
        colors = ['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6']
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        ax.set_xlabel('卡池')
        ax.set_ylabel('资源剩余')
        ax.set_title('各池资源剩余箱线图')
        ax.grid(axis='y', alpha=0.3)
        self.canvas.draw()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName("交互图表测试")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
