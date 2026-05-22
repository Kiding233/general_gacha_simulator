import sys
import os
import traceback
import tempfile
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QProgressBar, QGroupBox, QFormLayout, QDoubleSpinBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QComboBox, QRadioButton, QButtonGroup,
    QLineEdit, QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QColor

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from gacha_simulator.core.config_store import ConfigStore
from gacha_simulator.core.gdr import populate_gdr_combo, get_default_threshold


class RetreatSearchWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(object)
    error = pyqtSignal(object)

    def __init__(self, engine, target_specs, search_mode):
        super().__init__()
        self.engine = engine
        self.target_specs = target_specs
        self.search_mode = search_mode

    def stop(self):
        self.engine.stop()

    def run(self):
        try:
            self.progress.emit("正在构建截断配置...", 0)
            if self.search_mode == 'resource':
                result = self.engine.search_min_resource(self.target_specs)
            elif self.search_mode == 'target':
                result = self.engine.search_max_targets(self.target_specs)
            elif self.search_mode == 'pareto':
                result = self.engine.search_pareto(self.target_specs)
            else:
                raise ValueError(f"Unknown search mode: {self.search_mode}")
            self.finished.emit(result)
        except Exception as e:
            traceback.print_exc()
            self.error.emit(e)


class RetreatSearchPanel(QWidget):
    status_update = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._store = None
        self._vulnerability_result = None
        self._worker = None
        self._pity_init_values = {}
        self._miss_cost_weights = {}
        self._chart_path = None
        self._config_panel = None
        self._setup_ui()

    def set_store(self, store):
        self._store = store
        self._load_weights()

    def set_config_panel(self, config_panel):
        self._config_panel = config_panel

    def set_vulnerability_result(self, result):
        self._vulnerability_result = result
        self._refresh_pool_combo()

    def _load_weights(self):
        if self._store and self._store.target_cards:
            for tc in self._store.target_cards:
                if tc.card_id not in self._miss_cost_weights:
                    self._miss_cost_weights[tc.card_id] = 1.0
            for cid in list(self._miss_cost_weights.keys()):
                if cid not in {tc.card_id for tc in self._store.target_cards}:
                    del self._miss_cost_weights[cid]
        self._refresh_weight_table()

    def _refresh_weight_table(self):
        if not self._store or not self._store.target_cards:
            self.weight_table.setRowCount(0)
            return
        self.weight_table.blockSignals(True)
        self.weight_table.setRowCount(len(self._store.target_cards))
        for i, tc in enumerate(self._store.target_cards):
            card_id = tc.card_id
            weight = self._miss_cost_weights.get(card_id, 1.0)
            self.weight_table.setItem(i, 0, QTableWidgetItem(card_id))
            self.weight_table.item(i, 0).setFlags(
                self.weight_table.item(i, 0).flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.weight_table.item(i, 0).setBackground(QColor(240, 240, 240))
            weight_item = QTableWidgetItem()
            weight_item.setData(Qt.ItemDataRole.EditRole, weight)
            self.weight_table.setItem(i, 1, weight_item)
        self.weight_table.blockSignals(False)

    def _on_weight_changed(self, row, col):
        if col != 1 or row < 0:
            return
        card_item = self.weight_table.item(row, 0)
        if not card_item:
            return
        card_id = card_item.text()
        weight_item = self.weight_table.item(row, 1)
        try:
            self._miss_cost_weights[card_id] = float(weight_item.text())
        except (ValueError, AttributeError):
            self._miss_cost_weights[card_id] = 1.0

    def _refresh_pool_combo(self):
        self.pool_combo.clear()
        if not self._vulnerability_result:
            return
        for pr in self._vulnerability_result.pool_results:
            if pr.vulnerability_intervals:
                self.pool_combo.addItem(pr.pool_id, pr.pool_id)

    def _on_pool_changed(self, index):
        pool_id = self.pool_combo.currentData()
        if not pool_id or not self._vulnerability_result:
            return
        for pr in self._vulnerability_result.pool_results:
            if pr.pool_id == pool_id:
                self._update_resource_presets(pr)
                self._update_pity_table(pr)
                break

    def _update_resource_presets(self, pr):
        for btn in [self.res_vi_lower, self.res_vi_mean, self.res_vi_upper,
                    self.res_p25, self.res_p50, self.res_p75]:
            btn.setEnabled(False)
        self.res_vi_lower.setText("VI下限 (--)")
        self.res_vi_mean.setText("VI均值 (--)")
        self.res_vi_upper.setText("VI上限 (--)")
        self.res_p25.setText("25%分位 (--)")
        self.res_p50.setText("50%分位 (--)")
        self.res_p75.setText("75%分位 (--)")
        if pr.resource_values_all:
            import numpy as np
            p25 = np.percentile(pr.resource_values_all, 25)
            p50 = np.percentile(pr.resource_values_all, 50)
            p75 = np.percentile(pr.resource_values_all, 75)
            self.res_p25.setText(f"25%分位 ({p25:.0f})")
            self.res_p50.setText(f"50%分位 ({p50:.0f})")
            self.res_p75.setText(f"75%分位 ({p75:.0f})")
            self.res_p25.setEnabled(True)
            self.res_p50.setEnabled(True)
            self.res_p75.setEnabled(True)
        if pr.vulnerability_intervals:
            vi = pr.vulnerability_intervals[0]
            self.res_vi_lower.setText(f"VI下限 ({vi.lower:.0f})")
            self.res_vi_mean.setText(f"VI均值 ({vi.mean:.0f})")
            self.res_vi_upper.setText(f"VI上限 ({vi.upper:.0f})")
            self.res_vi_lower.setEnabled(True)
            self.res_vi_mean.setEnabled(True)
            self.res_vi_upper.setEnabled(True)
            self.res_vi_mean.setChecked(True)

    def _update_pity_table(self, pr):
        self.pity_table.setRowCount(0)
        self._pity_init_values = {}
        if not pr.pity_stats_at_pool_end:
            return
        for i, (cname, snap) in enumerate(pr.pity_stats_at_pool_end.items()):
            self.pity_table.insertRow(i)
            self.pity_table.setItem(i, 0, QTableWidgetItem(cname))
            self.pity_table.setItem(i, 1, QTableWidgetItem(f"{snap.mean:.1f}"))
            self.pity_table.setItem(i, 2, QTableWidgetItem(f"{snap.median:.1f}"))
            self.pity_table.setItem(i, 3, QTableWidgetItem(f"{snap.p25:.1f}"))
            self.pity_table.setItem(i, 4, QTableWidgetItem(f"{snap.p75:.1f}"))
            default_val = int(round(snap.mean))
            self._pity_init_values[cname] = default_val
            spin = QSpinBox()
            spin.setRange(0, 99999)
            spin.setValue(default_val)
            spin.valueChanged.connect(lambda val, name=cname: self._pity_init_values.__setitem__(name, val))
            self.pity_table.setCellWidget(i, 5, spin)

    def _get_selected_resource(self):
        if self.res_manual.isChecked():
            return float(self.res_manual_input.text() or '0')
        pool_id = self.pool_combo.currentData()
        if not pool_id or not self._vulnerability_result:
            return 0.0
        for pr in self._vulnerability_result.pool_results:
            if pr.pool_id == pool_id:
                if self.res_vi_lower.isChecked() or self.res_vi_mean.isChecked() or self.res_vi_upper.isChecked():
                    if pr.vulnerability_intervals:
                        vi = pr.vulnerability_intervals[0]
                        if self.res_vi_lower.isChecked():
                            return vi.lower
                        elif self.res_vi_mean.isChecked():
                            return vi.mean
                        elif self.res_vi_upper.isChecked():
                            return vi.upper
                elif self.res_p25.isChecked() or self.res_p50.isChecked() or self.res_p75.isChecked():
                    if pr.resource_values_all:
                        import numpy as np
                        if self.res_p25.isChecked():
                            return float(np.percentile(pr.resource_values_all, 25))
                        elif self.res_p50.isChecked():
                            return float(np.percentile(pr.resource_values_all, 50))
                        elif self.res_p75.isChecked():
                            return float(np.percentile(pr.resource_values_all, 75))
        return 0.0

    def _get_pity_init(self):
        return dict(self._pity_init_values)

    def _get_miss_cost_weights(self):
        return dict(self._miss_cost_weights)

    def _plot_pareto_chart(self, result):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from gacha_simulator.visualization.font_config import configure_chinese_font
        configure_chinese_font()

        if not result.points:
            return None

        extra_resources = [pt.extra_resource for pt in result.points]
        target_counts = [sum(pt.target_specs.values()) for pt in result.points]
        probs = [pt.success_probability for pt in result.points]

        # 根据点数决定图表尺寸，保持紧凑
        n = len(result.points)
        fig_w = max(5, min(n * 0.8 + 3, 10))
        fig_h = 4.5

        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        scatter = ax.scatter(extra_resources, target_counts, c=probs, cmap='RdYlGn',
                            s=80, edgecolors='black', linewidth=0.5, zorder=3)
        cbar = plt.colorbar(scatter, ax=ax, shrink=0.8)
        cbar.set_label('成功率')

        if len(extra_resources) > 1:
            sorted_pairs = sorted(zip(extra_resources, target_counts))
            sx = [p[0] for p in sorted_pairs]
            sy = [p[1] for p in sorted_pairs]
            ax.plot(sx, sy, '--', color='gray', alpha=0.5, linewidth=1, zorder=2)

        for i, pt in enumerate(result.points):
            specs_str = ', '.join(f"{k}" for k in pt.target_specs.keys())
            if specs_str:
                ax.annotate(specs_str, (pt.extra_resource, target_counts[i]),
                           textcoords="offset points", xytext=(3, 3),
                           fontsize=6, alpha=0.7)

        ax.set_xlabel('额外资源')
        ax.set_ylabel('目标卡数量')
        mode_labels = {'resource': '最少额外资源', 'target': '最多目标卡', 'pareto': 'Pareto前沿'}
        ax.set_title(f'退路方案搜索 — {mode_labels.get(result.search_mode, result.search_mode)}')
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        fig.savefig(tmp.name, dpi=200, bbox_inches='tight')
        plt.close(fig)
        return tmp.name

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        source_group = QGroupBox("起始状态（来自脆弱性分析）")
        source_form = QFormLayout(source_group)

        self.pool_combo = QComboBox()
        self.pool_combo.currentIndexChanged.connect(self._on_pool_changed)
        source_form.addRow("起始池:", self.pool_combo)

        res_group = QGroupBox("资源剩余值")
        res_grid = QGridLayout(res_group)
        res_grid.setSpacing(4)
        self.res_btn_group = QButtonGroup(self)
        self.res_vi_lower = QRadioButton("VI下限 (--)")
        self.res_vi_mean = QRadioButton("VI均值 (--)")
        self.res_vi_upper = QRadioButton("VI上限 (--)")
        self.res_p25 = QRadioButton("25%分位 (--)")
        self.res_p50 = QRadioButton("50%分位 (--)")
        self.res_p75 = QRadioButton("75%分位 (--)")
        self.res_manual = QRadioButton("手动输入:")
        self.res_manual_input = QLineEdit("0")
        for btn in [self.res_vi_lower, self.res_vi_mean, self.res_vi_upper,
                    self.res_p25, self.res_p50, self.res_p75, self.res_manual]:
            self.res_btn_group.addButton(btn)
        res_grid.addWidget(self.res_vi_lower, 0, 0)
        res_grid.addWidget(self.res_vi_mean, 0, 1)
        res_grid.addWidget(self.res_vi_upper, 0, 2)
        res_grid.addWidget(self.res_p25, 1, 0)
        res_grid.addWidget(self.res_p50, 1, 1)
        res_grid.addWidget(self.res_p75, 1, 2)
        manual_layout = QHBoxLayout()
        manual_layout.addWidget(self.res_manual)
        manual_layout.addWidget(self.res_manual_input)
        res_grid.addLayout(manual_layout, 2, 0, 1, 3)
        self.res_manual.setChecked(True)
        source_form.addRow(res_group)

        pity_group = QGroupBox("保底水位")
        pity_layout = QVBoxLayout(pity_group)
        self.pity_table = QTableWidget()
        self.pity_table.setColumnCount(6)
        self.pity_table.setHorizontalHeaderLabels(["计数器", "均值", "中位", "25%", "75%", "初始值"])
        self.pity_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pity_table.verticalHeader().setVisible(False)
        self.pity_table.setMaximumHeight(150)
        pity_layout.addWidget(self.pity_table)
        source_form.addRow(pity_group)

        left_layout.addWidget(source_group)

        weight_group = QGroupBox("目标卡权重（错失代价）")
        weight_layout = QVBoxLayout(weight_group)
        weight_info = QLabel("权重越小越先被移除（越不重要）")
        weight_info.setWordWrap(True)
        weight_layout.addWidget(weight_info)
        self.weight_table = QTableWidget()
        self.weight_table.setColumnCount(2)
        self.weight_table.setHorizontalHeaderLabels(["卡ID", "错失代价"])
        wh = self.weight_table.horizontalHeader()
        wh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        wh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.weight_table.setColumnWidth(1, 90)
        self.weight_table.verticalHeader().setVisible(False)
        self.weight_table.setMinimumHeight(80)
        self.weight_table.setMaximumHeight(200)
        self.weight_table.cellChanged.connect(self._on_weight_changed)
        weight_layout.addWidget(self.weight_table)
        left_layout.addWidget(weight_group)

        search_group = QGroupBox("搜索配置")
        search_form = QFormLayout(search_group)

        self.mode_resource = QRadioButton("最少额外资源")
        self.mode_target = QRadioButton("最多目标卡")
        self.mode_pareto = QRadioButton("Pareto前沿")
        self.mode_btn_group = QButtonGroup(self)
        for btn in [self.mode_resource, self.mode_target, self.mode_pareto]:
            self.mode_btn_group.addButton(btn)
        self.mode_pareto.setChecked(True)
        mode_layout = QVBoxLayout()
        mode_layout.addWidget(self.mode_resource)
        mode_layout.addWidget(self.mode_target)
        mode_layout.addWidget(self.mode_pareto)
        search_form.addRow("搜索模式:", mode_layout)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.01, 1.0)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setValue(0.95)
        self.threshold_spin.setDecimals(2)
        search_form.addRow("成功率阈值:", self.threshold_spin)

        self.sim_spin = QSpinBox()
        self.sim_spin.setRange(50, 10000)
        self.sim_spin.setSingleStep(100)
        self.sim_spin.setValue(1000)
        search_form.addRow("每步模拟次数:", self.sim_spin)

        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, os.cpu_count() or 16)
        self.worker_spin.setValue(max(1, (os.cpu_count() or 8) - 2))
        search_form.addRow("并行数:", self.worker_spin)

        self.gdr_combo = QComboBox()
        self.gdr_combo.setMaxVisibleItems(30)
        populate_gdr_combo(self.gdr_combo)
        self.gdr_combo.setCurrentIndex(1)
        search_form.addRow("GDR指标:", self.gdr_combo)

        self.gdr_threshold_spin = QDoubleSpinBox()
        self.gdr_threshold_spin.setRange(0.0, 9999999.0)
        self.gdr_threshold_spin.setSingleStep(0.1)
        self.gdr_threshold_spin.setValue(1.0)
        self.gdr_threshold_spin.setDecimals(2)
        search_form.addRow("GDR阈值:", self.gdr_threshold_spin)

        left_layout.addWidget(search_group)

        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("开始搜索")
        self.run_btn.clicked.connect(self._on_run)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.run_btn)
        btn_layout.addWidget(self.stop_btn)
        left_layout.addLayout(btn_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat('%p%')
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        left_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("请先运行脆弱性分析")
        left_layout.addWidget(self.status_label)
        left_layout.addStretch()

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        result_group = QGroupBox("搜索结果")
        result_layout = QVBoxLayout(result_group)
        self.result_label = QLabel("尚未运行搜索")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("padding: 8px; background: #f5f5f5; border-radius: 4px;")
        result_layout.addWidget(self.result_label)
        right_layout.addWidget(result_group)

        chart_group = QGroupBox("Pareto前沿图")
        chart_layout = QVBoxLayout(chart_group)
        self.chart_label = QLabel()
        self.chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_label.setMinimumHeight(200)
        chart_layout.addWidget(self.chart_label)
        right_layout.addWidget(chart_group)

        detail_group = QGroupBox("详细结果")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_table = QTableWidget()
        self.detail_table.setColumnCount(4)
        self.detail_table.setHorizontalHeaderLabels(["额外资源", "目标卡集合", "成功率", "总资源"])
        header = self.detail_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.detail_table.verticalHeader().setVisible(False)
        detail_layout.addWidget(self.detail_table)
        right_layout.addWidget(detail_group)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([400, 600])

    def _on_run(self):
        if not self._store:
            self.status_update.emit("请先加载配置")
            return
        if not self._vulnerability_result:
            self.status_label.setText("请先在退路分析中运行脆弱性分析")
            return

        pool_id = self.pool_combo.currentData()
        if not pool_id:
            self.status_label.setText("请选择起始池")
            return

        target_specs = {}
        for tc in self._store.target_cards:
            target_specs[tc.card_id] = getattr(tc, 'quantity', 1)
        if not target_specs:
            self.status_label.setText("请先在配置中添加目标卡")
            return

        base_resource = self._get_selected_resource()
        pity_init = self._get_pity_init()
        miss_cost_weights = self._get_miss_cost_weights()

        desire_weights = None
        card_value_weights = None
        if self._config_panel:
            desire_weights = self._config_panel.get_desire_weights()
            card_value_weights = self._config_panel.get_card_value_weights()

        if self.mode_resource.isChecked():
            mode = 'resource'
        elif self.mode_target.isChecked():
            mode = 'target'
        else:
            mode = 'pareto'

        gdr_key = self.gdr_combo.currentData() or 'all_targets'

        from gacha_simulator.core.retreat_search import RetreatSearchEngine

        strategy_key = self._store.strategy_name if self._store else 'smart'
        strategy_params = dict(self._store.strategy_params) if self._store else {}

        def _progress_callback(msg, pct):
            self._worker.progress.emit(msg, pct)

        engine = RetreatSearchEngine(
            config_store=self._store,
            from_pool_id=pool_id,
            base_resource=base_resource,
            pity_counter_init=pity_init,
            miss_cost_weights=miss_cost_weights,
            desire_weights=desire_weights,
            card_value_weights=card_value_weights,
            success_threshold=self.threshold_spin.value(),
            gdr_key=gdr_key,
            gdr_threshold=self.gdr_threshold_spin.value(),
            num_simulations=self.sim_spin.value(),
            max_workers=self.worker_spin.value(),
            strategy_name=strategy_key,
            strategy_params=strategy_params,
            progress_callback=_progress_callback,
        )

        self._worker = RetreatSearchWorker(engine, target_specs, mode)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self._worker.start()

    def _on_stop(self):
        if self._worker:
            self._worker.stop()

    def _on_progress(self, msg, pct):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)
        self.status_update.emit(msg)

    def _on_finished(self, result):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        self.status_label.setText("搜索完成")
        self.status_update.emit("退路方案搜索完成")

        if result is None:
            self.status_label.setText("搜索已停止")
            return

        from gacha_simulator.core.retreat_search import RetreatSearchResult
        assert isinstance(result, RetreatSearchResult)

        lines = [f"<b>搜索模式:</b> {result.search_mode}"]
        lines.append(f"<b>起始池:</b> {result.from_pool_id}")
        lines.append(f"<b>基准资源:</b> {result.base_resource:.0f}")
        lines.append(f"<b>保底初始:</b> {result.pity_init}")
        lines.append(f"<b>结果点数:</b> {len(result.points)}")

        if result.points:
            best = result.points[-1]
            lines.append(f"<b>最优:</b> 额外+{best.extra_resource:.0f}资源, "
                         f"目标{best.target_specs}, P={best.success_probability:.2%}")

        self.result_label.setText('<br>'.join(lines))

        chart_path = self._plot_pareto_chart(result)
        if chart_path:
            self._chart_path = chart_path
            pixmap = QPixmap(chart_path)
            if not pixmap.isNull():
                # 按比例缩放以适应标签宽度，保持宽高比
                max_w = self.chart_label.width() - 20
                max_h = 400
                scaled = pixmap.scaled(
                    max_w, max_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.chart_label.setPixmap(scaled)
            else:
                self.chart_label.setText("图表生成失败")
        else:
            self.chart_label.setText("无数据可绘制")

        self.detail_table.setRowCount(len(result.points))
        for i, pt in enumerate(result.points):
            self.detail_table.setItem(i, 0, QTableWidgetItem(f"{pt.extra_resource:.0f}"))
            specs_str = ', '.join(f"{k}\u00d7{v}" for k, v in pt.target_specs.items())
            self.detail_table.setItem(i, 1, QTableWidgetItem(specs_str or "(无)"))
            self.detail_table.setItem(i, 2, QTableWidgetItem(f"{pt.success_probability:.2%}"))
            total = result.base_resource + pt.extra_resource
            self.detail_table.setItem(i, 3, QTableWidgetItem(f"{total:.0f}"))

    def _on_error(self, err):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(f"错误: {err}")
        traceback.print_exc()
