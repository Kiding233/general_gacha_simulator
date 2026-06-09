#!/usr/bin/env python3
"""
退路分析面板 — 资源脆弱性分析
使用局部多项式回归（p=1）+ 等宽直方图叠加
直接基于批量模拟结果进行分析
"""

import sys
import os
import traceback
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QProgressBar, QGroupBox, QFormLayout, QDoubleSpinBox,
    QSpinBox, QComboBox, QSplitter,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from .chart_webview import ChartWebView

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from gacha_simulator.core.config_store import ConfigStore
from gacha_simulator.core.gdr import populate_gdr_combo, get_default_threshold


class RetreatWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(object)
    error = pyqtSignal(object)

    def __init__(
        self,
        simulation_results,
        target_specs,
        gdr_key,
        gdr_threshold,
        alpha,
        num_bins,
        num_curve_points,
        pool_names,
        desire_weights=None,
        miss_cost_weights=None,
        card_value_weights=None,
        no_draw_resource=None,
        no_draw_pool_resources=None,
        cost_per_draw=None,
        use_draw_units=False,
    ):
        super().__init__()
        self.simulation_results = simulation_results
        self.target_specs = target_specs
        self.gdr_key = gdr_key
        self.gdr_threshold = gdr_threshold
        self.alpha = alpha
        self.num_bins = num_bins
        self.num_curve_points = num_curve_points
        self.pool_names = pool_names
        self.desire_weights = desire_weights
        self.miss_cost_weights = miss_cost_weights
        self.card_value_weights = card_value_weights
        self.no_draw_resource = no_draw_resource
        self.no_draw_pool_resources = no_draw_pool_resources or {}
        self.cost_per_draw = cost_per_draw
        self.use_draw_units = use_draw_units

    def run(self):
        try:
            self.progress.emit("正在计算脆弱性分析...", 10)
            from gacha_simulator.core.vulnerability import compute_vulnerability_analysis

            analysis = compute_vulnerability_analysis(
                self.simulation_results,
                self.target_specs,
                gdr_key=self.gdr_key,
                gdr_threshold=self.gdr_threshold,
                alpha=self.alpha,
                num_bins=self.num_bins,
                num_curve_points=self.num_curve_points,
                desire_weights=self.desire_weights,
                miss_cost_weights=self.miss_cost_weights,
                card_value_weights=self.card_value_weights,
                cost_per_draw=self.cost_per_draw,
                use_draw_units=self.use_draw_units,
            )

            self.progress.emit("正在生成图表...", 60)
            from gacha_simulator.core.vulnerability import plot_vulnerability, plot_vulnerability_ridge
            import numpy as np

            ridge_fig = plot_vulnerability_ridge(analysis, pool_names=self.pool_names, no_draw_pool_resources=self.no_draw_pool_resources)

            global_edges = np.array(analysis.global_bin_edges) if analysis.global_bin_edges else None
            pool_specs = {}
            for pr in analysis.pool_results:
                pname = self.pool_names.get(pr.pool_id, pr.pool_id)
                spec = plot_vulnerability(pr, self.alpha, pool_name=pname, global_bin_edges=global_edges)
                pool_specs[pr.pool_id] = spec

            self.progress.emit("分析完成", 100)
            self.finished.emit({
                'analysis': analysis,
                'pool_specs': pool_specs,
                'ridge_fig': ridge_fig,
                'pool_names': self.pool_names,
            })
        except Exception as e:
            traceback.print_exc()
            self.error.emit(e)


class RetreatPanel(QWidget):
    status_update = pyqtSignal(str)
    vulnerability_finished = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._store = ConfigStore()
        self._worker = None
        self._results = None
        self._simulation_results = None
        self._target_specs = None
        self._config_panel = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)

        config_group = QGroupBox("脆弱性分析配置")
        config_form = QFormLayout()

        self.gdr_combo = QComboBox()
        self.gdr_combo.setMaxVisibleItems(30)
        populate_gdr_combo(self.gdr_combo)
        self.gdr_combo.currentIndexChanged.connect(self._on_gdr_changed)
        config_form.addRow("GDR指标:", self.gdr_combo)

        self.gdr_threshold_spin = QDoubleSpinBox()
        self.gdr_threshold_spin.setRange(-9999999.0, 9999999.0)
        self.gdr_threshold_spin.setSingleStep(0.05)
        self.gdr_threshold_spin.setValue(1.0)
        self.gdr_threshold_spin.setDecimals(2)
        config_form.addRow("成功阈值:", self.gdr_threshold_spin)

        self.alpha_spin = QDoubleSpinBox()
        self.alpha_spin.setRange(0.0, 1.0)
        self.alpha_spin.setSingleStep(0.05)
        self.alpha_spin.setValue(0.5)
        self.alpha_spin.setDecimals(2)
        config_form.addRow("脆弱比例阈值 α:", self.alpha_spin)

        self.num_bins_spin = QSpinBox()
        self.num_bins_spin.setRange(5, 100)
        self.num_bins_spin.setValue(20)
        config_form.addRow("直方图分箱数:", self.num_bins_spin)

        self.num_curve_spin = QSpinBox()
        self.num_curve_spin.setRange(50, 500)
        self.num_curve_spin.setValue(200)
        self.num_curve_spin.setSingleStep(50)
        config_form.addRow("回归曲线点数:", self.num_curve_spin)

        config_group.setLayout(config_form)
        left_layout.addWidget(config_group)

        self.run_btn = QPushButton("运行脆弱性分析")
        self.run_btn.clicked.connect(self._run_analysis)
        left_layout.addWidget(self.run_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat('%p%')
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        left_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("请先运行批量模拟")
        left_layout.addWidget(self.status_label)
        left_layout.addStretch()

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)

        self.chart_webview = ChartWebView()
        right_layout.addWidget(self.chart_webview)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([300, 700])

    def set_store(self, store):
        self._store = store

    def set_config_panel(self, config_panel):
        self._config_panel = config_panel

    def set_simulation_results(self, results, target_specs=None, no_draw_resource=None, no_draw_pool_resources=None):
        self._simulation_results = results
        self._target_specs = target_specs
        self._no_draw_resource = no_draw_resource
        self._no_draw_pool_resources = no_draw_pool_resources or {}
        if results:
            self.status_label.setText(f"已接收 {len(results)} 条模拟结果")

    def _on_gdr_changed(self, index):
        key = self.gdr_combo.currentData()
        default = get_default_threshold(key)
        self.gdr_threshold_spin.setValue(default)

    def _get_target_specs(self):
        if self._target_specs:
            return self._target_specs
        specs = {}
        for tc in getattr(self._store, 'target_cards', []):
            cid = tc.card_id
            qty = getattr(tc, 'quantity', 1)
            specs[cid] = qty
        return specs

    def _get_pool_names(self):
        pool_names = {}
        for pe in getattr(self._store, 'pools', []):
            if pe.enabled:
                pool_names[pe.pool_id] = getattr(pe, 'name', pe.pool_id)
        return pool_names

    def _extract_cost_per_draw(self):
        """从配置中提取单抽成本，默认 160。"""
        if self._store is None or not self._store.pools:
            return 160
        for pe in self._store.pools:
            cost_str = getattr(pe, 'cost', '')
            if not cost_str:
                continue
            try:
                parts = cost_str.split(':')
                if len(parts) == 2:
                    return int(float(parts[1]))
            except (ValueError, IndexError):
                continue
        return 160

    def _run_analysis(self):
        if not self._simulation_results:
            self.status_label.setText("请先运行批量模拟")
            return

        target_specs = self._get_target_specs()
        if not target_specs:
            self.status_label.setText("请先在配置中设置目标卡")
            return

        gdr_key = self.gdr_combo.currentData() or 'all_targets'
        gdr_threshold = self.gdr_threshold_spin.value()
        alpha = self.alpha_spin.value()
        num_bins = self.num_bins_spin.value()
        num_curve = self.num_curve_spin.value()
        pool_names = self._get_pool_names()
        cost_per_draw = self._extract_cost_per_draw()

        desire_weights = None
        miss_cost_weights = None
        card_value_weights = None
        if self._config_panel:
            desire_weights = self._config_panel.get_desire_weights()
            miss_cost_weights = self._config_panel.get_miss_cost_weights()
            card_value_weights = self._config_panel.get_card_value_weights()

        self._worker = RetreatWorker(
            simulation_results=self._simulation_results,
            target_specs=target_specs,
            gdr_key=gdr_key,
            gdr_threshold=gdr_threshold,
            alpha=alpha,
            num_bins=num_bins,
            num_curve_points=num_curve,
            pool_names=pool_names,
            desire_weights=desire_weights,
            miss_cost_weights=miss_cost_weights,
            card_value_weights=card_value_weights,
            no_draw_resource=getattr(self, '_no_draw_resource', None),
            no_draw_pool_resources=getattr(self, '_no_draw_pool_resources', {}),
            cost_per_draw=cost_per_draw,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self._worker.start()

    def _on_progress(self, msg, pct):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)
        self.status_update.emit(msg)

    def _on_finished(self, result):
        self.run_btn.setEnabled(True)

        self._results = result
        analysis = result["analysis"]
        pool_specs = result["pool_specs"]
        ridge_fig = result.get("ridge_fig")
        pool_names = result["pool_names"]

        summary = (
            f"总体失败率: {analysis.overall_failure_rate:.1%}  |  "
            f"模拟次数: {analysis.n_simulations}  |  "
            f"α = {analysis.alpha}"
        )
        self.status_label.setText(summary)

        charts: dict[str, object] = {}
        if ridge_fig is not None:
            charts["总览"] = ridge_fig

        for pr in analysis.pool_results:
            pname = pool_names.get(pr.pool_id, pr.pool_id)
            spec_data = pool_specs.get(pr.pool_id, {})

            combined_fig = spec_data.get("combined_figure") if isinstance(spec_data, dict) else None
            if combined_fig is not None:
                charts[pname] = combined_fig

        if charts:
            self.chart_webview.set_charts(charts)
        else:
            self.chart_webview.show_message("无数据可绘制")

        self.vulnerability_finished.emit(analysis)

    def _on_error(self, err):
        self.run_btn.setEnabled(True)
        self.status_label.setText(f"错误: {err}")
        traceback.print_exc()
