#!/usr/bin/env python3
"""
策略分析面板 - 目标卡权重配置与目标规划
"""

import sys
import os
import traceback
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QProgressBar, QGroupBox, QFormLayout, QDoubleSpinBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QFrame, QAbstractItemView, QComboBox, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

from .chart_webview import ChartWebView

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from gacha_simulator.core.config_store import ConfigStore
from gacha_simulator.core.gdr import populate_gdr_combo, get_default_threshold


class StrategyWorker(QThread):
    """策略分析运行线程"""
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(object, str)
    error = pyqtSignal(Exception)

    def __init__(
        self,
        method: str,
        all_target_ids: list,
        desire_weights: dict,
        miss_cost_weights: dict,
        card_value_weights: dict,
        success_threshold: float,
        target_qty: int,
        num_simulations: int,
        gdr_key: str,
        gdr_threshold: float,
        config_store: ConfigStore,
        max_workers: int = 4,
    ):
        super().__init__()
        self.method = method
        self.all_target_ids = all_target_ids
        self.desire_weights = desire_weights
        self.miss_cost_weights = miss_cost_weights
        self.card_value_weights = card_value_weights
        self.success_threshold = success_threshold
        self.target_qty = target_qty
        self.num_simulations = num_simulations
        self.gdr_key = gdr_key
        self.gdr_threshold = gdr_threshold
        self.config_store = config_store
        self.max_workers = max_workers
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def _build_simulation_env(self):
        from .batch_simulator import SimulationEnvBuilder
        self._sim_env = SimulationEnvBuilder.from_config_store(self.config_store)

    def _forward_method(self):
        from gacha_simulator.core.forward_backward import ForwardStep, ForwardResult

        sorted_ids = sorted(self.all_target_ids, key=lambda cid: self.desire_weights.get(cid, 1.0), reverse=True)
        current_set = set()
        current_specs = {}
        steps = []
        last_valid_set = set()
        last_valid_specs = {}
        last_valid_prob = 1.0

        total_steps = len(sorted_ids)
        for i, card_id in enumerate(sorted_ids):
            if self._should_stop:
                return None
            self.progress.emit(f"前进法: 尝试添加 {card_id}", int((i / max(total_steps, 1)) * 90) + 5)

            current_set.add(card_id)
            current_specs[card_id] = self.target_qty

            from .batch_simulator import run_batch_parallel
            _skey = self.config_store.strategy_name
            _sparams = self.config_store.strategy_params
            histories = run_batch_parallel(
                env=self._sim_env,
                target_specs=current_specs,
                initial_resources=self._sim_env.initial_resources,
                num_simulations=self.num_simulations,
                max_workers=self.max_workers,
                seed=0,
                strategy_name=_skey,
                strategy_params=_sparams,
            )
            from gacha_simulator.core.gdr import compute_success_probability
            prob = compute_success_probability(histories, current_specs, self.gdr_key, self.gdr_threshold,
                                               self.desire_weights, self.miss_cost_weights, self.card_value_weights)

            steps.append(ForwardStep(
                added_card_id=card_id,
                target_set=set(current_set),
                success_probability=prob,
                target_specs=dict(current_specs),
            ))

            if prob >= self.success_threshold:
                last_valid_set = set(current_set)
                last_valid_specs = dict(current_specs)
                last_valid_prob = prob
            else:
                self.progress.emit(f"前进法完成: 成功率 {last_valid_prob:.2%}", 95)
                break

        if not last_valid_set and steps:
            last_valid_set = set(steps[0].target_set)
            last_valid_specs = dict(steps[0].target_specs)
            last_valid_prob = steps[0].success_probability

        return ForwardResult(
            steps=steps,
            final_target_set=last_valid_set,
            final_success_probability=last_valid_prob,
            final_target_specs=last_valid_specs,
        )

    def _backward_method(self):
        from gacha_simulator.core.forward_backward import BackwardStep, BackwardResult

        sorted_ids = sorted(self.all_target_ids, key=lambda cid: self.miss_cost_weights.get(cid, 1.0))
        current_set = set(self.all_target_ids)
        current_specs = {cid: self.target_qty for cid in self.all_target_ids}
        steps = []

        total_steps = len(sorted_ids)

        self.progress.emit("后退法: 初始完整集合模拟", 5)

        from .batch_simulator import run_batch_parallel
        _skey = self.config_store.strategy_name
        _sparams = self.config_store.strategy_params
        initial_histories = run_batch_parallel(
            env=self._sim_env,
            target_specs=dict(current_specs),
            initial_resources=self._sim_env.initial_resources,
            num_simulations=self.num_simulations,
            max_workers=self.max_workers,
            seed=0,
            strategy_name=_skey,
            strategy_params=_sparams,
        )
        from gacha_simulator.core.gdr import compute_success_probability
        initial_prob = compute_success_probability(initial_histories, current_specs, self.gdr_key, self.gdr_threshold,
                                                   self.desire_weights, self.miss_cost_weights, self.card_value_weights)

        if initial_prob > self.success_threshold:
            self.progress.emit(f"后退法完成: 初始成功率已超阈值 {initial_prob:.2%}", 95)
            steps.append(BackwardStep(
                removed_card_id='',
                target_set=set(current_set),
                success_probability=initial_prob,
                target_specs=dict(current_specs),
            ))
            return BackwardResult(
                steps=steps,
                final_target_set=current_set,
                final_success_probability=initial_prob,
                final_target_specs=dict(current_specs),
            )

        last_valid_set = None
        last_valid_specs = None
        last_valid_prob = initial_prob

        for i, card_id in enumerate(sorted_ids):
            if self._should_stop:
                return None
            if card_id not in current_set:
                continue

            self.progress.emit(f"后退法: 尝试移除 {card_id}", int(((i + 1) / max(total_steps, 1)) * 90) + 5)

            temp_set = set(current_set)
            temp_specs = dict(current_specs)
            temp_set.discard(card_id)
            del temp_specs[card_id]

            from .batch_simulator import run_batch_parallel
            _skey = self.config_store.strategy_name
            _sparams = self.config_store.strategy_params
            histories = run_batch_parallel(
                env=self._sim_env,
                target_specs=temp_specs,
                initial_resources=self._sim_env.initial_resources,
                num_simulations=self.num_simulations,
                max_workers=self.max_workers,
                seed=0,
                strategy_name=_skey,
                strategy_params=_sparams,
            )
            from gacha_simulator.core.gdr import compute_success_probability
            temp_prob = compute_success_probability(histories, temp_specs, self.gdr_key, self.gdr_threshold,
                                                   self.desire_weights, self.miss_cost_weights, self.card_value_weights)

            steps.append(BackwardStep(
                removed_card_id=card_id,
                target_set=set(temp_set),
                success_probability=temp_prob,
                target_specs=dict(temp_specs),
            ))

            if temp_prob > self.success_threshold:
                last_valid_set = set(temp_set)
                last_valid_specs = dict(temp_specs)
                last_valid_prob = temp_prob
                self.progress.emit(f"后退法完成: 成功率 {last_valid_prob:.2%}", 95)
                break
            else:
                current_set = temp_set
                current_specs = temp_specs

        if last_valid_set is not None:
            return BackwardResult(
                steps=steps,
                final_target_set=last_valid_set,
                final_success_probability=last_valid_prob,
                final_target_specs=last_valid_specs,
            )

        return BackwardResult(
            steps=steps,
            final_target_set=current_set,
            final_success_probability=last_valid_prob,
            final_target_specs=dict(current_specs),
        )

    def run(self):
        try:
            self.progress.emit("正在构建模拟环境...", 0)
            self._build_simulation_env()

            self.progress.emit("开始分析...", 5)

            if self.method == 'forward':
                result = self._forward_method()
            else:
                result = self._backward_method()

            if result is None:
                self.progress.emit("已停止", 0)
                return

            self.progress.emit("分析完成!", 100)
            self.finished.emit(result, self.method)
        except Exception as e:
            import traceback as tb
            tb.print_exc()
            detailed = f"{type(e).__name__}: {e}\n\n{tb.format_exc()}"
            class DetailedError(Exception):
                def __init__(self, msg):
                    self.msg = msg
                def __str__(self):
                    return self.msg
            self.error.emit(DetailedError(detailed))


class StrategyPanel(QWidget):
    """策略分析面板"""
    status_update = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._store = None
        self._worker = None
        self._weights = {}
        self._config_panel = None
        self._setup_ui()

    def set_store(self, store: ConfigStore):
        self._store = store
        self._load_weights()

    def set_config_panel(self, config_panel):
        self._config_panel = config_panel
        config_panel.config_changed.connect(self._update_strategy_display)
        self._update_strategy_display()

    def _update_strategy_display(self):
        if self._config_panel:
            self.strategy_label.setText(self._config_panel.strategy_type.currentText())

    def _load_weights(self):
        if self._store and self._store.target_cards:
            for tc in self._store.target_cards:
                if tc.card_id not in self._weights:
                    self._weights[tc.card_id] = {
                        'desire_weight': 1.0,
                        'miss_cost_weight': 1.0,
                    }
            for cid in list(self._weights.keys()):
                if cid not in {tc.card_id for tc in self._store.target_cards}:
                    del self._weights[cid]
        self._refresh_weight_table()

    def _refresh_weight_table(self):
        if not self._store or not self._store.target_cards:
            self.weight_table.setRowCount(0)
            return

        self.weight_table.blockSignals(True)
        self.weight_table.setRowCount(len(self._store.target_cards))
        for i, tc in enumerate(self._store.target_cards):
            card_id = tc.card_id
            weights = self._weights.get(card_id, {'desire_weight': 1.0, 'miss_cost_weight': 1.0})

            self.weight_table.setItem(i, 0, QTableWidgetItem(card_id))
            self.weight_table.item(i, 0).setFlags(
                self.weight_table.item(i, 0).flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.weight_table.item(i, 0).setBackground(QColor(240, 240, 240))

            desire_item = QTableWidgetItem()
            desire_item.setData(Qt.ItemDataRole.EditRole, weights['desire_weight'])
            self.weight_table.setItem(i, 1, desire_item)

            miss_cost_item = QTableWidgetItem()
            miss_cost_item.setData(Qt.ItemDataRole.EditRole, weights['miss_cost_weight'])
            self.weight_table.setItem(i, 2, miss_cost_item)

        self.weight_table.blockSignals(False)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        weight_group = QGroupBox("目标卡权重配置")
        weight_layout = QVBoxLayout(weight_group)

        weight_info = QLabel("设置各目标卡的权重，用于前进法/后退法分析")
        weight_info.setWordWrap(True)
        weight_layout.addWidget(weight_info)

        self.weight_table = QTableWidget()
        self.weight_table.setColumnCount(3)
        self.weight_table.setHorizontalHeaderLabels(["卡ID", "抽取意愿", "错失代价"])
        header = self.weight_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.weight_table.setColumnWidth(1, 90)
        self.weight_table.setColumnWidth(2, 90)
        self.weight_table.verticalHeader().setVisible(False)
        self.weight_table.setMinimumHeight(200)
        self.weight_table.cellChanged.connect(self._on_weight_changed)
        weight_layout.addWidget(self.weight_table)

        left_layout.addWidget(weight_group)

        params_group = QGroupBox("分析参数")
        params_layout = QFormLayout(params_group)

        self.strategy_label = QLabel("--")
        self.strategy_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        params_layout.addRow("当前策略:", self.strategy_label)

        self.method_combo = QComboBox()
        self.method_combo.addItems(["前进法", "后退法"])
        params_layout.addRow("分析方法:", self.method_combo)

        self.gdr_combo = QComboBox()
        self.gdr_combo.setMaxVisibleItems(30)
        populate_gdr_combo(self.gdr_combo)
        self.gdr_combo.setCurrentIndex(0)
        self.gdr_combo.currentIndexChanged.connect(self._on_gdr_changed)
        params_layout.addRow("成功判定GDR:", self.gdr_combo)

        self.gdr_threshold_spin = QDoubleSpinBox()
        self.gdr_threshold_spin.setRange(0.0, 9999999.0)
        self.gdr_threshold_spin.setSingleStep(0.1)
        self.gdr_threshold_spin.setValue(1.0)
        self.gdr_threshold_spin.setDecimals(2)
        self.gdr_threshold_spin.setToolTip("GDR指标需达到此值才算成功")
        params_layout.addRow("GDR达标阈值:", self.gdr_threshold_spin)

        self.success_threshold_spin = QDoubleSpinBox()
        self.success_threshold_spin.setRange(0.0, 1.0)
        self.success_threshold_spin.setSingleStep(0.01)
        self.success_threshold_spin.setValue(0.95)
        self.success_threshold_spin.setDecimals(2)
        self.success_threshold_spin.setToolTip("模拟中GDR达标的比例需超过此阈值")
        params_layout.addRow("成功率阈值:", self.success_threshold_spin)

        self.target_qty_spin = QSpinBox()
        self.target_qty_spin.setRange(1, 10)
        self.target_qty_spin.setValue(1)
        params_layout.addRow("每张卡目标数量:", self.target_qty_spin)

        self.simulations_spin = QSpinBox()
        self.simulations_spin.setRange(100, 10000)
        self.simulations_spin.setSingleStep(100)
        self.simulations_spin.setValue(1000)
        params_layout.addRow("每次模拟次数:", self.simulations_spin)

        self.max_workers_spin = QSpinBox()
        self.max_workers_spin.setRange(1, os.cpu_count() or 16)
        self.max_workers_spin.setValue(max(1, (os.cpu_count() or 8) - 2))
        params_layout.addRow("并行进程数:", self.max_workers_spin)

        left_layout.addWidget(params_group)

        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("运行分析")
        self.run_btn.clicked.connect(self._on_run_clicked)
        btn_layout.addWidget(self.run_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)
        left_layout.addLayout(btn_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat('%p%')
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        left_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("就绪")
        left_layout.addWidget(self.status_label)

        left_layout.addStretch()

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        result_group = QGroupBox("分析结果")
        result_layout = QVBoxLayout(result_group)

        result_info = QLabel("""
        <b>前进法</b>：从空集合开始，按抽取意愿降序逐个添加目标卡，
        每次添加都重新运行模拟，计算新目标集合的成功率，
        持续添加直到成功率降至阈值以下，
        返回最后一个成功率仍≥阈值的最大可达目标集合。<br><br>
        <b>后退法</b>：从完整集合开始，按错失代价升序逐个移除目标卡，
        每次移除都重新运行模拟，计算新目标集合的成功率，
        持续移除直到成功率升至阈值以上，
        返回第一个成功率超过阈值的最小必要目标集合。
        """)
        result_info.setWordWrap(True)
        result_layout.addWidget(result_info)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("padding: 8px; background: #f5f5f5; border-radius: 4px;")
        result_layout.addWidget(self.result_label)

        right_layout.addWidget(result_group)

        steps_group = QGroupBox("分析步骤")
        steps_layout = QVBoxLayout(steps_group)

        self.steps_table = QTableWidget()
        self.steps_table.setColumnCount(3)
        self.steps_table.setHorizontalHeaderLabels(["步骤", "目标卡集合", "成功率"])
        self.steps_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.steps_table.verticalHeader().setVisible(False)
        steps_layout.addWidget(self.steps_table)

        right_layout.addWidget(steps_group)

        self.chart_group = QGroupBox("成功率趋势")
        chart_layout = QVBoxLayout(self.chart_group)
        self.chart_webview = ChartWebView()
        chart_layout.addWidget(self.chart_webview)
        right_layout.addWidget(self.chart_group)

        splitter.addWidget(left_panel)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right_panel)
        splitter.addWidget(right_scroll)
        splitter.setSizes([350, 650])

    def _on_weight_changed(self, row, col):
        if row < 0 or col < 0:
            return
        card_item = self.weight_table.item(row, 0)
        if not card_item:
            return
        card_id = card_item.text()

        if col == 1:
            desire_item = self.weight_table.item(row, col)
            try:
                self._weights[card_id]['desire_weight'] = float(desire_item.text())
            except (ValueError, AttributeError):
                self._weights[card_id]['desire_weight'] = 1.0
        elif col == 2:
            miss_cost_item = self.weight_table.item(row, col)
            try:
                self._weights[card_id]['miss_cost_weight'] = float(miss_cost_item.text())
            except (ValueError, AttributeError):
                self._weights[card_id]['miss_cost_weight'] = 1.0

    def _get_weights(self):
        desire_weights = {}
        miss_cost_weights = {}
        for card_id, weights in self._weights.items():
            desire_weights[card_id] = weights['desire_weight']
            miss_cost_weights[card_id] = weights['miss_cost_weight']
        return desire_weights, miss_cost_weights

    def _on_gdr_changed(self, index):
        key = self.gdr_combo.currentData()
        default = get_default_threshold(key)
        self.gdr_threshold_spin.setValue(default)

    def _on_run_clicked(self):
        if not self._store:
            self.status_update.emit("请先加载配置")
            return

        all_ids = [tc.card_id for tc in self._store.target_cards]
        if not all_ids:
            self.status_update.emit("请先在配置中添加目标卡")
            return

        method = 'forward' if self.method_combo.currentText() == '前进法' else 'backward'
        success_threshold = self.success_threshold_spin.value()
        target_qty = self.target_qty_spin.value()
        num_simulations = self.simulations_spin.value()
        desire_weights, miss_cost_weights = self._get_weights()

        card_value_weights = None
        if self._config_panel:
            card_value_weights = self._config_panel.get_card_value_weights()

        gdr_key = self.gdr_combo.currentData() or 'target_achievement'

        self._worker = StrategyWorker(
            method=method,
            all_target_ids=all_ids,
            desire_weights=desire_weights,
            miss_cost_weights=miss_cost_weights,
            card_value_weights=card_value_weights,
            success_threshold=success_threshold,
            target_qty=target_qty,
            num_simulations=num_simulations,
            gdr_key=gdr_key,
            gdr_threshold=self.gdr_threshold_spin.value(),
            config_store=self._store,
            max_workers=self.max_workers_spin.value(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._worker.start()

    def _on_stop_clicked(self):
        if self._worker:
            self._worker.stop()
            self._worker.wait()

    def _on_progress(self, msg, pct):
        self.status_label.setText(msg)
        self.progress_bar.setValue(pct)
        self.status_update.emit(msg)

    def _on_finished(self, result, method):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if result is None:
            self.status_update.emit("分析已停止")
            return

        if method == 'forward':
            self._display_forward_result(result)
        else:
            self._display_backward_result(result)

        self.status_update.emit("分析完成")

    def _display_forward_result(self, result):
        self.result_label.setText(f"""
<p><b>最终目标卡集合:</b> {', '.join(sorted(result.final_target_set)) if result.final_target_set else '(空)'}</p>
<p><b>最终成功率:</b> {result.final_success_probability:.2%}</p>
<p><b>目标规格:</b> {result.final_target_specs}</p>
        """)

        self.steps_table.setRowCount(len(result.steps))
        for i, step in enumerate(result.steps):
            self.steps_table.setItem(i, 0, QTableWidgetItem(f"添加 {step.added_card_id}"))
            self.steps_table.setItem(i, 1, QTableWidgetItem(', '.join(sorted(step.target_set))))
            self.steps_table.setItem(i, 2, QTableWidgetItem(f"{step.success_probability:.2%}"))

        self._draw_strategy_chart(result, 'forward')

    def _display_backward_result(self, result):
        self.result_label.setText(f"""
<p><b>最终目标卡集合:</b> {', '.join(sorted(result.final_target_set)) if result.final_target_set else '(空)'}</p>
<p><b>最终成功率:</b> {result.final_success_probability:.2%}</p>
<p><b>目标规格:</b> {result.final_target_specs}</p>
        """)

        self.steps_table.setRowCount(len(result.steps))
        for i, step in enumerate(result.steps):
            self.steps_table.setItem(i, 0, QTableWidgetItem(f"移除 {step.removed_card_id}"))
            self.steps_table.setItem(i, 1, QTableWidgetItem(', '.join(sorted(step.target_set))))
            self.steps_table.setItem(i, 2, QTableWidgetItem(f"{step.success_probability:.2%}"))

        self._draw_strategy_chart(result, 'backward')

    def _draw_strategy_chart(self, result, method):
        if not result or not result.steps:
            self.chart_webview.show_message("无数据")
            return

        from ..visualization.chart_spec import scatter, ChartAnnotation
        import numpy as np

        steps = result.steps
        if method == "forward":
            x_labels = [f"+{s.added_card_id}" for s in steps]
            x_title = "步骤（添加目标卡）"
        else:
            x_labels = [f"-{s.removed_card_id}" for s in steps]
            x_title = "步骤（移除目标卡）"

        x = np.arange(1, len(steps) + 1)
        y = np.array([s.success_probability for s in steps], dtype=float)
        target_counts = [len(s.target_set) for s in steps]

        threshold = self.success_threshold_spin.value()
        spec = scatter(
            x=x, y=y, mode="lines+markers",
            title="成功率随目标卡变化趋势",
            xlabel=x_title,
            ylabel="成功率",
            color="#2196F3",
            annotations=[
                ChartAnnotation(type="hline", value=threshold, color="#F44336",
                              text=f"阈值 {threshold:.0%}"),
            ],
        )
        self.chart_webview.set_chart(spec)

    def _on_error(self, e):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_update.emit(f"分析失败: {e}")
        self.result_label.setText(f"<p style='color: red'>错误: {e}</p>")

    def refresh_from_store(self):
        self._load_weights()
